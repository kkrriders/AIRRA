"""
Prometheus client for querying metrics.

Senior Engineering Note:
- PromQL query abstraction
- Metric data normalization
- Connection pooling via httpx
- Async HTTP requests
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)


class MetricDataPoint(BaseModel):
    """Single metric data point."""

    timestamp: float
    value: float


class MetricResult(BaseModel):
    """Result of a Prometheus query."""

    metric_name: str
    labels: dict[str, str]
    values: list[MetricDataPoint]


class PrometheusClient:
    """
    Async Prometheus client for querying metrics.

    Uses httpx for async HTTP requests with connection pooling.
    """

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()

    async def query(
        self,
        query: str,
        time: Optional[datetime] = None,
    ) -> list[MetricResult]:
        """
        Execute an instant query.

        Args:
            query: PromQL query string
            time: Evaluation timestamp (defaults to now)

        Returns:
            List of metric results
        """
        url = f"{self.base_url}/api/v1/query"

        params: dict[str, Any] = {"query": query}
        if time:
            params["time"] = time.timestamp()

        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()

            data = response.json()
            if data["status"] != "success":
                raise ValueError(f"Prometheus query failed: {data.get('error', 'Unknown error')}")

            return self._parse_response(data["data"])

        except httpx.HTTPError as e:
            logger.error(f"Prometheus HTTP error: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Prometheus query error: {str(e)}")
            raise

    async def query_range(
        self,
        query: str,
        start: datetime,
        end: datetime,
        step: str = "15s",
    ) -> list[MetricResult]:
        """
        Execute a range query.

        Args:
            query: PromQL query string
            start: Start timestamp
            end: End timestamp
            step: Query resolution step (e.g., "15s", "1m")

        Returns:
            List of metric results with time series data
        """
        url = f"{self.base_url}/api/v1/query_range"

        params = {
            "query": query,
            "start": start.timestamp(),
            "end": end.timestamp(),
            "step": step,
        }

        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()

            data = response.json()
            if data["status"] != "success":
                raise ValueError(f"Prometheus query failed: {data.get('error', 'Unknown error')}")

            return self._parse_response(data["data"])

        except httpx.HTTPError as e:
            logger.error(f"Prometheus HTTP error: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Prometheus range query error: {str(e)}")
            raise

    def _parse_response(self, data: dict) -> list[MetricResult]:
        """Parse Prometheus API response into MetricResult objects."""
        results = []

        result_type = data.get("resultType")
        if result_type not in ("vector", "matrix"):
            logger.warning(f"Unsupported result type: {result_type}")
            return results

        for result in data.get("result", []):
            metric_labels = result.get("metric", {})
            metric_name = metric_labels.pop("__name__", "unknown")

            values = []
            if result_type == "vector":
                # Instant query: single value
                value_data = result.get("value", [])
                if len(value_data) == 2:
                    values.append(
                        MetricDataPoint(
                            timestamp=float(value_data[0]),
                            value=float(value_data[1]),
                        )
                    )
            elif result_type == "matrix":
                # Range query: multiple values
                for value_data in result.get("values", []):
                    if len(value_data) == 2:
                        values.append(
                            MetricDataPoint(
                                timestamp=float(value_data[0]),
                                value=float(value_data[1]),
                            )
                        )

            results.append(
                MetricResult(
                    metric_name=metric_name,
                    labels=metric_labels,
                    values=values,
                )
            )

        return results

    async def get_service_metrics(
        self,
        service_name: str,
        lookback_minutes: int = 5,
    ) -> dict[str, list[MetricResult]]:
        """
        Get common metrics for a service.

        Senior Engineering Note:
        This is a convenience method that queries multiple metrics in parallel.
        In production, you'd customize these queries based on your stack.
        """
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=lookback_minutes)

        # Query the demo Gauge metrics exposed at /demo/metrics.
        # These are scraped by the 'airra-demo-services' Prometheus job (15 s interval).
        # Gauge queries work directly with query_range — no rate() wrapper needed.
        queries = {
            "request_rate": f'airra_demo_request_rate{{service="{service_name}"}}',
            "error_rate":   f'airra_demo_error_rate{{service="{service_name}"}}',
            "latency_p95":  f'airra_demo_latency_p95{{service="{service_name}"}}',
            "cpu_usage":    f'airra_demo_cpu_usage{{service="{service_name}"}}',
            "memory_usage": f'airra_demo_memory_bytes{{service="{service_name}"}}',
        }

        results = {}
        for name, query in queries.items():
            try:
                results[name] = await self.query_range(query, start, end)
            except Exception as e:
                logger.error(f"Failed to query {name}: {str(e)}")
                results[name] = []

        return results


_prometheus_client: PrometheusClient | None = None


def get_prometheus_client() -> PrometheusClient:
    """Get singleton Prometheus client to avoid connection leaks."""
    global _prometheus_client
    if _prometheus_client is None:
        _prometheus_client = PrometheusClient(base_url=settings.prometheus_url)
    return _prometheus_client


async def close_prometheus_client() -> None:
    """Close the singleton Prometheus client. Call during app shutdown."""
    global _prometheus_client
    if _prometheus_client is not None:
        await _prometheus_client.close()
        _prometheus_client = None
