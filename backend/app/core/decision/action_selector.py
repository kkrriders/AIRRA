"""
Action selection and recommendation based on hypotheses.

Senior Engineering Note:
- Rule-based action selection (can be extended with LLM-based selection)
- Risk assessment for each action
- Approval requirement determination
- Runbook mapping
"""
import logging
from dataclasses import dataclass
from typing import Optional

from app.core.reasoning.hypothesis_generator import HypothesisItem
from app.models.action import ActionType, RiskLevel

logger = logging.getLogger(__name__)


@dataclass
class ActionRecommendation:
    """Recommended action for an incident."""

    action_type: ActionType
    name: str
    description: str
    target_service: str
    target_resource: Optional[str]
    risk_level: RiskLevel
    risk_score: float  # 0.0 to 1.0
    blast_radius: str  # "low", "medium", "high", "critical"
    requires_approval: bool
    parameters: dict
    reasoning: str
    confidence: float  # Inherited from hypothesis


class ActionSelector:
    """
    Selects appropriate remediation actions based on hypotheses.

    Senior Engineering Note:
    This uses a rule-based approach for MVP. For production, consider:
    - LLM-based action selection with reasoning
    - Runbook integration
    - Historical success rate analysis
    - Multi-action plan generation
    """

    def __init__(self, approval_threshold: float = 0.7):
        """
        Initialize action selector.

        Args:
            approval_threshold: Confidence threshold below which approval is required
        """
        self.approval_threshold = approval_threshold

        # Action mapping rules
        # Format: {category: (action_type, risk_level, blast_radius)}
        self.action_rules = {
            "memory_leak": (ActionType.RESTART_POD, RiskLevel.MEDIUM, "medium"),
            "cpu_spike": (ActionType.SCALE_UP, RiskLevel.LOW, "low"),
            "traffic_spike": (ActionType.SCALE_UP, RiskLevel.LOW, "low"),
            "traffic_drop": (ActionType.SCALE_DOWN, RiskLevel.LOW, "low"),
            "latency_spike": (ActionType.RESTART_POD, RiskLevel.MEDIUM, "medium"),
            "error_spike": (ActionType.ROLLBACK_DEPLOYMENT, RiskLevel.HIGH, "high"),
            "database_issue": (ActionType.RESTART_POD, RiskLevel.HIGH, "high"),
            "network_issue": (ActionType.RESTART_POD, RiskLevel.HIGH, "high"),
        }

    def select(
        self,
        hypothesis: HypothesisItem,
        service_name: str,
        service_context: Optional[dict] = None,
    ) -> Optional[ActionRecommendation]:
        """
        Select appropriate action for a hypothesis.

        Args:
            hypothesis: The hypothesis to create action for
            service_name: Name of the affected service
            service_context: Optional service context

        Returns:
            ActionRecommendation or None if no action recommended
        """
        # Get action from rule mapping
        if hypothesis.category not in self.action_rules:
            logger.warning(f"No action rule for category: {hypothesis.category}")
            return None

        action_type, base_risk_level, blast_radius = self.action_rules[hypothesis.category]

        # Calculate risk score based on multiple factors
        risk_score = self._calculate_risk_score(
            base_risk_level=base_risk_level,
            confidence=hypothesis.confidence_score,
            service_context=service_context,
        )

        # Determine final risk level based on calculated score
        risk_level = self._score_to_risk_level(risk_score)

        # Determine if approval is required
        requires_approval = self._requires_approval(
            confidence=hypothesis.confidence_score,
            risk_level=risk_level,
        )

        # Build action parameters
        parameters = self._build_parameters(
            action_type=action_type,
            service_name=service_name,
            service_context=service_context,
        )

        # Generate action description
        description = self._generate_description(
            action_type=action_type,
            hypothesis=hypothesis,
            service_name=service_name,
        )

        # Determine target resource (pod name, deployment, etc.)
        target_resource = self._determine_target_resource(
            action_type=action_type,
            service_name=service_name,
            service_context=service_context,
        )

        return ActionRecommendation(
            action_type=action_type,
            name=f"{action_type.value.replace('_', ' ').title()} - {service_name}",
            description=description,
            target_service=service_name,
            target_resource=target_resource,
            risk_level=risk_level,
            risk_score=risk_score,
            blast_radius=blast_radius,
            requires_approval=requires_approval,
            parameters=parameters,
            reasoning=hypothesis.reasoning,
            confidence=hypothesis.confidence_score,
        )

    def select_best(
        self,
        hypotheses: list[HypothesisItem],
        service_name: str,
        service_context: Optional[dict] = None,
    ) -> Optional[ActionRecommendation]:
        """
        Select the best action from multiple hypotheses.

        Uses the highest confidence hypothesis.
        """
        if not hypotheses:
            return None

        # Sort by confidence
        sorted_hypotheses = sorted(
            hypotheses,
            key=lambda h: h.confidence_score,
            reverse=True,
        )

        # Try to select action for top hypothesis
        for hypothesis in sorted_hypotheses:
            action = self.select(hypothesis, service_name, service_context)
            if action:
                return action

        return None

    def _calculate_risk_score(
        self,
        base_risk_level: RiskLevel,
        confidence: float,
        service_context: Optional[dict] = None,
    ) -> float:
        """
        Calculate numeric risk score (0.0 to 1.0).

        Factors considered:
        - Base risk level of action type
        - Confidence in the hypothesis (lower confidence = higher risk)
        - Service tier (higher tier = higher risk)
        """
        # Base risk mapping
        base_risk_map = {
            RiskLevel.LOW: 0.2,
            RiskLevel.MEDIUM: 0.5,
            RiskLevel.HIGH: 0.75,
            RiskLevel.CRITICAL: 0.95,
        }

        base_risk = base_risk_map[base_risk_level]

        # Adjust for confidence (low confidence increases risk)
        # Formula: add risk when confidence is low, subtract when high
        confidence_adjustment = (1.0 - confidence) * 0.1  # Up to 10% adjustment

        # Adjust for service tier if available
        tier_adjustment = 0.0
        if service_context and "tier" in service_context:
            tier = service_context["tier"]
            if tier == "tier-1" or tier == "tier1":
                tier_adjustment = 0.15
            elif tier == "tier-2" or tier == "tier2":
                tier_adjustment = 0.05

        # Calculate final risk (additive adjustments)
        risk_score = min(1.0, max(0.0, base_risk + confidence_adjustment + tier_adjustment))

        return risk_score

    def _score_to_risk_level(self, score: float) -> RiskLevel:
        """Convert numeric risk score to RiskLevel enum."""
        if score >= 0.9:
            return RiskLevel.CRITICAL
        elif score >= 0.7:
            return RiskLevel.HIGH
        elif score >= 0.4:
            return RiskLevel.MEDIUM
        else:
            return RiskLevel.LOW

    def _requires_approval(self, confidence: float, risk_level: RiskLevel) -> bool:
        """Determine if human approval is required."""
        # Always require approval for high-risk actions
        if risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            return True

        # Require approval if confidence is below threshold
        if confidence < self.approval_threshold:
            return True

        # Medium risk requires approval
        if risk_level == RiskLevel.MEDIUM:
            return True

        # Low risk with high confidence can auto-execute (in theory)
        # But for safety, we default to requiring approval in MVP
        return True

    def _build_parameters(
        self,
        action_type: ActionType,
        service_name: str,
        service_context: Optional[dict] = None,
    ) -> dict:
        """Build action-specific parameters."""
        params = {
            "service_name": service_name,
        }

        if action_type == ActionType.SCALE_UP:
            current_replicas = service_context.get("current_replicas", 1) if service_context else 1
            params["target_replicas"] = current_replicas + 1
            params["max_replicas"] = current_replicas + 5

        elif action_type == ActionType.SCALE_DOWN:
            current_replicas = service_context.get("current_replicas", 2) if service_context else 2
            params["target_replicas"] = max(1, current_replicas - 1)

        elif action_type == ActionType.RESTART_POD:
            params["graceful_shutdown_seconds"] = 30

        elif action_type == ActionType.ROLLBACK_DEPLOYMENT:
            params["revision"] = "previous"

        return params

    def _generate_description(
        self,
        action_type: ActionType,
        hypothesis: HypothesisItem,
        service_name: str,
    ) -> str:
        """Generate human-readable action description."""
        descriptions = {
            ActionType.RESTART_POD: f"Restart pods for {service_name} to clear potential memory leaks or stale state",
            ActionType.SCALE_UP: f"Scale up {service_name} to handle increased load or compensate for degraded instances",
            ActionType.SCALE_DOWN: f"Scale down {service_name} to optimize resource usage",
            ActionType.ROLLBACK_DEPLOYMENT: f"Rollback {service_name} to previous deployment due to suspected regression",
        }

        base_description = descriptions.get(
            action_type,
            f"Execute {action_type.value} on {service_name}",
        )

        return f"{base_description}. Root cause hypothesis: {hypothesis.description}"

    def _determine_target_resource(
        self,
        action_type: ActionType,
        service_name: str,
        service_context: Optional[dict] = None,
    ) -> Optional[str]:
        """Determine specific resource to target."""
        # In a real implementation, this would query Kubernetes API
        # For MVP, we use service context or return None
        if service_context and "pod_name" in service_context:
            return service_context["pod_name"]

        return None
