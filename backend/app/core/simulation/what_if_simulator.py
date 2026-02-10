"""
What-if simulation for comparing remediation actions.

Senior Engineering Note:
- Before executing high-risk actions, simulate outcomes
- Compare multiple candidate actions side-by-side
- Show predicted metrics, risks, costs
- This is optional but highly valuable for operators
- Helps build confidence before execution
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.core.decision.blast_radius import BlastRadiusAssessment, BlastRadiusCalculator
from app.core.decision.risk_weighted_actions import (
    ActionRiskProfile,
    ActionRiskRegistry,
    get_action_risk_registry,
)
from app.core.execution.verification import HealthMetrics
from app.models.action import ActionType

logger = logging.getLogger(__name__)


@dataclass
class SimulatedOutcome:
    """Simulated outcome for an action."""

    action_type: ActionType
    action_description: str
    risk_profile: ActionRiskProfile

    # Predicted metrics
    predicted_success_probability: float  # Based on historical success rate
    predicted_improvement_percentage: float  # Expected improvement in metrics
    predicted_recovery_time_seconds: float  # Time to full recovery

    # Risk assessment
    expected_downtime_seconds: float
    worst_case_downtime_seconds: float
    expected_cost_dollars: float
    worst_case_cost_dollars: float

    # Side effects
    blast_radius_impact: str
    potential_side_effects: list[str]
    prerequisites_met: bool
    prerequisites_missing: list[str]

    # Recommendation
    recommended: bool
    recommendation_reasoning: str


@dataclass
class SimulationComparison:
    """Comparison of multiple simulated actions."""

    service_name: str
    incident_category: str
    blast_radius: BlastRadiusAssessment
    current_metrics: HealthMetrics

    simulated_outcomes: list[SimulatedOutcome]
    best_action: Optional[ActionType]
    best_action_reasoning: str

    simulation_timestamp: datetime
    simulation_id: str


class WhatIfSimulator:
    """
    Simulate multiple remediation actions and compare outcomes.

    This helps operators make informed decisions before executing.
    Shows side-by-side comparison of risks, costs, and predicted outcomes.
    """

    def __init__(
        self,
        action_risk_registry: Optional[ActionRiskRegistry] = None,
        blast_calculator: Optional[BlastRadiusCalculator] = None,
    ):
        """
        Initialize what-if simulator.

        Args:
            action_risk_registry: Registry of action risk profiles
            blast_calculator: Blast radius calculator
        """
        self.action_risk_registry = action_risk_registry or get_action_risk_registry()
        self.blast_calculator = blast_calculator

        # Historical success rates (would be loaded from confidence tracker)
        # For now, using conservative estimates
        self.historical_success_rates = {
            ActionType.SCALE_UP: 0.85,
            ActionType.SCALE_DOWN: 0.75,
            ActionType.RESTART_POD: 0.70,
            ActionType.ROLLBACK_DEPLOYMENT: 0.80,
            ActionType.CLEAR_CACHE: 0.65,
            ActionType.TOGGLE_FEATURE_FLAG: 0.75,
            ActionType.DRAIN_NODE: 0.60,
        }

    async def simulate_actions(
        self,
        service_name: str,
        incident_category: str,
        candidate_actions: list[ActionType],
        current_metrics: HealthMetrics,
        blast_radius: Optional[BlastRadiusAssessment] = None,
        service_criticality: str = "medium",
        current_downtime_seconds: float = 0,
    ) -> SimulationComparison:
        """
        Simulate multiple actions and compare outcomes.

        Args:
            service_name: Service being remediated
            incident_category: Type of incident
            candidate_actions: Actions to simulate
            current_metrics: Current health metrics
            blast_radius: Blast radius assessment (optional)
            service_criticality: Service criticality level
            current_downtime_seconds: Current downtime duration

        Returns:
            SimulationComparison with side-by-side outcomes
        """
        logger.info(
            f"Simulating {len(candidate_actions)} actions for {service_name} "
            f"({incident_category})"
        )

        # Calculate blast radius if not provided
        if blast_radius is None and self.blast_calculator:
            blast_radius = await self.blast_calculator.calculate_blast_radius(
                service_name
            )

        # Simulate each action
        simulated_outcomes: list[SimulatedOutcome] = []

        for action_type in candidate_actions:
            outcome = await self._simulate_single_action(
                action_type=action_type,
                service_name=service_name,
                incident_category=incident_category,
                current_metrics=current_metrics,
                blast_radius=blast_radius,
                service_criticality=service_criticality,
                current_downtime_seconds=current_downtime_seconds,
            )
            simulated_outcomes.append(outcome)

        # Sort by recommendation score
        simulated_outcomes.sort(
            key=lambda x: (
                x.recommended,
                x.predicted_success_probability,
                -x.expected_cost_dollars,
            ),
            reverse=True,
        )

        # Select best action
        best_action = None
        best_reasoning = "No suitable action found"

        if simulated_outcomes and simulated_outcomes[0].recommended:
            best_action = simulated_outcomes[0].action_type
            best_reasoning = simulated_outcomes[0].recommendation_reasoning

        simulation_id = f"sim-{service_name}-{datetime.utcnow().timestamp()}"

        comparison = SimulationComparison(
            service_name=service_name,
            incident_category=incident_category,
            blast_radius=blast_radius or BlastRadiusAssessment(
                level="unknown",
                score=0.0,
                affected_services_count=0,
                downstream_services=[],
                request_volume_per_second=0.0,
                error_propagation_percentage=0.0,
                estimated_users_impacted=0,
                revenue_impact_per_hour=0.0,
                urgency_multiplier=1.0,
                assessment_timestamp=datetime.utcnow(),
                details={},
            ),
            current_metrics=current_metrics,
            simulated_outcomes=simulated_outcomes,
            best_action=best_action,
            best_action_reasoning=best_reasoning,
            simulation_timestamp=datetime.utcnow(),
            simulation_id=simulation_id,
        )

        logger.info(
            f"Simulation complete: Best action = {best_action.value if best_action else 'None'}"
        )

        return comparison

    async def _simulate_single_action(
        self,
        action_type: ActionType,
        service_name: str,
        incident_category: str,
        current_metrics: HealthMetrics,
        blast_radius: Optional[BlastRadiusAssessment],
        service_criticality: str,
        current_downtime_seconds: float,
    ) -> SimulatedOutcome:
        """
        Simulate a single action and predict outcome.

        Args:
            action_type: Action to simulate
            service_name: Service name
            incident_category: Incident category
            current_metrics: Current metrics
            blast_radius: Blast radius assessment
            service_criticality: Service criticality
            current_downtime_seconds: Current downtime

        Returns:
            SimulatedOutcome with predictions
        """
        # Get risk profile
        risk_profile = self.action_risk_registry.get_risk_profile(action_type)

        if risk_profile is None:
            logger.warning(f"No risk profile for {action_type}")
            return SimulatedOutcome(
                action_type=action_type,
                action_description=f"Unknown action: {action_type.value}",
                risk_profile=None,
                predicted_success_probability=0.0,
                predicted_improvement_percentage=0.0,
                predicted_recovery_time_seconds=0.0,
                expected_downtime_seconds=0.0,
                worst_case_downtime_seconds=0.0,
                expected_cost_dollars=0.0,
                worst_case_cost_dollars=0.0,
                blast_radius_impact="unknown",
                potential_side_effects=[],
                prerequisites_met=False,
                prerequisites_missing=["Risk profile not found"],
                recommended=False,
                recommendation_reasoning="Action risk profile not found",
            )

        # Get historical success rate
        success_probability = self.historical_success_rates.get(action_type, 0.50)

        # Predict improvement (category-specific heuristics)
        predicted_improvement = self._predict_improvement(
            action_type, incident_category, success_probability
        )

        # Estimate recovery time
        predicted_recovery_time = risk_profile.expected_downtime_seconds

        # Calculate costs
        blast_multiplier = (
            blast_radius.urgency_multiplier if blast_radius else 1.0
        )
        expected_cost = self.action_risk_registry.calculate_expected_cost(
            action_type, blast_multiplier
        )
        worst_cost = self.action_risk_registry.calculate_worst_case_cost(
            action_type, blast_multiplier
        )

        # Check prerequisites (simplified - would need actual checks)
        prerequisites_met = True
        prerequisites_missing = []

        # Example prerequisite check
        if action_type == ActionType.SCALE_DOWN:
            # Would check actual replica count
            prerequisites_missing.append("Check: Current replicas > min replicas")
            prerequisites_met = False

        # Determine if recommended
        recommended = self._should_recommend(
            action_type=action_type,
            risk_profile=risk_profile,
            success_probability=success_probability,
            expected_cost=expected_cost,
            worst_cost=worst_cost,
            prerequisites_met=prerequisites_met,
            service_criticality=service_criticality,
        )

        # Generate reasoning
        reasoning = self._generate_recommendation_reasoning(
            action_type=action_type,
            risk_profile=risk_profile,
            success_probability=success_probability,
            expected_cost=expected_cost,
            recommended=recommended,
            prerequisites_met=prerequisites_met,
        )

        return SimulatedOutcome(
            action_type=action_type,
            action_description=risk_profile.action_type.value.replace("_", " ").title(),
            risk_profile=risk_profile,
            predicted_success_probability=success_probability,
            predicted_improvement_percentage=predicted_improvement,
            predicted_recovery_time_seconds=predicted_recovery_time,
            expected_downtime_seconds=risk_profile.expected_downtime_seconds,
            worst_case_downtime_seconds=risk_profile.worst_case_downtime_seconds,
            expected_cost_dollars=expected_cost,
            worst_case_cost_dollars=worst_cost,
            blast_radius_impact=risk_profile.blast_radius,
            potential_side_effects=risk_profile.side_effects,
            prerequisites_met=prerequisites_met,
            prerequisites_missing=prerequisites_missing,
            recommended=recommended,
            recommendation_reasoning=reasoning,
        )

    def _predict_improvement(
        self,
        action_type: ActionType,
        incident_category: str,
        success_probability: float,
    ) -> float:
        """
        Predict expected improvement percentage.

        Based on historical data and category-action matching.

        Args:
            action_type: Type of action
            incident_category: Incident category
            success_probability: Historical success rate

        Returns:
            Predicted improvement percentage (0-100)
        """
        # Category-action effectiveness matrix (would be learned from data)
        effectiveness_matrix = {
            ("memory_leak", ActionType.RESTART_POD): 0.70,
            ("memory_leak", ActionType.SCALE_UP): 0.30,
            ("cpu_spike", ActionType.SCALE_UP): 0.80,
            ("cpu_spike", ActionType.RESTART_POD): 0.40,
            ("error_spike", ActionType.ROLLBACK_DEPLOYMENT): 0.85,
            ("error_spike", ActionType.RESTART_POD): 0.50,
            ("database_issue", ActionType.RESTART_POD): 0.60,
            ("cache_issue", ActionType.CLEAR_CACHE): 0.75,
        }

        effectiveness = effectiveness_matrix.get(
            (incident_category, action_type), 0.50
        )

        # Combine with success probability
        predicted_improvement = effectiveness * success_probability * 100

        return predicted_improvement

    def _should_recommend(
        self,
        action_type: ActionType,
        risk_profile: ActionRiskProfile,
        success_probability: float,
        expected_cost: float,
        worst_cost: float,
        prerequisites_met: bool,
        service_criticality: str,
    ) -> bool:
        """
        Determine if action should be recommended.

        Args:
            action_type: Action type
            risk_profile: Risk profile
            success_probability: Success probability
            expected_cost: Expected cost
            worst_cost: Worst case cost
            prerequisites_met: Prerequisites satisfied
            service_criticality: Service criticality

        Returns:
            True if recommended
        """
        # Must meet prerequisites
        if not prerequisites_met:
            return False

        # Must have reasonable success probability
        if success_probability < 0.50:
            return False

        # Risk-reward tradeoff
        if risk_profile.risk_score > 0.7 and success_probability < 0.80:
            return False

        # Cost consideration
        if worst_cost > 5000 and service_criticality != "critical":
            return False

        return True

    def _generate_recommendation_reasoning(
        self,
        action_type: ActionType,
        risk_profile: ActionRiskProfile,
        success_probability: float,
        expected_cost: float,
        recommended: bool,
        prerequisites_met: bool,
    ) -> str:
        """
        Generate human-readable reasoning for recommendation.

        Args:
            action_type: Action type
            risk_profile: Risk profile
            success_probability: Success probability
            expected_cost: Expected cost
            recommended: Whether recommended
            prerequisites_met: Prerequisites met

        Returns:
            Reasoning string
        """
        if not prerequisites_met:
            return (
                f"Not recommended: Prerequisites not met. "
                f"Check: {', '.join(risk_profile.prerequisites)}"
            )

        if not recommended:
            if success_probability < 0.50:
                return f"Not recommended: Low success probability ({success_probability:.0%})"
            if risk_profile.risk_score > 0.7:
                return f"Not recommended: High risk ({risk_profile.risk_score:.2f})"
            return "Not recommended: Risk-reward tradeoff unfavorable"

        # Build positive reasoning
        reasoning_parts = [
            f"Success probability: {success_probability:.0%}",
            f"Risk: {risk_profile.risk_score:.2f}",
            f"Expected cost: ${expected_cost:.2f}",
        ]

        if risk_profile.reversible:
            reasoning_parts.append("Reversible")

        if risk_profile.expected_downtime_seconds == 0:
            reasoning_parts.append("No expected downtime")

        return "Recommended: " + ", ".join(reasoning_parts)

    def generate_comparison_report(self, comparison: SimulationComparison) -> str:
        """
        Generate human-readable comparison report.

        Args:
            comparison: Simulation comparison

        Returns:
            Formatted report string
        """
        lines = []
        lines.append("=" * 70)
        lines.append("WHAT-IF SIMULATION: ACTION COMPARISON")
        lines.append("=" * 70)

        lines.append(f"\nService: {comparison.service_name}")
        lines.append(f"Incident: {comparison.incident_category}")

        if comparison.blast_radius:
            lines.append(
                f"Blast Radius: {comparison.blast_radius.level.upper()} "
                f"({comparison.blast_radius.affected_services_count} services, "
                f"{comparison.blast_radius.estimated_users_impacted} users)"
            )

        lines.append("\n" + "-" * 70)
        lines.append("SIMULATED ACTIONS:")
        lines.append("-" * 70)

        for idx, outcome in enumerate(comparison.simulated_outcomes, 1):
            lines.append(f"\n{idx}. {outcome.action_description.upper()}")
            lines.append(f"   Status: {'✓ RECOMMENDED' if outcome.recommended else '✗ Not Recommended'}")
            lines.append(
                f"   Success Probability: {outcome.predicted_success_probability:.0%}"
            )
            lines.append(
                f"   Expected Improvement: {outcome.predicted_improvement_percentage:.1f}%"
            )
            lines.append(
                f"   Expected Downtime: {outcome.expected_downtime_seconds:.0f}s "
                f"(worst: {outcome.worst_case_downtime_seconds:.0f}s)"
            )
            lines.append(
                f"   Expected Cost: ${outcome.expected_cost_dollars:.2f} "
                f"(worst: ${outcome.worst_case_cost_dollars:.2f})"
            )
            lines.append(f"   Risk Score: {outcome.risk_profile.risk_score:.2f}")
            lines.append(f"   Blast Radius: {outcome.blast_radius_impact}")

            if outcome.potential_side_effects:
                lines.append(f"   Side Effects:")
                for effect in outcome.potential_side_effects[:3]:
                    lines.append(f"     - {effect}")

            if not outcome.prerequisites_met:
                lines.append(f"   ⚠ Prerequisites Missing:")
                for prereq in outcome.prerequisites_missing:
                    lines.append(f"     - {prereq}")

            lines.append(f"   Reasoning: {outcome.recommendation_reasoning}")

        lines.append("\n" + "=" * 70)
        if comparison.best_action:
            lines.append(f"BEST ACTION: {comparison.best_action.value.upper()}")
            lines.append(f"Reasoning: {comparison.best_action_reasoning}")
        else:
            lines.append("NO RECOMMENDED ACTION")
            lines.append(f"Reasoning: {comparison.best_action_reasoning}")

        lines.append("=" * 70)

        return "\n".join(lines)


# Global instance
_what_if_simulator: Optional[WhatIfSimulator] = None


def get_what_if_simulator() -> WhatIfSimulator:
    """Get global what-if simulator instance."""
    global _what_if_simulator
    if _what_if_simulator is None:
        _what_if_simulator = WhatIfSimulator()
    return _what_if_simulator
