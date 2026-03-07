
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.core.perception.anomaly_detector import AnomalyDetector, categorize_anomaly
from app.core.perception.signal_correlator import CorrelatedIncident, SignalCorrelator
from app.core.redis import get_redis
from app.database import get_db_context
from app.models.incident import Incident, IncidentSeverity, IncidentStatus
from app.services.prometheus_client import get_prometheus_client

logger = logging.getLogger(__name__)


class AnomalyMonitor:
    """
    Continuous monitoring service for anomaly detection.

    Polls Prometheus metrics and automatically creates incidents.
    """

    # Maximum number of concurrent Prometheus queries to avoid overwhelming
    # the metrics backend when monitoring many services.
    MAX_CONCURRENT_QUERIES = 5

    def __init__(
        self,
        poll_interval_seconds: int = 60,
        min_confidence: float = 0.75,
        deduplication_window_minutes: int = 10,
    ):
        self.poll_interval_seconds = poll_interval_seconds
        self.min_confidence = min_confidence
        self.deduplication_window = timedelta(minutes=deduplication_window_minutes)
        # In-memory fallback for dedup when Redis is unreachable.
        # Primary dedup state lives in Redis so it is shared across Celery
        # worker processes and survives restarts (IMP-2 fix).
        self._fallback_recent_incidents: dict[str, datetime] = {}
        self._query_semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_QUERIES)

    async def check_once(self) -> None:
        """
        Public facade for Celery tasks — run a single anomaly detection cycle.

        Celery monitoring tasks call this instead of the private
        _check_for_anomalies() so the contract is explicit and refactors
        to internal method names do not silently break the task (S1 fix).
        """
        await self._check_for_anomalies()

    async def _check_for_anomalies(self):
        """Check all monitored services for anomalies."""
        try:
            # Get list of services to monitor
            # In production, this would come from service registry/CMDB
            monitored_services = await self._get_monitored_services()

            prom_client = get_prometheus_client()
            anomaly_detector = AnomalyDetector(
                threshold_sigma=settings.anomaly_threshold_sigma
            )

            # Check services concurrently with bounded parallelism.
            # Deduplication is handled inside _check_service via Redis (IMP-2).
            tasks = [
                self._check_service(service_name, prom_client, anomaly_detector)
                for service_name in monitored_services
            ]

            await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            logger.error(f"Error in anomaly check cycle: {str(e)}", exc_info=True)

    async def _check_service(
        self,
        service_name: str,
        prom_client,
        anomaly_detector: AnomalyDetector,
    ):
        """Check a single service for anomalies, throttled by semaphore."""
        async with self._query_semaphore:
            try:
                # Skip services we reported recently (Redis-backed dedup shared
                # across all worker processes and restarts).
                if await self._is_recently_reported(service_name):
                    return

                # Fetch service metrics
                service_metrics = await prom_client.get_service_metrics(
                    service_name=service_name,
                    lookback_minutes=5,
                )

                # Detect anomalies
                all_metric_results = []
                for metric_name, results in service_metrics.items():
                    all_metric_results.extend(results)

                anomalies = anomaly_detector.detect_multiple(all_metric_results)

                # Filter by confidence
                significant_anomalies = [
                    a for a in anomalies if a.confidence >= self.min_confidence
                ]

                if significant_anomalies:
                    # Run multi-signal correlation.  With only Prometheus metrics
                    # the correlator returns [] (needs ≥2 signal types), so we
                    # fall back to the raw anomaly path.  When Loki/Jaeger signals
                    # are added they flow through here automatically.
                    signals = SignalCorrelator.from_anomalies(significant_anomalies)
                    correlator = SignalCorrelator()
                    correlated = await correlator.correlate_signals(
                        signals, service_filter=service_name
                    )
                    top_correlation: CorrelatedIncident | None = correlated[0] if correlated else None

                    await self._create_incident(
                        service_name, significant_anomalies, correlation=top_correlation
                    )
                    await self._mark_recently_reported(service_name)

            except Exception as e:
                logger.error(
                    f"Error checking service {service_name}: {str(e)}",
                    exc_info=True,
                )

    async def _get_monitored_services(self) -> list[str]:
        """
        Get list of services to monitor.

        Reads from the AIRRA_MONITORED_SERVICES config setting.
        Set via environment variable as a JSON array, e.g.:
            AIRRA_MONITORED_SERVICES='["payment-service","order-service"]'

        In a future iteration this could also query a service registry
        (Consul, Eureka) or the Kubernetes API.
        """
        return settings.monitored_services

    async def _is_recently_reported(self, service_name: str) -> bool:
        """
        Check if we recently created an incident for this service.

        Primary state is a Redis key with a TTL matching the deduplication window.
        This is shared across all Celery worker processes and survives restarts,
        preventing duplicate incidents from N concurrent workers (IMP-2 fix).

        Falls back to the in-memory dict if Redis is unreachable.
        """
        try:
            key = f"airra:anomaly_dedup:{service_name}"
            return bool(await get_redis().exists(key))
        except Exception as e:
            logger.warning(f"Redis dedup check failed for {service_name}, using in-memory fallback: {e}")
            last = self._fallback_recent_incidents.get(service_name)
            if last is None:
                return False
            return (datetime.now(timezone.utc) - last) < self.deduplication_window

    async def _mark_recently_reported(self, service_name: str) -> None:
        """
        Record that we just created an incident for this service.

        Sets a Redis key with TTL = deduplication_window so the key
        auto-expires exactly when the window closes. Falls back to
        the in-memory dict if Redis is unreachable.
        """
        try:
            key = f"airra:anomaly_dedup:{service_name}"
            ttl = int(self.deduplication_window.total_seconds())
            await get_redis().set(key, "1", ex=ttl)
        except Exception as e:
            logger.warning(f"Redis dedup mark failed for {service_name}, using in-memory fallback: {e}")
            self._fallback_recent_incidents[service_name] = datetime.now(timezone.utc)

    async def _create_incident(
        self,
        service_name: str,
        anomalies: list,
        correlation: "CorrelatedIncident | None" = None,
    ):
        """Create an incident from detected anomalies.

        When a CorrelatedIncident is supplied (i.e. multi-signal correlation
        succeeded), its confidence score and signal count are embedded in the
        incident context for downstream consumers (learning engine, analytics).
        """
        try:
            # Determine severity based on anomaly scores
            max_deviation = max(a.deviation_sigma for a in anomalies)
            if max_deviation >= 5.0:
                severity = IncidentSeverity.CRITICAL
            elif max_deviation >= 4.0:
                severity = IncidentSeverity.HIGH
            elif max_deviation >= 3.0:
                severity = IncidentSeverity.MEDIUM
            else:
                severity = IncidentSeverity.LOW

            # Build description
            anomaly_summaries = []
            for a in anomalies[:3]:  # Top 3 anomalies
                category = categorize_anomaly(a)
                anomaly_summaries.append(
                    f"{a.metric_name}: {category} "
                    f"({a.deviation_sigma:.1f}σ deviation)"
                )

            description = "Automatically detected anomalies:\n" + "\n".join(
                f"- {s}" for s in anomaly_summaries
            )

            # Create metrics snapshot
            metrics_snapshot = {
                a.metric_name: {
                    "current": a.current_value,
                    "expected": a.expected_value,
                    "deviation_sigma": a.deviation_sigma,
                }
                for a in anomalies
            }

            incident_context: dict = {
                "anomaly_count": len(anomalies),
                "max_deviation": max_deviation,
                "auto_detected": True,
            }
            if correlation is not None:
                incident_context["correlation_confidence"] = round(correlation.confidence, 4)
                incident_context["correlated_signal_count"] = len(correlation.signals)

            # Service dependency context — enriches incident embedding + LLM prompt
            try:
                from app.services.dependency_graph import get_dependency_graph
                dep_graph = get_dependency_graph()
                upstream = dep_graph.get_upstream_dependencies(service_name)
                if upstream:
                    incident_context["upstream_dependencies"] = upstream
                svc_info = dep_graph.get_service_info(service_name)
                if svc_info:
                    incident_context["service_criticality"] = svc_info.criticality
                    if svc_info.tier:
                        incident_context["service_tier"] = svc_info.tier
            except Exception as dep_exc:
                logger.debug(f"Dependency graph lookup failed for {service_name}: {dep_exc}")

            # Wire blast radius (best-effort — failure must never block incident creation)
            try:
                from app.core.decision.blast_radius import get_blast_radius_calculator
                blast_calc = get_blast_radius_calculator(get_prometheus_client())
                assessment = await blast_calc.calculate_blast_radius(service_name)
                incident_context["blast_radius"] = {
                    "level": assessment.level.value,
                    "score": round(assessment.score, 3),
                    "affected_services_count": assessment.affected_services_count,
                    "urgency_multiplier": round(assessment.urgency_multiplier, 2),
                }
            except Exception as blast_exc:
                logger.warning(f"Blast radius calculation failed for {service_name}: {blast_exc}")

            # Create incident
            async with get_db_context() as db:
                incident = Incident(
                    title=f"Anomalies detected in {service_name}",
                    description=description,
                    severity=severity,
                    status=IncidentStatus.DETECTED,
                    affected_service=service_name,
                    affected_components=[service_name],
                    detected_at=datetime.now(timezone.utc),
                    detection_source="airra_monitor",
                    metrics_snapshot=metrics_snapshot,
                    context=incident_context,
                )

                db.add(incident)
                await db.commit()
                await db.refresh(incident)

                logger.info(
                    f"Created incident {incident.id} for {service_name} "
                    f"(severity: {severity.value}, anomalies: {len(anomalies)})"
                )

                # Stage 6: Generate embedding asynchronously so future vector search
                # can retrieve this incident as a past case.
                from app.worker.tasks.embedding import embed_incident_task
                embed_incident_task.delay(str(incident.id))

        except Exception as e:
            logger.error(f"Failed to create incident for {service_name}: {str(e)}")


# Global monitor instance
_monitor: AnomalyMonitor | None = None


def get_monitor() -> AnomalyMonitor:
    """Get the global monitor instance."""
    global _monitor
    if _monitor is None:
        _monitor = AnomalyMonitor()
    return _monitor


