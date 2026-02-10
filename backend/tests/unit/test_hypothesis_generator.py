"""
Unit tests for hypothesis generation.

Tests the LLM-powered hypothesis generation that forms the "cognitive core" of AIRRA.

Senior Engineering Note:
- Tests LLM integration with mocked responses
- Validates prompt engineering and context inclusion
- Verifies confidence scoring and ranking
- Covers error scenarios and edge cases
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock

from app.core.perception.anomaly_detector import AnomalyDetection
from app.core.reasoning.hypothesis_generator import (
    Evidence,
    HypothesisGenerator,
    HypothesisItem,
    HypothesesResponse,
    rank_hypotheses,
)
from app.services.llm_client import LLMResponse


class TestHypothesisGenerator:
    """Test suite for Hypothesis Generator."""

    async def test_generates_hypotheses_with_single_anomaly(
        self, mock_llm_client, mock_llm_response
    ):
        """
        Test hypothesis generation with single anomaly.

        Should call LLM with properly formatted prompt and return hypotheses.
        """
        generator = HypothesisGenerator(mock_llm_client)

        anomaly = AnomalyDetection(
            metric_name="memory_usage",
            is_anomaly=True,
            confidence=0.90,
            current_value=7500000000.0,
            expected_value=2000000000.0,
            deviation_sigma=5.5,
            timestamp=datetime.utcnow(),
            context={"labels": {"service": "payment-service"}},
        )

        hypotheses_response, llm_response = await generator.generate(
            anomalies=[anomaly], service_name="payment-service"
        )

        # Verify LLM was called
        mock_llm_client.generate_structured.assert_called_once()
        call_args = mock_llm_client.generate_structured.call_args

        assert call_args.kwargs["response_model"] == HypothesesResponse
        assert call_args.kwargs["temperature"] == 0.3
        assert "memory_usage" in call_args.kwargs["prompt"]
        assert "payment-service" in call_args.kwargs["prompt"]

        # Verify response
        assert len(hypotheses_response.hypotheses) >= 1
        assert llm_response.total_tokens > 0

    async def test_generates_hypotheses_with_multiple_anomalies(
        self, mock_llm_client, mock_llm_response, memory_leak_anomalies
    ):
        """
        Test hypothesis generation with multiple correlated anomalies.

        Should include all anomalies in the prompt.
        """
        generator = HypothesisGenerator(mock_llm_client)

        hypotheses_response, llm_response = await generator.generate(
            anomalies=memory_leak_anomalies, service_name="payment-service"
        )

        # Verify LLM was called with multiple anomalies
        call_args = mock_llm_client.generate_structured.call_args
        prompt = call_args.kwargs["prompt"]

        assert "Anomaly #1" in prompt
        assert "Anomaly #2" in prompt
        assert "memory_usage_bytes" in prompt
        assert "gc_time_percent" in prompt

        assert len(hypotheses_response.hypotheses) >= 1

    async def test_includes_service_context_in_prompt(
        self, mock_llm_client, mock_llm_response, sample_service_context
    ):
        """
        Test that service context is included in prompt when provided.

        Context like dependencies and recent deployments helps LLM reasoning.
        """
        generator = HypothesisGenerator(mock_llm_client)

        anomaly = AnomalyDetection(
            metric_name="cpu_usage",
            is_anomaly=True,
            confidence=0.85,
            current_value=95.0,
            expected_value=45.0,
            deviation_sigma=5.0,
            timestamp=datetime.utcnow(),
            context={"labels": {"service": "api-gateway"}},
        )

        await generator.generate(
            anomalies=[anomaly],
            service_name="api-gateway",
            service_context=sample_service_context,
        )

        # Verify context was included in prompt
        call_args = mock_llm_client.generate_structured.call_args
        prompt = call_args.kwargs["prompt"]

        assert "Service Context" in prompt
        assert "database" in prompt  # dependency
        assert "redis" in prompt  # dependency
        assert "tier1" in prompt  # tier
        assert "platform" in prompt  # team

    async def test_normalizes_confidence_scores(self, mock_llm_client):
        """
        Test that confidence scores are validated to [0.0, 1.0] range.

        Pydantic validates confidence scores at model creation time.
        """
        # Verify that Pydantic rejects invalid confidence scores
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            HypothesisItem(
                description="Memory leak",
                category="memory_leak",
                confidence_score=1.5,  # Invalid (> 1.0)
                evidence=[],
                reasoning="Test",
            )

        assert "less_than_equal" in str(exc_info.value)

        # Verify that valid scores are accepted
        valid_hypothesis = HypothesisItem(
            description="Memory leak",
            category="memory_leak",
            confidence_score=0.95,  # Valid
            evidence=[],
            reasoning="Test",
        )
        assert valid_hypothesis.confidence_score == 0.95

    async def test_raises_error_on_empty_anomalies(self, mock_llm_client):
        """
        Test that ValueError is raised when no anomalies provided.

        Cannot generate hypotheses without anomaly data.
        """
        generator = HypothesisGenerator(mock_llm_client)

        with pytest.raises(ValueError, match="No anomalies provided"):
            await generator.generate(anomalies=[], service_name="test-service")

    async def test_tracks_token_usage(
        self, mock_llm_client, mock_llm_response
    ):
        """
        Test that token usage is tracked from LLM response.
        """
        generator = HypothesisGenerator(mock_llm_client)

        anomaly = AnomalyDetection(
            metric_name="cpu_usage",
            is_anomaly=True,
            confidence=0.85,
            current_value=95.0,
            expected_value=45.0,
            deviation_sigma=5.0,
            timestamp=datetime.utcnow(),
            context={"labels": {}},
        )

        _, llm_response = await generator.generate(
            anomalies=[anomaly], service_name="test-service"
        )

        assert llm_response.prompt_tokens > 0
        assert llm_response.completion_tokens > 0
        assert llm_response.total_tokens == (
            llm_response.prompt_tokens + llm_response.completion_tokens
        )
        assert llm_response.model is not None

    async def test_handles_llm_exception(self, mock_llm_client):
        """
        Test that LLM exceptions are propagated (not swallowed).

        Caller should handle LLM failures appropriately.
        """
        mock_llm_client.generate_structured = AsyncMock(
            side_effect=Exception("LLM API error")
        )

        generator = HypothesisGenerator(mock_llm_client)

        anomaly = AnomalyDetection(
            metric_name="cpu_usage",
            is_anomaly=True,
            confidence=0.85,
            current_value=95.0,
            expected_value=45.0,
            deviation_sigma=5.0,
            timestamp=datetime.utcnow(),
            context={"labels": {}},
        )

        with pytest.raises(Exception, match="LLM API error"):
            await generator.generate(anomalies=[anomaly], service_name="test-service")

    async def test_prompt_includes_anomaly_details(
        self, mock_llm_client, mock_llm_response
    ):
        """
        Test that prompt includes detailed anomaly information.

        Prompt should have current value, expected value, deviation, etc.
        """
        generator = HypothesisGenerator(mock_llm_client)

        anomaly = AnomalyDetection(
            metric_name="memory_usage",
            is_anomaly=True,
            confidence=0.90,
            current_value=7500000000.0,
            expected_value=2000000000.0,
            deviation_sigma=5.5,
            timestamp=datetime.utcnow(),
            context={"labels": {"env": "production", "region": "us-east-1"}},
        )

        await generator.generate(anomalies=[anomaly], service_name="payment-service")

        call_args = mock_llm_client.generate_structured.call_args
        prompt = call_args.kwargs["prompt"]

        # Check all key details are in prompt
        assert "memory_usage" in prompt
        assert "7500000000.00" in prompt or "7.5" in prompt  # Current value
        assert "2000000000.00" in prompt or "2" in prompt  # Expected value
        assert "5.5" in prompt or "5.50" in prompt  # Deviation sigma
        assert "0.90" in prompt  # Confidence
        assert "production" in prompt  # Labels
        assert "us-east-1" in prompt

    async def test_system_prompt_includes_sre_expertise(
        self, mock_llm_client, mock_llm_response
    ):
        """
        Test that system prompt defines SRE expert role.

        System prompt should set proper context for LLM reasoning.
        """
        generator = HypothesisGenerator(mock_llm_client)

        anomaly = AnomalyDetection(
            metric_name="cpu_usage",
            is_anomaly=True,
            confidence=0.85,
            current_value=95.0,
            expected_value=45.0,
            deviation_sigma=5.0,
            timestamp=datetime.utcnow(),
            context={"labels": {}},
        )

        await generator.generate(anomalies=[anomaly], service_name="test-service")

        call_args = mock_llm_client.generate_structured.call_args
        system_prompt = call_args.kwargs.get("system_prompt")

        assert system_prompt is not None
        assert "Site Reliability Engineer" in system_prompt or "SRE" in system_prompt
        assert "root cause" in system_prompt.lower()
        assert "hypothesis" in system_prompt.lower() or "hypotheses" in system_prompt.lower()

    async def test_handles_multiple_hypotheses_ranking(
        self, mock_llm_client
    ):
        """
        Test that multiple hypotheses are returned and can be ranked.
        """
        # Mock response with 3 hypotheses
        mock_response = HypothesesResponse(
            hypotheses=[
                HypothesisItem(
                    description="Memory leak in cache",
                    category="memory_leak",
                    confidence_score=0.85,
                    evidence=[],
                    reasoning="High confidence",
                ),
                HypothesisItem(
                    description="Database connection pool exhausted",
                    category="database_issue",
                    confidence_score=0.70,
                    evidence=[],
                    reasoning="Medium confidence",
                ),
                HypothesisItem(
                    description="Network congestion",
                    category="network_issue",
                    confidence_score=0.55,
                    evidence=[],
                    reasoning="Low confidence",
                ),
            ],
            overall_assessment="Multiple potential causes",
        )
        llm_meta = LLMResponse(
            content="test", prompt_tokens=500, completion_tokens=300, total_tokens=800, model="test"
        )

        mock_llm_client.generate_structured = AsyncMock(return_value=(mock_response, llm_meta))
        generator = HypothesisGenerator(mock_llm_client)

        anomaly = AnomalyDetection(
            metric_name="memory_usage",
            is_anomaly=True,
            confidence=0.90,
            current_value=7500000000.0,
            expected_value=2000000000.0,
            deviation_sigma=5.5,
            timestamp=datetime.utcnow(),
            context={"labels": {}},
        )

        hypotheses_response, _ = await generator.generate(
            anomalies=[anomaly], service_name="test-service"
        )

        assert len(hypotheses_response.hypotheses) == 3
        # Should already be sorted by LLM (most likely first)
        assert hypotheses_response.hypotheses[0].confidence_score >= hypotheses_response.hypotheses[1].confidence_score

    async def test_evidence_included_in_hypotheses(
        self, mock_llm_client, mock_llm_response
    ):
        """
        Test that hypotheses include supporting evidence.
        """
        generator = HypothesisGenerator(mock_llm_client)

        anomaly = AnomalyDetection(
            metric_name="memory_usage",
            is_anomaly=True,
            confidence=0.90,
            current_value=7500000000.0,
            expected_value=2000000000.0,
            deviation_sigma=5.5,
            timestamp=datetime.utcnow(),
            context={"labels": {}},
        )

        hypotheses_response, _ = await generator.generate(
            anomalies=[anomaly], service_name="test-service"
        )

        hypothesis = hypotheses_response.hypotheses[0]
        assert len(hypothesis.evidence) > 0, "Hypothesis should have evidence"

        evidence = hypothesis.evidence[0]
        assert evidence.signal_type in ["metric", "log", "trace"]
        assert evidence.signal_name is not None
        assert evidence.observation is not None
        assert 0.0 <= evidence.relevance <= 1.0

    async def test_chain_of_thought_reasoning_captured(
        self, mock_llm_client, mock_llm_response
    ):
        """
        Test that chain-of-thought reasoning is captured.

        Reasoning field should contain LLM's thought process.
        """
        generator = HypothesisGenerator(mock_llm_client)

        anomaly = AnomalyDetection(
            metric_name="memory_usage",
            is_anomaly=True,
            confidence=0.90,
            current_value=7500000000.0,
            expected_value=2000000000.0,
            deviation_sigma=5.5,
            timestamp=datetime.utcnow(),
            context={"labels": {}},
        )

        hypotheses_response, _ = await generator.generate(
            anomalies=[anomaly], service_name="test-service"
        )

        hypothesis = hypotheses_response.hypotheses[0]
        assert hypothesis.reasoning is not None
        assert len(hypothesis.reasoning) > 0
        # Reasoning should explain the hypothesis
        assert isinstance(hypothesis.reasoning, str)

    async def test_different_anomaly_categories(
        self, mock_llm_client, cpu_spike_anomalies
    ):
        """
        Test hypothesis generation with CPU spike anomalies.

        Should generate appropriate hypotheses for CPU issues.
        """
        # Mock response for CPU spike
        mock_response = HypothesesResponse(
            hypotheses=[
                HypothesisItem(
                    description="Infinite loop in request handler",
                    category="cpu_spike",
                    confidence_score=0.82,
                    evidence=[
                        Evidence(
                            signal_type="metric",
                            signal_name="cpu_usage",
                            observation="CPU at 98%",
                            relevance=0.95,
                        )
                    ],
                    reasoning="Sudden CPU spike suggests runaway process",
                )
            ],
            overall_assessment="CPU spike detected",
        )
        llm_meta = LLMResponse(
            content="test", prompt_tokens=400, completion_tokens=200, total_tokens=600, model="test"
        )

        mock_llm_client.generate_structured = AsyncMock(return_value=(mock_response, llm_meta))
        generator = HypothesisGenerator(mock_llm_client)

        hypotheses_response, _ = await generator.generate(
            anomalies=cpu_spike_anomalies, service_name="api-gateway"
        )

        assert hypotheses_response.hypotheses[0].category == "cpu_spike"

    async def test_temperature_parameter_used(
        self, mock_llm_client, mock_llm_response
    ):
        """
        Test that temperature=0.3 is used for focused reasoning.

        Lower temperature gives more deterministic, focused responses.
        """
        generator = HypothesisGenerator(mock_llm_client)

        anomaly = AnomalyDetection(
            metric_name="cpu_usage",
            is_anomaly=True,
            confidence=0.85,
            current_value=95.0,
            expected_value=45.0,
            deviation_sigma=5.0,
            timestamp=datetime.utcnow(),
            context={"labels": {}},
        )

        await generator.generate(anomalies=[anomaly], service_name="test-service")

        call_args = mock_llm_client.generate_structured.call_args
        assert call_args.kwargs["temperature"] == 0.3


class TestRankHypotheses:
    """Test hypothesis ranking utility function."""

    def test_ranks_by_confidence_descending(self):
        """
        Test that hypotheses are ranked by confidence (highest first).
        """
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

        ranked = rank_hypotheses(hypotheses)

        assert len(ranked) == 3
        assert ranked[0][0] == 1  # Rank 1
        assert ranked[0][1].confidence_score == 0.90  # Highest
        assert ranked[1][0] == 2  # Rank 2
        assert ranked[1][1].confidence_score == 0.75  # Medium
        assert ranked[2][0] == 3  # Rank 3
        assert ranked[2][1].confidence_score == 0.55  # Lowest

    def test_handles_empty_list(self):
        """
        Test ranking with empty list.
        """
        ranked = rank_hypotheses([])
        assert len(ranked) == 0

    def test_handles_single_hypothesis(self):
        """
        Test ranking with single hypothesis.
        """
        hypotheses = [
            HypothesisItem(
                description="Only one",
                category="memory_leak",
                confidence_score=0.85,
                evidence=[],
                reasoning="Test",
            )
        ]

        ranked = rank_hypotheses(hypotheses)

        assert len(ranked) == 1
        assert ranked[0][0] == 1  # Rank 1
        assert ranked[0][1].confidence_score == 0.85

    def test_handles_equal_confidence(self):
        """
        Test ranking with equal confidence scores.

        Order should be stable (original order preserved for equal values).
        """
        hypotheses = [
            HypothesisItem(
                description="First",
                category="memory_leak",
                confidence_score=0.80,
                evidence=[],
                reasoning="First",
            ),
            HypothesisItem(
                description="Second",
                category="cpu_spike",
                confidence_score=0.80,
                evidence=[],
                reasoning="Second",
            ),
        ]

        ranked = rank_hypotheses(hypotheses)

        assert len(ranked) == 2
        assert ranked[0][1].description == "First"
        assert ranked[1][1].description == "Second"
