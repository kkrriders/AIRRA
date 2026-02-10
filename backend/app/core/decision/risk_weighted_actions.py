"""
Risk-weighted action selection.

Senior Engineering Note:
- Not all actions are equal:
  Restarting a service ≠ rolling back deployment ≠ scaling a DB
- Each action has:
  - Risk score (probability of making things worse)
  - Downtime cost estimate
  - Recovery time if action fails
- Strategy: Pick lowest risk action that can fix the problem
- This is real production logic
"""
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app.models.action import ActionType, RiskLevel

logger = logging.getLogger(__name__)


class ActionRiskCategory(str, Enum):
    """Risk categories for actions."""

    REVERSIBLE_LOW_IMPACT = "reversible_low_impact"  # Scale up, cache clear
    REVERSIBLE_MEDIUM_IMPACT = "reversible_medium_impact"  # Scale down, restart
    IRREVERSIBLE_LOW_IMPACT = "irreversible_low_impact"  # Feature flag toggle
    IRREVERSIBLE_HIGH_IMPACT = "irreversible_high_impact"  # Rollback, drain node
    DANGEROUS = "dangerous"  # Direct database changes, data migration


@dataclass
class ActionRiskProfile:
    """Risk profile for a remediation action."""

    action_type: ActionType
    risk_category: ActionRiskCategory
    risk_score: float  # 0.0-1.0 (probability of making things worse)
    expected_downtime_seconds: float  # Expected downtime if executed
    worst_case_downtime_seconds: float  # Worst case if action fails
    recovery_time_seconds: float  # Time to recover if action fails
    reversible: bool  # Can action be undone?
    blast_radius: str  # "single_pod", "deployment", "cluster", "datacenter"
    estimated_cost_per_minute: float  # $ cost per minute of downtime
    prerequisites: list[str]  # What must be true before executing
    side_effects: list[str]  # Known side effects


class ActionRiskRegistry:
    """
    Registry of action risk profiles.

    Defines risk characteristics for each action type.
    Used to select lowest-risk action that solves problem.
    """

    def __init__(self):
        """Initialize action risk registry."""
        self.risk_profiles: dict[ActionType, ActionRiskProfile] = {}
        self._load_risk_profiles()

    def _load_risk_profiles(self):
        """Load risk profiles for all action types."""

        # Scale up - low risk, easily reversible
        self.risk_profiles[ActionType.SCALE_UP] = ActionRiskProfile(
            action_type=ActionType.SCALE_UP,
            risk_category=ActionRiskCategory.REVERSIBLE_LOW_IMPACT,
            risk_score=0.05,  # Very low risk
            expected_downtime_seconds=0,  # No downtime
            worst_case_downtime_seconds=30,  # Brief if pods fail to start
            recovery_time_seconds=60,  # Quick rollback
            reversible=True,
            blast_radius="deployment",
            estimated_cost_per_minute=10.0,
            prerequisites=[
                "Current replicas < max replicas",
                "Cluster has capacity",
            ],
            side_effects=[
                "Increased resource usage",
                "Higher infrastructure cost",
            ],
        )

        # Scale down - medium risk, reversible but reduces capacity
        self.risk_profiles[ActionType.SCALE_DOWN] = ActionRiskProfile(
            action_type=ActionType.SCALE_DOWN,
            risk_category=ActionRiskCategory.REVERSIBLE_MEDIUM_IMPACT,
            risk_score=0.25,  # Medium risk - reduces capacity
            expected_downtime_seconds=0,
            worst_case_downtime_seconds=300,  # If scaled too aggressively
            recovery_time_seconds=120,  # Time to scale back up
            reversible=True,
            blast_radius="deployment",
            estimated_cost_per_minute=50.0,
            prerequisites=[
                "Current replicas > min replicas",
                "Load allows reduction",
            ],
            side_effects=[
                "Reduced capacity",
                "Potential queuing if load increases",
            ],
        )

        # Restart pod - medium-high risk, causes brief downtime
        self.risk_profiles[ActionType.RESTART_POD] = ActionRiskProfile(
            action_type=ActionType.RESTART_POD,
            risk_category=ActionRiskCategory.REVERSIBLE_MEDIUM_IMPACT,
            risk_score=0.35,  # Medium-high risk
            expected_downtime_seconds=10,  # Brief per-pod downtime
            worst_case_downtime_seconds=300,  # If pod fails to restart
            recovery_time_seconds=180,  # Manual intervention if needed
            reversible=False,  # Can't undo restart
            blast_radius="single_pod",
            estimated_cost_per_minute=100.0,
            prerequisites=[
                "Multiple replicas available",
                "Service has health checks",
            ],
            side_effects=[
                "Connection termination",
                "In-flight request loss",
                "Cache cold start",
            ],
        )

        # Rollback deployment - high risk, significant impact
        self.risk_profiles[ActionType.ROLLBACK_DEPLOYMENT] = ActionRiskProfile(
            action_type=ActionType.ROLLBACK_DEPLOYMENT,
            risk_category=ActionRiskCategory.IRREVERSIBLE_HIGH_IMPACT,
            risk_score=0.50,  # High risk
            expected_downtime_seconds=60,  # Rolling update downtime
            worst_case_downtime_seconds=1800,  # If rollback fails
            recovery_time_seconds=600,  # Manual intervention needed
            reversible=False,  # Can't easily undo
            blast_radius="deployment",
            estimated_cost_per_minute=500.0,
            prerequisites=[
                "Previous version available",
                "Database schema compatible",
            ],
            side_effects=[
                "Feature loss",
                "Potential data inconsistency",
                "User experience change",
            ],
        )

        # Toggle feature flag - low-medium risk, depends on flag
        self.risk_profiles[ActionType.TOGGLE_FEATURE_FLAG] = ActionRiskProfile(
            action_type=ActionType.TOGGLE_FEATURE_FLAG,
            risk_category=ActionRiskCategory.IRREVERSIBLE_LOW_IMPACT,
            risk_score=0.20,  # Low-medium risk
            expected_downtime_seconds=0,
            worst_case_downtime_seconds=60,  # If flag misconfigured
            recovery_time_seconds=30,  # Quick toggle back
            reversible=True,  # Can toggle back
            blast_radius="deployment",
            estimated_cost_per_minute=50.0,
            prerequisites=[
                "Feature flag exists",
                "Safe to disable feature",
            ],
            side_effects=[
                "Feature unavailable to users",
                "Potential UX degradation",
            ],
        )

        # Clear cache - low risk, temporary impact
        self.risk_profiles[ActionType.CLEAR_CACHE] = ActionRiskProfile(
            action_type=ActionType.CLEAR_CACHE,
            risk_category=ActionRiskCategory.REVERSIBLE_LOW_IMPACT,
            risk_score=0.10,  # Low risk
            expected_downtime_seconds=0,
            worst_case_downtime_seconds=120,  # Cache rebuild time
            recovery_time_seconds=60,  # Cache repopulates
            reversible=False,  # Can't undo but low impact
            blast_radius="deployment",
            estimated_cost_per_minute=20.0,
            prerequisites=[
                "Cache is not critical path",
                "Service can handle cache miss load",
            ],
            side_effects=[
                "Increased database load",
                "Slower response times temporarily",
            ],
        )

        # Drain node - high risk, affects multiple services
        self.risk_profiles[ActionType.DRAIN_NODE] = ActionRiskProfile(
            action_type=ActionType.DRAIN_NODE,
            risk_category=ActionRiskCategory.IRREVERSIBLE_HIGH_IMPACT,
            risk_score=0.60,  # High risk
            expected_downtime_seconds=0,  # Gradual drain
            worst_case_downtime_seconds=3600,  # If cluster capacity exceeded
            recovery_time_seconds=1800,  # Node restart + pod scheduling
            reversible=False,
            blast_radius="cluster",
            estimated_cost_per_minute=1000.0,
            prerequisites=[
                "Cluster has spare capacity",
                "Not last healthy node",
            ],
            side_effects=[
                "All pods on node restarted",
                "Multiple services affected",
                "Resource contention",
            ],
        )

    def get_risk_profile(self, action_type: ActionType) -> Optional[ActionRiskProfile]:
        """Get risk profile for an action type."""
        return self.risk_profiles.get(action_type)

    def rank_actions_by_risk(
        self,
        action_types: list[ActionType],
        service_criticality: str = "medium",
        current_downtime_seconds: float = 0,
    ) -> list[tuple[ActionType, ActionRiskProfile, float]]:
        """
        Rank actions by overall risk, considering context.

        Risk factors:
        1. Base action risk score
        2. Service criticality multiplier
        3. Current downtime (more downtime = willing to take more risk)

        Args:
            action_types: List of potential actions
            service_criticality: Service criticality level
            current_downtime_seconds: How long service has been down

        Returns:
            List of (action_type, profile, adjusted_risk_score) sorted by risk (lowest first)
        """
        # Criticality multiplier
        criticality_multipliers = {
            "low": 0.8,  # Less risk aversion
            "medium": 1.0,
            "high": 1.2,  # More risk aversion
            "critical": 1.5,  # Very risk averse
        }
        criticality_mult = criticality_multipliers.get(service_criticality, 1.0)

        # Downtime urgency factor
        # If already down for 5+ minutes, willing to take more risk
        downtime_minutes = current_downtime_seconds / 60.0
        urgency_discount = min(0.3, downtime_minutes / 20.0)  # Max 30% discount

        ranked_actions = []
        for action_type in action_types:
            profile = self.get_risk_profile(action_type)
            if profile is None:
                logger.warning(f"No risk profile for {action_type}, skipping")
                continue

            # Adjusted risk score
            adjusted_risk = (profile.risk_score * criticality_mult) - urgency_discount
            adjusted_risk = max(0.0, min(1.0, adjusted_risk))  # Clamp to [0, 1]

            ranked_actions.append((action_type, profile, adjusted_risk))

        # Sort by adjusted risk (lowest first)
        ranked_actions.sort(key=lambda x: x[2])

        return ranked_actions

    def calculate_expected_cost(
        self,
        action_type: ActionType,
        blast_radius_multiplier: float = 1.0,
    ) -> float:
        """
        Calculate expected cost of executing action.

        Expected cost = expected_downtime * cost_per_minute * blast_multiplier

        Args:
            action_type: Type of action
            blast_radius_multiplier: Multiplier based on blast radius (1.0-5.0)

        Returns:
            Expected cost in dollars
        """
        profile = self.get_risk_profile(action_type)
        if profile is None:
            return 0.0

        downtime_minutes = profile.expected_downtime_seconds / 60.0
        expected_cost = downtime_minutes * profile.estimated_cost_per_minute * blast_radius_multiplier

        return expected_cost

    def calculate_worst_case_cost(
        self,
        action_type: ActionType,
        blast_radius_multiplier: float = 1.0,
    ) -> float:
        """
        Calculate worst-case cost if action fails.

        Worst case = (worst_downtime + recovery_time) * cost_per_minute * blast_multiplier

        Args:
            action_type: Type of action
            blast_radius_multiplier: Multiplier based on blast radius

        Returns:
            Worst-case cost in dollars
        """
        profile = self.get_risk_profile(action_type)
        if profile is None:
            return 0.0

        total_downtime = profile.worst_case_downtime_seconds + profile.recovery_time_seconds
        downtime_minutes = total_downtime / 60.0
        worst_cost = downtime_minutes * profile.estimated_cost_per_minute * blast_radius_multiplier

        return worst_cost

    def select_best_action(
        self,
        candidate_actions: list[ActionType],
        service_criticality: str = "medium",
        current_downtime_seconds: float = 0,
        blast_radius_multiplier: float = 1.0,
        min_confidence: float = 0.6,
        action_confidences: Optional[dict[ActionType, float]] = None,
    ) -> Optional[tuple[ActionType, str]]:
        """
        Select the best action based on risk-reward tradeoff.

        Strategy:
        1. Rank actions by adjusted risk
        2. Filter by minimum confidence
        3. Select lowest risk action that meets confidence threshold
        4. Consider expected vs worst-case cost

        Args:
            candidate_actions: Possible actions
            service_criticality: Service criticality
            current_downtime_seconds: Current downtime
            blast_radius_multiplier: Blast radius impact multiplier
            min_confidence: Minimum confidence required
            action_confidences: Confidence for each action (if available)

        Returns:
            Tuple of (selected_action, reasoning) or None
        """
        if not candidate_actions:
            return None

        # Rank by risk
        ranked = self.rank_actions_by_risk(
            candidate_actions,
            service_criticality,
            current_downtime_seconds,
        )

        # Filter by confidence if available
        if action_confidences:
            ranked = [
                (action, profile, risk)
                for action, profile, risk in ranked
                if action_confidences.get(action, 0.0) >= min_confidence
            ]

        if not ranked:
            return None

        # Select lowest risk action
        best_action, best_profile, best_risk = ranked[0]

        # Calculate costs
        expected_cost = self.calculate_expected_cost(best_action, blast_radius_multiplier)
        worst_cost = self.calculate_worst_case_cost(best_action, blast_radius_multiplier)

        reasoning = (
            f"Selected {best_action.value} "
            f"(risk: {best_risk:.2f}, "
            f"expected cost: ${expected_cost:.2f}, "
            f"worst case: ${worst_cost:.2f})"
        )

        # Check if worst case is acceptable
        if worst_cost > 10000 and best_profile.risk_score > 0.5:
            reasoning += " - HIGH RISK, recommend human approval"

        logger.info(reasoning)

        return (best_action, reasoning)


# Global instance
_action_risk_registry: Optional[ActionRiskRegistry] = None


def get_action_risk_registry() -> ActionRiskRegistry:
    """Get global action risk registry."""
    global _action_risk_registry
    if _action_risk_registry is None:
        _action_risk_registry = ActionRiskRegistry()
    return _action_risk_registry
