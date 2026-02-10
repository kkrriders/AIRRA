
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from app.config import settings
from app.core.perception.anomaly_detector import AnomalyDetector, categorize_anomaly
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
        self.is_running = False
        self.recent_incidents: dict[str, datetime] = {}  # service -> last incident time
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

            # Check services concurrently with bounded parallelism
            tasks = [
                self._check_service(service_name, prom_client, anomaly_detector)
                for service_name in monitored_services
                if not self._is_recently_reported(service_name)
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
                    self.recent_incidents[service_name] = datetime.utcnow()

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

    def _is_recently_reported(self, service_name: str) -> bool:
        """Check if we recently created an incident for this service."""
        if service_name not in self.recent_incidents:
            return False

        last_incident_time = self.recent_incidents[service_name]
        time_since_last = datetime.utcnow() - last_incident_time

        return time_since_last < self.deduplication_window

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
                    detected_at=datetime.utcnow(),
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
