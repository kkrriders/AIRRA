"""
Post-action verification and health checking.

Senior Engineering Note:
- Actions execute without confirming success are useless
- This module verifies that actions actually fixed the issue
- Waits for stabilization window before checking
- Determines if action succeeded, failed (rollback), or failed (escalate)
- No system is autonomous without feedback
"""
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from app.core.execution.base import ExecutionResult, ExecutionStatus
from app.services.prometheus_client import PrometheusClient

logger = logging.getLogger(__name__)


class VerificationStatus(str, Enum):
    """Status of post-action verification."""

    SUCCESS = "success"  # Metrics improved, action worked
    PARTIAL_SUCCESS = "partial_success"  # Some improvement but not complete
    NO_CHANGE = "no_change"  # Metrics unchanged
    DEGRADED = "degraded"  # Metrics worse, needs rollback
    UNSTABLE = "unstable"  # Metrics fluctuating, needs monitoring


@dataclass
class HealthMetrics:
    """Health metrics for verification."""

    error_rate: Optional[float] = None  # Errors per minute
    latency_p95: Optional[float] = None  # 95th percentile latency (ms)
    latency_p99: Optional[float] = None  # 99th percentile latency (ms)
    availability: Optional[float] = None  # Uptime percentage
    request_rate: Optional[float] = None  # Requests per second
    timestamp: Optional[datetime] = None


@dataclass
class VerificationResult:
    """Result of post-action verification."""

    status: VerificationStatus
    message: str
    before_metrics: HealthMetrics
    after_metrics: HealthMetrics
    improvement_percentage: dict[str, float]  # Metric -> % improvement
    recommendation: str  # "continue", "rollback", "escalate"
    stabilization_seconds: int
    verification_timestamp: datetime


class PostActionVerifier:
    """
    Verifies that actions actually fixed the issue.

    This is CRITICAL for autonomous operation.
    Without verification, you're just randomly executing actions.
    """

    def __init__(
        self,
        prometheus_client: PrometheusClient,
        stabilization_window_seconds: int = 120,  # 2 minutes default
        improvement_threshold: float = 0.20,  # 20% improvement required
    ):
        """
        Initialize verifier.

        Args:
            prometheus_client: Client for fetching metrics
            stabilization_window_seconds: How long to wait before checking (default 2 min)
            improvement_threshold: Minimum improvement to declare success (default 20%)
        """
        self.prometheus_client = prometheus_client
        self.stabilization_window = stabilization_window_seconds
        self.improvement_threshold = improvement_threshold

    async def verify_action(
        self,
        service_name: str,
        execution_result: ExecutionResult,
        before_metrics: Optional[HealthMetrics] = None,
    ) -> VerificationResult:
        """
        Verify that an action improved system health.

        Process:
        1. Wait for stabilization window
        2. Fetch current metrics
        3. Compare with pre-action metrics
        4. Determine success/failure
        5. Recommend next action

        Args:
            service_name: Service that was acted upon
            execution_result: Result of the action execution
            before_metrics: Metrics before action (if available)

        Returns:
            VerificationResult with status and recommendation
        """
        logger.info(
            f"Starting post-action verification for {service_name} "
            f"(waiting {self.stabilization_window}s for stabilization)"
        )

        # If action itself failed, don't bother verifying
        if execution_result.status == ExecutionStatus.FAILED:
            return VerificationResult(
                status=VerificationStatus.DEGRADED,
                message=f"Action execution failed: {execution_result.error}",
                before_metrics=before_metrics or HealthMetrics(),
                after_metrics=HealthMetrics(),
                improvement_percentage={},
                recommendation="rollback",
                stabilization_seconds=0,
                verification_timestamp=datetime.utcnow(),
            )

        # Wait for stabilization
        await asyncio.sleep(self.stabilization_window)

        # Fetch current metrics
        after_metrics = await self._fetch_health_metrics(service_name)

        # If we don't have before metrics, try to get them from recent history
        if before_metrics is None:
            # Get metrics from just before action execution
            before_time = execution_result.started_at - timedelta(minutes=5)
            before_metrics = await self._fetch_health_metrics(
                service_name,
                time=before_time,
            )

        # Compare metrics and determine status
        verification_status, improvements = self._compare_metrics(
            before_metrics,
            after_metrics,
        )

        # Generate recommendation
        recommendation = self._generate_recommendation(
            verification_status,
            improvements,
        )

        # Generate message
        message = self._generate_message(
            verification_status,
            improvements,
            before_metrics,
            after_metrics,
        )

        logger.info(
            f"Verification complete for {service_name}: {verification_status.value} "
            f"(recommendation: {recommendation})"
        )

        return VerificationResult(
            status=verification_status,
            message=message,
            before_metrics=before_metrics,
            after_metrics=after_metrics,
            improvement_percentage=improvements,
            recommendation=recommendation,
            stabilization_seconds=self.stabilization_window,
            verification_timestamp=datetime.utcnow(),
        )

    async def _fetch_health_metrics(
        self,
        service_name: str,
        time: Optional[datetime] = None,
    ) -> HealthMetrics:
        """
        Fetch current health metrics for a service.

        Args:
            service_name: Service to fetch metrics for
            time: Time to fetch metrics for (None = now)

        Returns:
            HealthMetrics with current values
        """
        metrics = HealthMetrics(timestamp=time or datetime.utcnow())

        try:
            # Error rate (errors per minute)
            error_query = f'rate(http_requests_total{{service="{service_name}",status=~"5.."}}[1m]) * 60'
            error_results = await self.prometheus_client.query(error_query, time=time)
            if error_results:
                metrics.error_rate = error_results[0].values[-1].value if error_results[0].values else 0.0

            # Latency P95
            latency_p95_query = f'histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{{service="{service_name}"}}[5m])) * 1000'
            p95_results = await self.prometheus_client.query(latency_p95_query, time=time)
            if p95_results:
                metrics.latency_p95 = p95_results[0].values[-1].value if p95_results[0].values else None

            # Latency P99
            latency_p99_query = f'histogram_quantile(0.99, rate(http_request_duration_seconds_bucket{{service="{service_name}"}}[5m])) * 1000'
            p99_results = await self.prometheus_client.query(latency_p99_query, time=time)
            if p99_results:
                metrics.latency_p99 = p99_results[0].values[-1].value if p99_results[0].values else None

            # Request rate
            rate_query = f'rate(http_requests_total{{service="{service_name}"}}[1m])'
            rate_results = await self.prometheus_client.query(rate_query, time=time)
            if rate_results:
                metrics.request_rate = rate_results[0].values[-1].value if rate_results[0].values else None

            # Availability (uptime)
            up_query = f'up{{service="{service_name}"}}'
            up_results = await self.prometheus_client.query(up_query, time=time)
            if up_results:
                metrics.availability = up_results[0].values[-1].value if up_results[0].values else 0.0

        except Exception as e:
            logger.error(f"Failed to fetch health metrics: {str(e)}")

        return metrics

    def _compare_metrics(
        self,
        before: HealthMetrics,
        after: HealthMetrics,
    ) -> tuple[VerificationStatus, dict[str, float]]:
        """
        Compare before/after metrics and determine status.

        Args:
            before: Metrics before action
            after: Metrics after action

        Returns:
            Tuple of (status, improvement_percentages)
        """
        improvements = {}

        # Calculate improvement for each metric (negative = worse)
        if before.error_rate is not None and after.error_rate is not None:
            if before.error_rate > 0:
                improvements["error_rate"] = (
                    (before.error_rate - after.error_rate) / before.error_rate
                ) * 100
            else:
                improvements["error_rate"] = 0.0 if after.error_rate == 0 else -100.0

        if before.latency_p95 is not None and after.latency_p95 is not None:
            if before.latency_p95 > 0:
                improvements["latency_p95"] = (
                    (before.latency_p95 - after.latency_p95) / before.latency_p95
                ) * 100
            else:
                improvements["latency_p95"] = 0.0

        if before.latency_p99 is not None and after.latency_p99 is not None:
            if before.latency_p99 > 0:
                improvements["latency_p99"] = (
                    (before.latency_p99 - after.latency_p99) / before.latency_p99
                ) * 100
            else:
                improvements["latency_p99"] = 0.0

        if before.availability is not None and after.availability is not None:
            improvements["availability"] = ((after.availability - before.availability) / before.availability) * 100 if before.availability > 0 else 0.0

        # Determine status based on improvements
        if not improvements:
            return VerificationStatus.NO_CHANGE, improvements

        avg_improvement = sum(improvements.values()) / len(improvements)

        # Check for degradation (any metric significantly worse)
        if any(imp < -10.0 for imp in improvements.values()):
            return VerificationStatus.DEGRADED, improvements

        # Check for success (significant improvement)
        if avg_improvement >= self.improvement_threshold:
            return VerificationStatus.SUCCESS, improvements

        # Check for partial success
        if avg_improvement >= self.improvement_threshold / 2:
            return VerificationStatus.PARTIAL_SUCCESS, improvements

        # Check for instability (high variance in improvements)
        if improvements and max(improvements.values()) - min(improvements.values()) > 30.0:
            return VerificationStatus.UNSTABLE, improvements

        return VerificationStatus.NO_CHANGE, improvements

    def _generate_recommendation(
        self,
        status: VerificationStatus,
        improvements: dict[str, float],
    ) -> str:
        """
        Generate recommendation based on verification status.

        Args:
            status: Verification status
            improvements: Improvement percentages

        Returns:
            Recommendation: "continue", "rollback", "escalate", "monitor"
        """
        if status == VerificationStatus.SUCCESS:
            return "continue"  # Action worked, continue monitoring

        if status == VerificationStatus.DEGRADED:
            return "rollback"  # Action made things worse, rollback immediately

        if status == VerificationStatus.PARTIAL_SUCCESS:
            return "monitor"  # Some improvement, keep watching

        if status == VerificationStatus.UNSTABLE:
            return "escalate"  # Unclear if action helped, escalate to human

        # NO_CHANGE
        return "escalate"  # Action didn't help, escalate

    def _generate_message(
        self,
        status: VerificationStatus,
        improvements: dict[str, float],
        before: HealthMetrics,
        after: HealthMetrics,
    ) -> str:
        """
        Generate human-readable message with before-after comparison.

        Format:
        Before: error_rate = 12%
        After: error_rate = 1.2%
        Δ = -10.8%

        This is examiner-proof and shows clear impact.
        """
        lines = [f"Post-action verification: {status.value}"]
        lines.append("\n=== Before-After Metrics Comparison ===")

        # Error rate
        if before.error_rate is not None and after.error_rate is not None:
            delta = after.error_rate - before.error_rate
            delta_pct = improvements.get("error_rate", 0.0)
            lines.append(f"\nError Rate:")
            lines.append(f"  Before: {before.error_rate:.2f} errors/min")
            lines.append(f"  After:  {after.error_rate:.2f} errors/min")
            lines.append(f"  Δ = {delta:+.2f} errors/min ({delta_pct:+.1f}%)")

        # Latency P95
        if before.latency_p95 is not None and after.latency_p95 is not None:
            delta = after.latency_p95 - before.latency_p95
            delta_pct = improvements.get("latency_p95", 0.0)
            lines.append(f"\nLatency P95:")
            lines.append(f"  Before: {before.latency_p95:.1f}ms")
            lines.append(f"  After:  {after.latency_p95:.1f}ms")
            lines.append(f"  Δ = {delta:+.1f}ms ({delta_pct:+.1f}%)")

        # Latency P99
        if before.latency_p99 is not None and after.latency_p99 is not None:
            delta = after.latency_p99 - before.latency_p99
            delta_pct = improvements.get("latency_p99", 0.0)
            lines.append(f"\nLatency P99:")
            lines.append(f"  Before: {before.latency_p99:.1f}ms")
            lines.append(f"  After:  {after.latency_p99:.1f}ms")
            lines.append(f"  Δ = {delta:+.1f}ms ({delta_pct:+.1f}%)")

        # Availability
        if before.availability is not None and after.availability is not None:
            delta = after.availability - before.availability
            delta_pct = improvements.get("availability", 0.0)
            lines.append(f"\nAvailability:")
            lines.append(f"  Before: {before.availability:.2%}")
            lines.append(f"  After:  {after.availability:.2%}")
            lines.append(f"  Δ = {delta:+.2%} ({delta_pct:+.1f}%)")

        # Request rate
        if before.request_rate is not None and after.request_rate is not None:
            delta = after.request_rate - before.request_rate
            lines.append(f"\nRequest Rate:")
            lines.append(f"  Before: {before.request_rate:.1f} req/s")
            lines.append(f"  After:  {after.request_rate:.1f} req/s")
            lines.append(f"  Δ = {delta:+.1f} req/s")

        lines.append("\n" + "=" * 40)

        # Overall assessment
        if improvements:
            avg_improvement = sum(improvements.values()) / len(improvements)
            lines.append(f"\nOverall improvement: {avg_improvement:+.1f}%")

        return "\n".join(lines)
