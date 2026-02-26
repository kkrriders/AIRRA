
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis.asyncio as aioredis

from app.config import settings
from app.core.perception.anomaly_detector import AnomalyDetector, categorize_anomaly
from app.database import get_db_context
from app.models.incident import Incident, IncidentSeverity, IncidentStatus
from app.services.prometheus_client import get_prometheus_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level Redis client for anomaly deduplication.
# Shared across all check_once() calls in the same worker process.
# ---------------------------------------------------------------------------
_redis_client: Optional[aioredis.Redis] = None


def _get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            str(settings.redis_url),
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _redis_client


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
        self.is_running = False
        # In-memory fallback for dedup when Redis is unreachable.
        # Primary dedup state lives in Redis so it is shared across Celery
        # worker processes and survives restarts (IMP-2 fix).
        self._fallback_recent_incidents: dict[str, datetime] = {}
        self._query_semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_QUERIES)

    async def start(self):
        """Start the monitoring loop."""
        self.is_running = True
        logger.info("Anomaly monitor started")

        while self.is_running:
            try:
                await self._check_for_anomalies()
            except Exception as e:
                logger.error(
                    f"Anomaly monitor error (will retry next cycle): {str(e)}",
                    exc_info=True,
                )
            await asyncio.sleep(self.poll_interval_seconds)

    async def stop(self):
        """Stop the monitoring loop."""
        self.is_running = False
        logger.info("Anomaly monitor stopped")

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
                    await self._create_incident(service_name, significant_anomalies)
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
            return bool(await _get_redis().exists(key))
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
            await _get_redis().set(key, "1", ex=ttl)
        except Exception as e:
            logger.warning(f"Redis dedup mark failed for {service_name}, using in-memory fallback: {e}")
            self._fallback_recent_incidents[service_name] = datetime.now(timezone.utc)

    async def _create_incident(self, service_name: str, anomalies: list):
        """Create an incident from detected anomalies."""
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
                    context={
                        "anomaly_count": len(anomalies),
                        "max_deviation": max_deviation,
                        "auto_detected": True,
                    },
                )

                db.add(incident)
                await db.commit()
                await db.refresh(incident)

                logger.info(
                    f"Created incident {incident.id} for {service_name} "
                    f"(severity: {severity.value}, anomalies: {len(anomalies)})"
                )

                # Optionally trigger automatic analysis
                if settings.environment == "production":
                    # In production, you might want to trigger analysis immediately
                    # for high-severity incidents
                    if severity in [IncidentSeverity.CRITICAL, IncidentSeverity.HIGH]:
                        logger.info(f"Auto-triggering analysis for incident {incident.id}")
                        # TODO: Trigger analysis asynchronously
                        # await trigger_incident_analysis(incident.id)

        except Exception as e:
            logger.error(f"Failed to create incident for {service_name}: {str(e)}")


# Global monitor instance
_monitor: Optional[AnomalyMonitor] = None


def get_monitor() -> AnomalyMonitor:
    """Get the global monitor instance."""
    global _monitor
    if _monitor is None:
        _monitor = AnomalyMonitor()
    return _monitor


async def start_anomaly_monitor():
    """Start the anomaly monitoring background task."""
    monitor = get_monitor()
    if not monitor.is_running:
        asyncio.create_task(monitor.start())
        logger.info("Anomaly monitor background task started")


async def stop_anomaly_monitor():
    """Stop the anomaly monitoring background task."""
    monitor = get_monitor()
    if monitor.is_running:
        await monitor.stop()
        logger.info("Anomaly monitor background task stopped")
