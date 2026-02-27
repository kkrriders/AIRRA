"""
Blast-radius awareness for impact-based decision making.

Senior Engineering Note:
- AIRRA needs to understand: "How many users/services does this affect?"
- Not all service failures are equal
- Blast radius determines action urgency
- Small blast → wait and observe
- Large blast → act aggressively
- This is real SRE thinking
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from app.services.dependency_graph import get_dependency_graph
from app.services.prometheus_client import PrometheusClient

logger = logging.getLogger(__name__)


class BlastRadiusLevel(str, Enum):
    """Blast radius severity levels."""

    MINIMAL = "minimal"  # Single service, low traffic
    LOW = "low"  # Few downstream services
    MEDIUM = "medium"  # Multiple downstream services
    HIGH = "high"  # Critical services affected
    CRITICAL = "critical"  # Cascading failure, many services


@dataclass
class BlastRadiusAssessment:
    """Assessment of incident blast radius."""

    level: BlastRadiusLevel
    score: float  # 0.0-1.0
    affected_services_count: int
    downstream_services: list[str]
    request_volume_per_second: float
    error_propagation_percentage: float  # % of downstream services showing errors
    estimated_users_impacted: int
    revenue_impact_per_hour: float  # Estimated $ per hour
    urgency_multiplier: float  # Multiplier for action prioritization (1.0-5.0)
    assessment_timestamp: datetime
    details: dict


class BlastRadiusCalculator:
    """
    Calculate blast radius of incidents to determine action urgency.

    Blast radius = impact scope
    Small blast → wait and observe (might self-heal)
    Large blast → act aggressively (revenue impact)
    """

    def __init__(
        self,
        prometheus_client: PrometheusClient,
        users_per_rps: float = 10.0,  # Estimated users per request/sec
        revenue_per_user_hour: float = 0.01,  # Estimated $ per user per hour
    ):
        """
        Initialize blast radius calculator.

        Args:
            prometheus_client: Prometheus client for metrics
            users_per_rps: Estimated users per request per second
            revenue_per_user_hour: Estimated revenue impact per user per hour
        """
        self.prometheus_client = prometheus_client
        self.users_per_rps = users_per_rps
        self.revenue_per_user_hour = revenue_per_user_hour

    async def calculate_blast_radius(
        self,
        service_name: str,
        incident_start_time: Optional[datetime] = None,
    ) -> BlastRadiusAssessment:
        """
        Calculate blast radius for a service incident.

        Factors:
        1. Number of downstream services affected
        2. Request volume (QPS)
        3. Error propagation percentage
        4. Service criticality
        5. User impact estimate
        6. Revenue impact estimate

        Args:
            service_name: Service experiencing issues
            incident_start_time: When incident started (None = now)

        Returns:
            BlastRadiusAssessment with impact details
        """
        logger.info(f"Calculating blast radius for {service_name}")

        if incident_start_time is None:
            incident_start_time = datetime.now(timezone.utc)

        # Get dependency information
        dep_graph = get_dependency_graph()
        downstream_services = dep_graph.get_downstream_dependents(service_name)
        service_info = dep_graph.get_service_info(service_name)

        # Calculate request volume
        request_volume = await self._get_request_volume(service_name)

        # Calculate error propagation
        error_propagation = await self._calculate_error_propagation(
            service_name,
            downstream_services,
        )

        # Estimate user impact
        users_impacted = int(request_volume * self.users_per_rps)

        # Estimate revenue impact
        revenue_impact = users_impacted * self.revenue_per_user_hour

        # Calculate blast radius score (0.0-1.0)
        score = self._calculate_blast_score(
            downstream_count=len(downstream_services),
            request_volume=request_volume,
            error_propagation=error_propagation,
            criticality=service_info.criticality if service_info else "medium",
        )

        # Determine blast radius level
        level = self._score_to_level(score)

        # Calculate urgency multiplier
        urgency_multiplier = self._calculate_urgency(score, level)

        assessment = BlastRadiusAssessment(
            level=level,
            score=score,
            affected_services_count=len(downstream_services),
            downstream_services=downstream_services,
            request_volume_per_second=request_volume,
            error_propagation_percentage=error_propagation * 100,
            estimated_users_impacted=users_impacted,
            revenue_impact_per_hour=revenue_impact,
            urgency_multiplier=urgency_multiplier,
            assessment_timestamp=datetime.now(timezone.utc),
            details={
                "service": service_name,
                "tier": service_info.tier if service_info else "unknown",
                "criticality": service_info.criticality if service_info else "medium",
                "incident_start": incident_start_time.isoformat(),
            },
        )

        logger.info(
            f"Blast radius for {service_name}: {level.value} "
            f"(score: {score:.2f}, downstream: {len(downstream_services)}, "
            f"QPS: {request_volume:.1f}, urgency: {urgency_multiplier:.1f}x)"
        )

        return assessment

    async def _get_request_volume(self, service_name: str) -> float:
        """
        Get current request volume (requests per second).

        Args:
            service_name: Service to check

        Returns:
            Requests per second
        """
        try:
            # Query for request rate over last 5 minutes
            query = f'rate(http_requests_total{{service="{service_name}"}}[5m])'
            results = await self.prometheus_client.query(query)

            if results and results[0].values:
                # Get most recent value
                return results[0].values[-1].value

        except Exception as e:
            logger.warning(f"Failed to get request volume for {service_name}: {e}")

        # Default to moderate volume if unable to determine
        return 10.0

    async def _calculate_error_propagation(
        self,
        service_name: str,
        downstream_services: list[str],
    ) -> float:
        """
        Calculate what percentage of downstream services are showing errors.

        Args:
            service_name: Failing service
            downstream_services: List of downstream services

        Returns:
            Error propagation ratio (0.0-1.0)
        """
        if not downstream_services:
            return 0.0

        try:
            affected_count = 0

            for downstream in downstream_services:
                # Check if downstream service has elevated error rate
                query = f'rate(http_requests_total{{service="{downstream}",status=~"5.."}}[5m]) > 0.01'
                results = await self.prometheus_client.query(query)

                if results and results[0].values:
                    affected_count += 1

            return affected_count / len(downstream_services)

        except Exception as e:
            logger.warning(f"Failed to calculate error propagation: {e}")
            return 0.0

    def _calculate_blast_score(
        self,
        downstream_count: int,
        request_volume: float,
        error_propagation: float,
        criticality: str,
    ) -> float:
        """
        Calculate overall blast radius score.

        Formula:
        - Downstream impact: 30% weight (more services = bigger blast)
        - Request volume: 25% weight (more traffic = more users)
        - Error propagation: 25% weight (cascading failures)
        - Service criticality: 20% weight (tier-1 vs tier-3)

        Args:
            downstream_count: Number of downstream services
            request_volume: Requests per second
            error_propagation: Error propagation ratio
            criticality: Service criticality level

        Returns:
            Blast score 0.0-1.0
        """
        # Downstream impact (normalize to 0-1)
        # 0 services = 0.0, 10+ services = 1.0
        downstream_score = min(1.0, downstream_count / 10.0)

        # Request volume impact (normalize to 0-1)
        # 0 RPS = 0.0, 100+ RPS = 1.0
        volume_score = min(1.0, request_volume / 100.0)

        # Error propagation is already 0-1

        # Criticality score
        criticality_map = {
            "low": 0.2,
            "medium": 0.5,
            "high": 0.7,
            "critical": 1.0,
        }
        criticality_score = criticality_map.get(criticality, 0.5)

        # Weighted combination
        blast_score = (
            downstream_score * 0.30 +
            volume_score * 0.25 +
            error_propagation * 0.25 +
            criticality_score * 0.20
        )

        return min(1.0, max(0.0, blast_score))

    def _score_to_level(self, score: float) -> BlastRadiusLevel:
        """Convert blast score to severity level."""
        if score >= 0.8:
            return BlastRadiusLevel.CRITICAL
        elif score >= 0.6:
            return BlastRadiusLevel.HIGH
        elif score >= 0.4:
            return BlastRadiusLevel.MEDIUM
        elif score >= 0.2:
            return BlastRadiusLevel.LOW
        else:
            return BlastRadiusLevel.MINIMAL

    def _calculate_urgency(
        self,
        blast_score: float,
        level: BlastRadiusLevel,
    ) -> float:
        """
        Calculate urgency multiplier for action prioritization.

        Small blast → 1.0x (wait and observe)
        Large blast → 5.0x (act immediately)

        Args:
            blast_score: Blast radius score
            level: Blast radius level

        Returns:
            Urgency multiplier 1.0-5.0
        """
        # Base multiplier from level
        level_multipliers = {
            BlastRadiusLevel.MINIMAL: 1.0,
            BlastRadiusLevel.LOW: 1.5,
            BlastRadiusLevel.MEDIUM: 2.5,
            BlastRadiusLevel.HIGH: 3.5,
            BlastRadiusLevel.CRITICAL: 5.0,
        }

        base_multiplier = level_multipliers[level]

        # Fine-tune based on exact score
        # This ensures smooth scaling within levels
        adjusted_multiplier = base_multiplier + (blast_score * 0.5)

        return min(5.0, max(1.0, adjusted_multiplier))

    def should_act_immediately(
        self,
        assessment: BlastRadiusAssessment,
        confidence: float,
    ) -> tuple[bool, str]:
        """
        Determine if action should be taken immediately based on blast radius.

        Decision matrix:
        - CRITICAL blast: Act immediately regardless of confidence
        - HIGH blast + high confidence: Act immediately
        - MEDIUM blast + high confidence: Act soon
        - LOW/MINIMAL blast: Wait and observe

        Args:
            assessment: Blast radius assessment
            confidence: Hypothesis confidence (0.0-1.0)

        Returns:
            Tuple of (should_act_immediately, reasoning)
        """
        level = assessment.level
        urgency = assessment.urgency_multiplier

        if level == BlastRadiusLevel.CRITICAL:
            return (
                True,
                f"CRITICAL blast radius ({assessment.affected_services_count} services, "
                f"{assessment.estimated_users_impacted} users, "
                f"${assessment.revenue_impact_per_hour:.2f}/hr) - act immediately"
            )

        if level == BlastRadiusLevel.HIGH and confidence >= 0.7:
            return (
                True,
                f"HIGH blast radius with {confidence:.0%} confidence - act immediately"
            )

        if level == BlastRadiusLevel.MEDIUM and confidence >= 0.8:
            return (
                True,
                f"MEDIUM blast radius with high confidence ({confidence:.0%}) - act soon"
            )

        if level in [BlastRadiusLevel.LOW, BlastRadiusLevel.MINIMAL]:
            return (
                False,
                f"{level.value.upper()} blast radius - wait and observe for self-healing"
            )

        return (
            False,
            f"Blast radius {level.value} with confidence {confidence:.0%} - "
            f"requires more certainty or escalation"
        )


# Global instance
_blast_radius_calculator: Optional[BlastRadiusCalculator] = None


def get_blast_radius_calculator(
    prometheus_client: PrometheusClient,
) -> BlastRadiusCalculator:
    """Get or create blast radius calculator."""
    global _blast_radius_calculator
    if _blast_radius_calculator is None:
        _blast_radius_calculator = BlastRadiusCalculator(prometheus_client)
    return _blast_radius_calculator
