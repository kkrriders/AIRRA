"""
Hypothesis generation using LLM-based reasoning.

Senior Engineering Note:
- LLM generates hypotheses, evidence, and reasoning (NOT confidence scores)
- Confidence scoring is deterministic based on evidence quality
- Evidence-based ranking
- Structured output for consistency
- LLM = reasoning assistant, NOT controller
"""
import logging
from typing import Optional

from pydantic import BaseModel, Field

from app.core.perception.anomaly_detector import AnomalyDetection
from app.services.dependency_graph import get_dependency_graph
from app.services.llm_client import LLMClient, LLMResponse

logger = logging.getLogger(__name__)


class Evidence(BaseModel):
    """Evidence supporting a hypothesis."""

    signal_type: str = Field(..., description="Type of signal (metric, log, trace)")
    signal_name: str = Field(..., description="Name of the signal")
    observation: str = Field(..., description="What was observed")
    relevance: float = Field(..., ge=0.0, le=1.0, description="Relevance score")


class HypothesisItemLLM(BaseModel):
    """LLM-generated hypothesis (without confidence score)."""

    description: str = Field(..., description="Natural language description of root cause")
    category: str = Field(
        ...,
        description="Category: memory_leak, cpu_spike, network_issue, database_issue, etc.",
    )
    evidence: list[Evidence] = Field(..., description="Supporting evidence")
    reasoning: str = Field(..., description="Chain-of-thought reasoning")


class HypothesisItem(BaseModel):
    """Single hypothesis with deterministic confidence score."""

    description: str = Field(..., description="Natural language description of root cause")
    category: str = Field(
        ...,
        description="Category: memory_leak, cpu_spike, network_issue, database_issue, etc.",
    )
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Deterministic confidence 0.0-1.0")
    evidence: list[Evidence] = Field(..., description="Supporting evidence")
    reasoning: str = Field(..., description="Chain-of-thought reasoning")


class HypothesesResponseLLM(BaseModel):
    """LLM response containing hypotheses (without confidence scores)."""

    hypotheses: list[HypothesisItemLLM] = Field(
        ...,
        description="Hypotheses with evidence and reasoning",
        min_length=1,
        max_length=5,
    )
    overall_assessment: str = Field(..., description="Summary of the incident")


class HypothesesResponse(BaseModel):
    """Final hypotheses response with deterministic confidence scores."""

    hypotheses: list[HypothesisItem] = Field(
        ...,
        description="Ranked hypotheses (most likely first)",
        min_length=1,
        max_length=5,
    )
    overall_assessment: str = Field(..., description="Summary of the incident")


def calculate_hypothesis_confidence(
    hypothesis: HypothesisItemLLM,
    anomalies: list[AnomalyDetection],
    affected_service: Optional[str] = None,
) -> float:
    """
    Calculate deterministic confidence score for a hypothesis.

    CONFIDENCE FORMULA DEFINITION:
    ===============================
    This function uses a deterministic, explainable formula to calculate confidence.
    LLM does NOT generate confidence scores - this is purely rule-based.

    Formula Components:
    1. Base Confidence (40% weight):
       - Category-specific baseline from historical incident data
       - memory_leak: 0.70, cpu_spike: 0.75, error_spike: 0.85, etc.
       - Default: 0.50 for unknown categories

    2. Evidence Quality (35% weight):
       - Average relevance: Sum(evidence.relevance) / count
       - Signal diversity bonus: +0.05 per unique signal type (max +0.15)
       - Evidence count bonus: +0.03 per evidence item (max +0.10)
       - Formula: (avg_relevance * 0.6) + diversity_bonus + count_bonus

    3. Anomaly Strength (25% weight):
       - Average anomaly confidence from perception layer
       - Deviation normalization: deviation_sigma / 6.0 (3σ = 0.5, 6σ = 1.0)
       - Formula: (avg_anomaly_confidence * 0.7) + (deviation_score * 0.3)

    Final Confidence:
       confidence = (base * 0.4) + (evidence * 0.35) + (anomaly * 0.25)
       Clamped to [0.01, 0.99] to avoid overconfidence

    Args:
        hypothesis: LLM-generated hypothesis (without confidence)
        anomalies: Original anomalies that triggered analysis

    Returns:
        Confidence score 0.0-1.0 (deterministic, explainable)
    """
    # Base confidence by category (from historical data / expert knowledge)
    category_base_confidence = {
        "memory_leak": 0.70,
        "cpu_spike": 0.75,
        "traffic_spike": 0.80,
        "latency_spike": 0.65,
        "error_spike": 0.85,
        "database_issue": 0.60,
        "network_issue": 0.55,
        "deployment_issue": 0.80,
    }

    base_confidence = category_base_confidence.get(hypothesis.category, 0.50)

    # Evidence quality score
    if not hypothesis.evidence:
        evidence_score = 0.0
    else:
        # Average relevance of evidence
        avg_relevance = sum(e.relevance for e in hypothesis.evidence) / len(hypothesis.evidence)

        # Signal diversity bonus (metric + log + trace is better than just metric)
        signal_types = {e.signal_type for e in hypothesis.evidence}
        diversity_bonus = min(0.15, len(signal_types) * 0.05)

        # Evidence count bonus (more evidence is better, but diminishing returns)
        count_bonus = min(0.10, len(hypothesis.evidence) * 0.03)

        evidence_score = (avg_relevance * 0.6) + diversity_bonus + count_bonus

    # Anomaly strength score
    if anomalies:
        avg_anomaly_confidence = sum(a.confidence for a in anomalies) / len(anomalies)
        max_deviation = max((a.deviation_sigma for a in anomalies), default=0)

        # Normalize deviation (3 sigma = 0.5, 6 sigma = 1.0)
        deviation_score = min(1.0, max_deviation / 6.0)

        anomaly_score = (avg_anomaly_confidence * 0.7) + (deviation_score * 0.3)
    else:
        anomaly_score = 0.0

    # Weighted combination
    final_confidence = (
        base_confidence * 0.4 +
        evidence_score * 0.35 +
        anomaly_score * 0.25
    )

    # Service dependency boost (if topology information available)
    dependency_boost = 0.0
    if affected_service:
        try:
            # Extract service name from hypothesis (if mentioned)
            # Check evidence for service labels
            hypothesis_service = None
            for evidence_item in hypothesis.evidence:
                if "service" in evidence_item.signal_name.lower():
                    # Try to extract service name from signal
                    hypothesis_service = affected_service  # Simplified for now
                    break

            # If we can identify the service causing the issue, apply dependency boost
            if hypothesis_service and hypothesis_service != affected_service:
                dep_graph = get_dependency_graph()
                dependency_boost = dep_graph.calculate_dependency_boost(
                    affected_service, hypothesis_service
                )
                logger.debug(
                    f"Dependency boost for {hypothesis_service} -> {affected_service}: "
                    f"{dependency_boost:+.2f}"
                )
        except Exception as e:
            logger.debug(f"Failed to calculate dependency boost: {str(e)}")

    final_confidence += dependency_boost

    # Clamp to valid range
    return min(0.99, max(0.01, final_confidence))


class HypothesisGenerator:
    """
    Generates root cause hypotheses using LLM reasoning.

    LLM Role: Generates hypotheses, evidence, and reasoning
    Deterministic: Confidence scoring based on evidence quality
    """

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    async def generate(
        self,
        anomalies: list[AnomalyDetection],
        service_name: str,
        service_context: Optional[dict] = None,
    ) -> tuple[HypothesesResponse, LLMResponse]:
        """
        Generate hypotheses from detected anomalies.

        Args:
            anomalies: Detected anomalies from perception layer
            service_name: Name of the affected service
            service_context: Optional context (topology, recent changes, etc.)

        Returns:
            Tuple of (HypothesesResponse, LLMResponse with token usage)
        """
        if not anomalies:
            raise ValueError("No anomalies provided for hypothesis generation")

        # Build context-aware prompt
        prompt = self._build_prompt(anomalies, service_name, service_context)

        # System prompt defines the role
        system_prompt = """You are an expert Site Reliability Engineer (SRE) with deep experience in incident response and root cause analysis.

Your task is to analyze metric anomalies and generate hypotheses about the root cause.

Guidelines:
- Think like an experienced SRE: consider common failure modes and patterns
- Generate 2-5 hypotheses with detailed evidence and reasoning
- DO NOT provide confidence scores (these will be calculated separately)
- Show your reasoning (chain-of-thought)
- Consider dependencies and system interactions
- Be specific and actionable
- List supporting evidence with relevance scores

Focus on generating insightful hypotheses. Confidence will be scored deterministically."""

        try:
            # Get structured response from LLM (without confidence scores)
            llm_hypotheses, llm_response = await self.llm_client.generate_structured(
                prompt=prompt,
                response_model=HypothesesResponseLLM,
                system_prompt=system_prompt,
                temperature=0.3,  # Lower temperature for more focused reasoning
            )

            # Calculate deterministic confidence for each hypothesis
            hypotheses_with_confidence = []
            for llm_hypothesis in llm_hypotheses.hypotheses:
                confidence = calculate_hypothesis_confidence(
                    llm_hypothesis,
                    anomalies,
                    affected_service=service_name,
                )

                hypothesis = HypothesisItem(
                    description=llm_hypothesis.description,
                    category=llm_hypothesis.category,
                    confidence_score=confidence,
                    evidence=llm_hypothesis.evidence,
                    reasoning=llm_hypothesis.reasoning,
                )
                hypotheses_with_confidence.append(hypothesis)

            # Sort by confidence (deterministic ranking)
            hypotheses_with_confidence.sort(key=lambda h: h.confidence_score, reverse=True)

            # Create final response
            final_response = HypothesesResponse(
                hypotheses=hypotheses_with_confidence,
                overall_assessment=llm_hypotheses.overall_assessment,
            )

            logger.info(
                f"Generated {len(final_response.hypotheses)} hypotheses with deterministic confidence "
                f"(tokens: {llm_response.total_tokens})"
            )

            return final_response, llm_response

        except Exception as e:
            logger.error(f"Hypothesis generation failed: {str(e)}")
            raise

    def _build_prompt(
        self,
        anomalies: list[AnomalyDetection],
        service_name: str,
        service_context: Optional[dict] = None,
    ) -> str:
        """
        Build the prompt for hypothesis generation.

        Senior Engineering Note:
        Prompt engineering is critical here. The prompt structure:
        1. Service context
        2. Observed anomalies with data
        3. Additional context (if available)
        4. Clear task instruction
        """
        # Format anomalies
        anomaly_descriptions = []
        for i, anomaly in enumerate(anomalies, 1):
            desc = f"""
Anomaly #{i}:
- Metric: {anomaly.metric_name}
- Current Value: {anomaly.current_value:.2f}
- Expected Value: {anomaly.expected_value:.2f}
- Deviation: {anomaly.deviation_sigma:.2f} standard deviations
- Confidence: {anomaly.confidence:.2f}
- Timestamp: {anomaly.timestamp.isoformat()}
- Labels: {anomaly.context.get('labels', {})}
"""
            anomaly_descriptions.append(desc.strip())

        # Build full prompt
        prompt_parts = [
            f"## Incident Analysis Request",
            f"",
            f"**Service:** {service_name}",
            f"",
            f"## Detected Anomalies",
            "",
        ]
        prompt_parts.extend(anomaly_descriptions)

        # Add service context if available
        if service_context:
            prompt_parts.extend(
                [
                    "",
                    "## Service Context",
                    "",
                ]
            )
            if "dependencies" in service_context:
                deps = ", ".join(service_context["dependencies"])
                prompt_parts.append(f"**Dependencies:** {deps}")
            if "recent_deployments" in service_context:
                prompt_parts.append(
                    f"**Recent Deployments:** {service_context['recent_deployments']}"
                )
            if "tier" in service_context:
                prompt_parts.append(f"**Service Tier:** {service_context['tier']}")

        # Add task instruction
        prompt_parts.extend(
            [
                "",
                "## Task",
                "",
                "Based on the anomalies above, generate 2-5 hypotheses for the root cause.",
                "",
                "For each hypothesis:",
                "1. Provide a clear description of what you think is happening",
                "2. Categorize the issue (memory_leak, cpu_spike, network_issue, etc.)",
                "3. List the supporting evidence from the anomalies with relevance scores (0.0-1.0)",
                "4. Explain your reasoning (chain-of-thought)",
                "",
                "Note: Confidence scores will be calculated deterministically based on your evidence.",
                "Focus on providing high-quality evidence and reasoning.",
            ]
        )

        return "\n".join(prompt_parts)


def rank_hypotheses(hypotheses: list[HypothesisItem]) -> list[tuple[int, HypothesisItem]]:
    """
    Rank hypotheses and assign rank numbers.

    Returns list of (rank, hypothesis) tuples sorted by confidence.
    """
    sorted_hypotheses = sorted(
        hypotheses,
        key=lambda h: h.confidence_score,
        reverse=True,
    )

    return [(i + 1, h) for i, h in enumerate(sorted_hypotheses)]
