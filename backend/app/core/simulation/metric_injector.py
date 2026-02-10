"""
Metric Injector for Incident Simulation.

Communicates with the mock service to inject realistic metrics that simulate
incidents. The mock service exposes Prometheus endpoints with these metrics.
"""
import asyncio
import logging
from typing import Dict, Optional
from datetime import datetime

import httpx

from app.core.simulation.scenario_definitions import IncidentScenario, MetricPattern

logger = logging.getLogger(__name__)


class MetricInjector:
    """
    Injects metrics into mock service for incident simulation.

    The mock payment service provides endpoints:
    - POST /trigger-incident: Start injecting anomalous metrics
    - POST /resolve-incident: Return metrics to normal
    - GET /metrics: Prometheus endpoint with current metrics
    """

    def __init__(self, mock_service_url: str = "http://localhost:5001"):
        """
        Initialize the metric injector.

        Args:
            mock_service_url: Base URL of the mock service
        """
        self.mock_service_url = mock_service_url
        self._http_client: Optional[httpx.AsyncClient] = None
        self._auto_stop_task: Optional[asyncio.Task] = None
        self._active_scenario_id: Optional[str] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=10.0)
        return self._http_client

    async def inject_scenario(
        self,
        scenario: IncidentScenario,
        auto_stop: bool = True,
    ) -> Dict:
        """
        Start injecting metrics for a scenario.

        Args:
            scenario: The scenario to simulate
            auto_stop: If True, automatically stop after scenario.duration_seconds

        Returns:
            Dict with status and details

        Raises:
            Exception: If mock service is unavailable or injection fails
        """
        try:
            logger.info(
                f"Injecting scenario '{scenario.scenario_id}' into mock service "
                f"at {self.mock_service_url}"
            )

            # Build payload for mock service
            # The mock service expects: {"incident_type": str, "metrics": dict}
            payload = {
                "incident_type": scenario.scenario_id,
                "metrics": self._build_metrics_payload(scenario.metrics),
                "duration_seconds": scenario.duration_seconds,
            }

            client = await self._get_client()
            response = await client.post(
                f"{self.mock_service_url}/trigger-incident",
                json=payload,
            )

            response.raise_for_status()
            result = response.json()

            self._active_scenario_id = scenario.scenario_id
            logger.info(f"Successfully triggered incident: {result}")

            # Schedule auto-stop if requested
            if auto_stop and scenario.duration_seconds > 0:
                self._auto_stop_task = asyncio.create_task(
                    self._auto_stop_after_delay(
                        scenario.scenario_id,
                        scenario.duration_seconds,
                    )
                )
                logger.info(
                    f"Scheduled auto-stop in {scenario.duration_seconds} seconds"
                )

            return {
                "status": "injected",
                "scenario_id": scenario.scenario_id,
                "mock_service_url": self.mock_service_url,
                "auto_stop_scheduled": auto_stop,
                "duration_seconds": scenario.duration_seconds if auto_stop else None,
                "injected_at": datetime.utcnow().isoformat(),
            }

        except httpx.HTTPError as e:
            logger.error(f"Failed to inject metrics: {str(e)}")
            raise Exception(
                f"Mock service unavailable at {self.mock_service_url}. "
                f"Please ensure it's running: python mock-services/payment-service.py"
            ) from e

    async def stop_injection(self, scenario_id: Optional[str] = None) -> Dict:
        """
        Stop metric injection and return to normal.

        Args:
            scenario_id: Optional scenario ID for validation

        Returns:
            Dict with status and details
        """
        try:
            if scenario_id and scenario_id != self._active_scenario_id:
                logger.warning(
                    f"Requested stop for '{scenario_id}' but active scenario "
                    f"is '{self._active_scenario_id}'"
                )

            logger.info(
                f"Stopping metric injection for scenario: "
                f"{self._active_scenario_id or scenario_id or 'any'}"
            )

            client = await self._get_client()
            response = await client.post(
                f"{self.mock_service_url}/resolve-incident",
                json={},
            )

            response.raise_for_status()
            result = response.json()

            # Cancel auto-stop task if running
            if self._auto_stop_task and not self._auto_stop_task.done():
                self._auto_stop_task.cancel()
                logger.info("Cancelled auto-stop task")

            previous_scenario = self._active_scenario_id
            self._active_scenario_id = None

            logger.info(f"Successfully stopped injection: {result}")

            return {
                "status": "stopped",
                "previous_scenario_id": previous_scenario,
                "stopped_at": datetime.utcnow().isoformat(),
            }

        except httpx.HTTPError as e:
            logger.error(f"Failed to stop metrics: {str(e)}")
            raise Exception(
                f"Mock service unavailable at {self.mock_service_url}"
            ) from e

    async def check_health(self) -> bool:
        """
        Check if mock service is available.

        Returns:
            True if service is healthy, False otherwise
        """
        try:
            client = await self._get_client()
            response = await client.get(
                f"{self.mock_service_url}/health",
                timeout=2.0,
            )
            return response.status_code == 200
        except Exception:
            return False

    async def _auto_stop_after_delay(
        self,
        scenario_id: str,
        delay_seconds: int,
    ) -> None:
        """
        Automatically stop injection after delay.

        Args:
            scenario_id: Scenario being stopped
            delay_seconds: Delay before stopping
        """
        try:
            logger.info(
                f"Auto-stop scheduled for '{scenario_id}' in {delay_seconds}s"
            )
            await asyncio.sleep(delay_seconds)

            logger.info(f"Auto-stopping scenario '{scenario_id}'")
            await self.stop_injection(scenario_id)

        except asyncio.CancelledError:
            logger.info(f"Auto-stop cancelled for '{scenario_id}'")
        except Exception as e:
            logger.error(f"Auto-stop failed: {str(e)}", exc_info=True)

    def _build_metrics_payload(self, metrics: list[MetricPattern]) -> Dict:
        """
        Convert scenario metrics to mock service format.

        Args:
            metrics: List of metric patterns from scenario

        Returns:
            Dict suitable for mock service API
        """
        payload = {}
        for metric in metrics:
            # Mock service expects: {metric_name: value}
            # For now, we just send the target value
            # Future enhancement: send pattern type and duration for realistic evolution
            payload[metric.metric_name] = {
                "value": metric.value,
                "baseline": metric.baseline,
                "pattern_type": metric.pattern_type.value,
            }

        return payload

    async def close(self) -> None:
        """Clean up resources."""
        if self._auto_stop_task and not self._auto_stop_task.done():
            self._auto_stop_task.cancel()

        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None


# ============================================
# Singleton Instance
# ============================================

_injector_instance: Optional[MetricInjector] = None


def get_metric_injector(mock_service_url: str = "http://localhost:5001") -> MetricInjector:
    """
    Get or create the singleton metric injector instance.

    Args:
        mock_service_url: Base URL of the mock service

    Returns:
        MetricInjector instance
    """
    global _injector_instance

    if _injector_instance is None:
        _injector_instance = MetricInjector(mock_service_url)
        logger.info(f"Created MetricInjector for {mock_service_url}")

    return _injector_instance
