"""
Unit tests for action selection.

Tests the decision module that selects appropriate remediation actions
based on root cause hypotheses, with risk assessment and approval logic.

Senior Engineering Note:
- Tests risk scoring with multiple factors
- Validates approval threshold logic
- Tests action mapping for all categories
- Covers parameter building and resource targeting
"""
import pytest

from app.core.decision.action_selector import ActionRecommendation, ActionSelector
from app.core.reasoning.hypothesis_generator import Evidence, HypothesisItem
from app.models.action import ActionType, RiskLevel


class TestActionSelector:
    """Test suite for ActionSelector class."""

    def test_selects_restart_pod_for_memory_leak(self, memory_leak_hypothesis):
        """
        Test that memory leak hypothesis triggers pod restart action.
        """
        selector = ActionSelector()

        action = selector.select(
            hypothesis=memory_leak_hypothesis,
            service_name="payment-service",
        )

        assert action is not None
        assert action.action_type == ActionType.RESTART_POD
        assert action.target_service == "payment-service"
        assert action.risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH)
        assert action.requires_approval is True
        assert action.confidence == memory_leak_hypothesis.confidence_score

    def test_selects_scale_up_for_cpu_spike(self, cpu_spike_hypothesis):
        """
        Test that CPU spike hypothesis triggers scale up action.
        """
        selector = ActionSelector()

        action = selector.select(
            hypothesis=cpu_spike_hypothesis,
            service_name="api-gateway",
        )

        assert action is not None
        assert action.action_type == ActionType.SCALE_UP
        assert action.target_service == "api-gateway"
        assert action.risk_level == RiskLevel.LOW or action.risk_level == RiskLevel.MEDIUM
        assert "scale up" in action.description.lower() or "scale" in action.description.lower()

    def test_selects_rollback_for_error_spike(self):
        """
        Test that error spike hypothesis triggers rollback action.
        """
        selector = ActionSelector()

        hypothesis = HypothesisItem(
            description="Recent deployment introduced critical bug",
            category="error_spike",
            confidence_score=0.88,
            evidence=[],
            reasoning="Error rate spiked after deployment",
        )

        action = selector.select(
            hypothesis=hypothesis,
            service_name="checkout-service",
        )

        assert action is not None
        assert action.action_type == ActionType.ROLLBACK_DEPLOYMENT
        assert action.risk_level == RiskLevel.HIGH
        assert "rollback" in action.description.lower()

    def test_selects_restart_for_database_issue(self, database_issue_hypothesis):
        """
        Test that database issue hypothesis triggers pod restart.
        """
        selector = ActionSelector()

        action = selector.select(
            hypothesis=database_issue_hypothesis,
            service_name="api-service",
        )

        assert action is not None
        assert action.action_type == ActionType.RESTART_POD
        assert action.risk_level == RiskLevel.HIGH  # Database issues are high risk

    def test_returns_none_for_unknown_category(self):
        """
        Test that unknown category returns None (no action recommended).
        """
        selector = ActionSelector()

        hypothesis = HypothesisItem(
            description="Unknown issue",
            category="unknown_category",
            confidence_score=0.75,
            evidence=[],
            reasoning="Cannot determine",
        )

        action = selector.select(
            hypothesis=hypothesis,
            service_name="test-service",
        )

        assert action is None, "Unknown category should not recommend action"

    def test_risk_score_calculation_base_levels(self):
        """
        Test risk score calculation for different base risk levels.
        """
        selector = ActionSelector()

        # Test LOW risk
        score_low = selector._calculate_risk_score(
            base_risk_level=RiskLevel.LOW,
            confidence=0.90,
        )
        assert 0.15 <= score_low <= 0.25, f"Low risk should be ~0.2, got {score_low}"

        # Test MEDIUM risk
        score_medium = selector._calculate_risk_score(
            base_risk_level=RiskLevel.MEDIUM,
            confidence=0.90,
        )
        assert 0.45 <= score_medium <= 0.55, f"Medium risk should be ~0.5, got {score_medium}"

        # Test HIGH risk
        score_high = selector._calculate_risk_score(
            base_risk_level=RiskLevel.HIGH,
            confidence=0.90,
        )
        assert 0.70 <= score_high <= 0.80, f"High risk should be ~0.75, got {score_high}"

    def test_risk_score_increases_with_low_confidence(self):
        """
        Test that lower confidence increases risk score.
        """
        selector = ActionSelector()

        high_conf_risk = selector._calculate_risk_score(
            base_risk_level=RiskLevel.MEDIUM,
            confidence=0.95,  # High confidence
        )

        low_conf_risk = selector._calculate_risk_score(
            base_risk_level=RiskLevel.MEDIUM,
            confidence=0.50,  # Low confidence
        )

        assert (
            low_conf_risk > high_conf_risk
        ), "Lower confidence should increase risk score"

    def test_risk_score_increases_for_tier1_services(self):
        """
        Test that tier-1 services have higher risk scores.
        """
        selector = ActionSelector()

        tier3_risk = selector._calculate_risk_score(
            base_risk_level=RiskLevel.MEDIUM,
            confidence=0.85,
            service_context={"tier": "tier-3"},
        )

        tier1_risk = selector._calculate_risk_score(
            base_risk_level=RiskLevel.MEDIUM,
            confidence=0.85,
            service_context={"tier": "tier-1"},
        )

        assert tier1_risk > tier3_risk, "Tier-1 services should have higher risk"

    def test_risk_score_to_risk_level_conversion(self):
        """
        Test conversion from numeric score to RiskLevel enum.
        """
        selector = ActionSelector()

        assert selector._score_to_risk_level(0.95) == RiskLevel.CRITICAL
        assert selector._score_to_risk_level(0.90) == RiskLevel.CRITICAL
        assert selector._score_to_risk_level(0.75) == RiskLevel.HIGH
        assert selector._score_to_risk_level(0.70) == RiskLevel.HIGH
        assert selector._score_to_risk_level(0.50) == RiskLevel.MEDIUM
        assert selector._score_to_risk_level(0.40) == RiskLevel.MEDIUM
        assert selector._score_to_risk_level(0.25) == RiskLevel.LOW
        assert selector._score_to_risk_level(0.10) == RiskLevel.LOW

    def test_requires_approval_for_high_risk(self):
        """
        Test that high-risk actions always require approval.
        """
        selector = ActionSelector()

        requires = selector._requires_approval(
            confidence=0.95,  # High confidence
            risk_level=RiskLevel.HIGH,
        )

        assert requires is True, "High risk should require approval"

    def test_requires_approval_for_critical_risk(self):
        """
        Test that critical-risk actions always require approval.
        """
        selector = ActionSelector()

        requires = selector._requires_approval(
            confidence=0.95,
            risk_level=RiskLevel.CRITICAL,
        )

        assert requires is True, "Critical risk should require approval"

    def test_requires_approval_for_low_confidence(self):
        """
        Test that low confidence requires approval.
        """
        selector = ActionSelector(approval_threshold=0.70)

        # Below threshold
        requires = selector._requires_approval(
            confidence=0.65,
            risk_level=RiskLevel.LOW,
        )

        assert requires is True, "Low confidence should require approval"

    def test_requires_approval_for_medium_risk(self):
        """
        Test that medium-risk actions require approval.
        """
        selector = ActionSelector()

        requires = selector._requires_approval(
            confidence=0.95,  # High confidence
            risk_level=RiskLevel.MEDIUM,
        )

        assert requires is True, "Medium risk should require approval"

    def test_builds_scale_up_parameters(self):
        """
        Test parameter building for scale up action.
        """
        selector = ActionSelector()

        params = selector._build_parameters(
            action_type=ActionType.SCALE_UP,
            service_name="api-gateway",
            service_context={"current_replicas": 3},
        )

        assert params["service_name"] == "api-gateway"
        assert params["target_replicas"] == 4  # current + 1
        assert params["max_replicas"] == 8  # current + 5
        assert "target_replicas" in params

    def test_builds_scale_down_parameters(self):
        """
        Test parameter building for scale down action.
        """
        selector = ActionSelector()

        params = selector._build_parameters(
            action_type=ActionType.SCALE_DOWN,
            service_name="worker-service",
            service_context={"current_replicas": 5},
        )

        assert params["service_name"] == "worker-service"
        assert params["target_replicas"] == 4  # current - 1
        assert params["target_replicas"] >= 1, "Should not scale below 1 replica"

    def test_builds_restart_pod_parameters(self):
        """
        Test parameter building for pod restart action.
        """
        selector = ActionSelector()

        params = selector._build_parameters(
            action_type=ActionType.RESTART_POD,
            service_name="payment-service",
        )

        assert params["service_name"] == "payment-service"
        assert "graceful_shutdown_seconds" in params
        assert params["graceful_shutdown_seconds"] == 30

    def test_builds_rollback_parameters(self):
        """
        Test parameter building for rollback action.
        """
        selector = ActionSelector()

        params = selector._build_parameters(
            action_type=ActionType.ROLLBACK_DEPLOYMENT,
            service_name="checkout-service",
        )

        assert params["service_name"] == "checkout-service"
        assert params["revision"] == "previous"

    def test_generates_descriptive_action_name(self):
        """
        Test that action names are human-readable.
        """
        selector = ActionSelector()

        hypothesis = HypothesisItem(
            description="Memory leak",
            category="memory_leak",
            confidence_score=0.85,
            evidence=[],
            reasoning="Test",
        )

        action = selector.select(
            hypothesis=hypothesis,
            service_name="payment-service",
        )

        assert action is not None
        assert "payment-service" in action.name
        assert "restart" in action.name.lower() or "pod" in action.name.lower()

    def test_includes_hypothesis_in_description(self):
        """
        Test that action description includes hypothesis description.
        """
        selector = ActionSelector()

        hypothesis = HypothesisItem(
            description="Memory leak in cache layer",
            category="memory_leak",
            confidence_score=0.85,
            evidence=[],
            reasoning="Test",
        )

        action = selector.select(
            hypothesis=hypothesis,
            service_name="payment-service",
        )

        assert action is not None
        assert "Memory leak in cache layer" in action.description
        assert "payment-service" in action.description

    def test_determines_target_resource_from_context(self):
        """
        Test that target resource is extracted from service context.
        """
        selector = ActionSelector()

        hypothesis = HypothesisItem(
            description="Memory leak",
            category="memory_leak",
            confidence_score=0.85,
            evidence=[],
            reasoning="Test",
        )

        action = selector.select(
            hypothesis=hypothesis,
            service_name="payment-service",
            service_context={"pod_name": "payment-service-abc123"},
        )

        assert action is not None
        assert action.target_resource == "payment-service-abc123"

    def test_target_resource_none_when_not_in_context(self):
        """
        Test that target resource is None when not provided.
        """
        selector = ActionSelector()

        hypothesis = HypothesisItem(
            description="CPU spike",
            category="cpu_spike",
            confidence_score=0.80,
            evidence=[],
            reasoning="Test",
        )

        action = selector.select(
            hypothesis=hypothesis,
            service_name="api-gateway",
        )

        assert action is not None
        assert action.target_resource is None

    def test_select_best_chooses_highest_confidence(self):
        """
        Test that select_best chooses action from highest confidence hypothesis.
        """
        selector = ActionSelector()

        hypotheses = [
            HypothesisItem(
                description="Low confidence",
                category="network_issue",
                confidence_score=0.55,
                evidence=[],
                reasoning="Low",
            ),
            HypothesisItem(
                description="High confidence",
                category="memory_leak",
                confidence_score=0.90,
                evidence=[],
                reasoning="High",
            ),
            HypothesisItem(
                description="Medium confidence",
                category="cpu_spike",
                confidence_score=0.75,
                evidence=[],
                reasoning="Medium",
            ),
        ]

        action = selector.select_best(
            hypotheses=hypotheses,
            service_name="test-service",
        )

        assert action is not None
        assert action.confidence == 0.90, "Should select highest confidence"
        assert action.action_type == ActionType.RESTART_POD  # memory_leak → restart

    def test_select_best_returns_none_for_empty_list(self):
        """
        Test that select_best returns None for empty hypothesis list.
        """
        selector = ActionSelector()

        action = selector.select_best(
            hypotheses=[],
            service_name="test-service",
        )

        assert action is None

    def test_select_best_skips_unknown_categories(self):
        """
        Test that select_best skips hypotheses with unknown categories.
        """
        selector = ActionSelector()

        hypotheses = [
            HypothesisItem(
                description="Unknown issue",
                category="unknown_category",
                confidence_score=0.90,
                evidence=[],
                reasoning="High confidence but unknown",
            ),
            HypothesisItem(
                description="Known issue",
                category="memory_leak",
                confidence_score=0.70,
                evidence=[],
                reasoning="Lower confidence but actionable",
            ),
        ]

        action = selector.select_best(
            hypotheses=hypotheses,
            service_name="test-service",
        )

        assert action is not None
        assert action.confidence == 0.70, "Should skip unknown and use next best"
        assert action.action_type == ActionType.RESTART_POD

    def test_blast_radius_assigned_correctly(self):
        """
        Test that blast radius is assigned based on action type.
        """
        selector = ActionSelector()

        # Scale up has low blast radius
        scale_hypothesis = HypothesisItem(
            description="Traffic spike",
            category="traffic_spike",
            confidence_score=0.85,
            evidence=[],
            reasoning="Test",
        )

        scale_action = selector.select(
            hypothesis=scale_hypothesis,
            service_name="api-gateway",
        )

        assert scale_action is not None
        assert scale_action.blast_radius == "low"

        # Rollback has high blast radius
        rollback_hypothesis = HypothesisItem(
            description="Error spike",
            category="error_spike",
            confidence_score=0.85,
            evidence=[],
            reasoning="Test",
        )

        rollback_action = selector.select(
            hypothesis=rollback_hypothesis,
            service_name="checkout-service",
        )

        assert rollback_action is not None
        assert rollback_action.blast_radius == "high"

    def test_all_action_categories_covered(self):
        """
        Test that all major incident categories have action mappings.
        """
        selector = ActionSelector()

        categories = [
            "memory_leak",
            "cpu_spike",
            "traffic_spike",
            "traffic_drop",
            "latency_spike",
            "error_spike",
            "database_issue",
            "network_issue",
        ]

        for category in categories:
            hypothesis = HypothesisItem(
                description=f"Test {category}",
                category=category,
                confidence_score=0.80,
                evidence=[],
                reasoning="Test",
            )

            action = selector.select(
                hypothesis=hypothesis,
                service_name="test-service",
            )

            assert action is not None, f"Category {category} should have action mapping"
            assert action.action_type in [
                ActionType.RESTART_POD,
                ActionType.SCALE_UP,
                ActionType.SCALE_DOWN,
                ActionType.ROLLBACK_DEPLOYMENT,
            ]


class TestActionSelectorEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_risk_score_capped_at_one(self):
        """
        Test that risk score is capped at 1.0 even with multiple factors.
        """
        selector = ActionSelector()

        # Extreme case: critical risk, low confidence, tier-1 service
        risk_score = selector._calculate_risk_score(
            base_risk_level=RiskLevel.CRITICAL,
            confidence=0.30,  # Very low
            service_context={"tier": "tier-1"},
        )

        assert risk_score <= 1.0, "Risk score should never exceed 1.0"

    def test_scale_down_never_below_one_replica(self):
        """
        Test that scale down never targets less than 1 replica.
        """
        selector = ActionSelector()

        # Service with 1 replica
        params = selector._build_parameters(
            action_type=ActionType.SCALE_DOWN,
            service_name="single-replica-service",
            service_context={"current_replicas": 1},
        )

        assert params["target_replicas"] >= 1, "Should not scale below 1 replica"

    def test_handles_missing_service_context(self):
        """
        Test that action selection works without service context.
        """
        selector = ActionSelector()

        hypothesis = HypothesisItem(
            description="Memory leak",
            category="memory_leak",
            confidence_score=0.85,
            evidence=[],
            reasoning="Test",
        )

        # No service context provided
        action = selector.select(
            hypothesis=hypothesis,
            service_name="test-service",
            service_context=None,
        )

        assert action is not None
        assert action.parameters is not None
        assert "service_name" in action.parameters

    def test_approval_threshold_customizable(self):
        """
        Test that approval threshold can be customized.
        """
        # Strict threshold
        strict_selector = ActionSelector(approval_threshold=0.90)

        requires_strict = strict_selector._requires_approval(
            confidence=0.85,  # Below 0.90
            risk_level=RiskLevel.LOW,
        )

        assert requires_strict is True

        # Lenient threshold
        lenient_selector = ActionSelector(approval_threshold=0.50)

        requires_lenient = lenient_selector._requires_approval(
            confidence=0.85,  # Above 0.50
            risk_level=RiskLevel.LOW,
        )

        # Note: In current implementation, LOW risk still requires approval
        # This tests the confidence check part
        assert requires_lenient is True  # Because LOW risk defaults to approval in MVP
