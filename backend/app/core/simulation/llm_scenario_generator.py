"""
LLM-Powered Scenario Generator.

Uses LLM to dynamically generate incident scenarios from natural language prompts.
This allows creating unlimited variations of incidents for realistic demo timelines.
"""
import logging
from typing import Dict, List
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.core.simulation.scenario_definitions import (
    IncidentScenario,
    MetricPattern,
    MetricPatternType,
    ScenarioTag,
    ScenarioDifficulty,
)
from app.services.llm_client import LLMClient, get_llm_client

logger = logging.getLogger(__name__)


class GeneratedMetric(BaseModel):
    """LLM-generated metric definition."""

    metric_name: str = Field(description="Technical metric name (e.g., memory_usage_bytes)")
    value: float = Field(description="Current anomalous value")
    baseline: float = Field(description="Expected baseline value")
    deviation_sigma: float = Field(description="Standard deviation from baseline (3+ for anomaly)")
    unit: str = Field(default="", description="Unit of measurement")


class GeneratedScenario(BaseModel):
    """LLM-generated incident scenario."""

    name: str = Field(description="Short name for the incident")
    description: str = Field(description="Detailed description of what went wrong")
    root_cause: str = Field(description="Technical root cause category")
    severity: str = Field(description="Severity level: low, medium, high, or critical")
    metrics: List[GeneratedMetric] = Field(description="List of anomalous metrics")
    context: Dict = Field(default_factory=dict, description="Additional context like deployments")
    expected_action_types: List[str] = Field(
        default_factory=list,
        description="Expected remediation action types"
    )


class LLMScenarioGenerator:
    """
    Generates incident scenarios using LLM from natural language prompts.

    Example usage:
        generator = LLMScenarioGenerator()
        scenario = await generator.generate(
            prompt="Generate a Redis cache failure incident with cascading failures",
            service_name="payment-service",
            severity="high"
        )
    """

    def __init__(self, llm_client: LLMClient = None):
        """
        Initialize the generator.

        Args:
            llm_client: LLM client instance (uses default if not provided)
        """
        self.llm_client = llm_client or get_llm_client()

    async def generate(
        self,
        prompt: str,
        service_name: str = "payment-service",
        severity: str = "medium",
    ) -> IncidentScenario:
        """
        Generate an incident scenario from a natural language prompt.

        Args:
            prompt: Natural language description of the incident
            service_name: Name of affected service
            severity: Expected severity level

        Returns:
            IncidentScenario ready to be run

        Example:
            scenario = await generator.generate(
                prompt="Create a database connection pool exhaustion incident",
                service_name="payment-service",
                severity="high"
            )
        """
        logger.info(f"Generating scenario from prompt: {prompt}")

        # Build LLM prompt
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(prompt, service_name, severity)

        try:
            # Call LLM with structured output
            generated, llm_response = await self.llm_client.generate_structured(
                prompt=user_prompt,
                response_model=GeneratedScenario,
                system_prompt=system_prompt,
            )

            logger.info(
                f"Generated scenario: {generated.name} "
                f"({len(generated.metrics)} metrics, "
                f"tokens: {llm_response.total_tokens})"
            )

            # Convert to IncidentScenario
            scenario = self._convert_to_scenario(
                generated=generated,
                service_name=service_name,
                prompt=prompt,
            )

            return scenario

        except Exception as e:
            logger.error(f"Failed to generate scenario: {str(e)}", exc_info=True)
            raise

    def _build_system_prompt(self) -> str:
        """Build the system prompt for scenario generation."""
        return """You are an expert SRE (Site Reliability Engineer) and incident response specialist.

Your task is to generate realistic incident scenarios for a microservices payment platform.

When generating scenarios:
1. Create believable technical incidents with specific metrics
2. Use realistic metric values and deviations (3-8 sigma for anomalies)
3. Include proper technical context (deployments, dependencies, etc.)
4. Suggest appropriate remediation actions
5. Make scenarios educational and demonstrative

Focus on common production incidents:
- Resource exhaustion (memory, CPU, disk)
- Performance degradation (latency, throughput)
- Dependency failures (databases, external APIs)
- Configuration issues (bad deployments, misconfigurations)
- Network problems (timeouts, packet loss, DNS)
- Security incidents (auth failures, suspicious patterns)

Output metrics should follow naming conventions:
- memory_usage_bytes, memory_usage_percent
- cpu_usage_percent, cpu_throttling_seconds_total
- http_request_duration_seconds_p95, http_request_duration_seconds_p99
- http_requests_total, http_response_status_500_total
- database_query_duration_seconds, database_connections_active
- disk_usage_percent, disk_io_wait_percent
- network_errors_total, dns_lookup_duration_seconds
"""

    def _build_user_prompt(
        self,
        prompt: str,
        service_name: str,
        severity: str,
    ) -> str:
        """Build the user prompt with specific requirements."""
        return f"""Generate an incident scenario with the following requirements:

**Incident Description**: {prompt}

**Service**: {service_name}
**Target Severity**: {severity}

Please generate:
1. A short, descriptive name for the incident
2. Detailed technical description of what's happening
3. Root cause category (e.g., memory_leak, capacity_issue, dependency_failure)
4. 3-6 anomalous metrics with realistic values:
   - Each metric should have: name, current value, baseline, deviation (sigma), unit
   - Deviation should be 3+ sigma to be considered anomalous
   - Values should be realistic for production systems
5. Context including recent deployments or configuration changes
6. Expected remediation action types (restart, scale, rollback, etc.)

Make the scenario realistic and educational for demonstrating an AI-powered incident response system.

Current timestamp: {datetime.now(timezone.utc).isoformat()}
"""

    def _convert_to_scenario(
        self,
        generated: GeneratedScenario,
        service_name: str,
        prompt: str,
    ) -> IncidentScenario:
        """
        Convert LLM-generated scenario to IncidentScenario dataclass.

        Args:
            generated: LLM output
            service_name: Service name
            prompt: Original prompt (for metadata)

        Returns:
            IncidentScenario ready to use
        """
        # Convert metrics
        metrics = []
        for m in generated.metrics:
            metrics.append(
                MetricPattern(
                    metric_name=m.metric_name,
                    value=m.value,
                    baseline=m.baseline,
                    deviation_sigma=m.deviation_sigma,
                    pattern_type=MetricPatternType.CONSTANT,  # LLM doesn't generate patterns yet
                    unit=m.unit,
                )
            )

        # Infer tags from root cause
        tags = self._infer_tags(generated.root_cause, generated.description)

        # Infer difficulty from severity and complexity
        difficulty = self._infer_difficulty(generated.severity, len(metrics))

        # Generate unique ID from prompt
        scenario_id = f"llm_{hash(prompt) % 1000000:06d}"

        # Build scenario
        scenario = IncidentScenario(
            scenario_id=scenario_id,
            name=f"[LLM] {generated.name}",
            description=f"{generated.description}\n\n"
                        f"_This scenario was generated by LLM from prompt: \"{prompt[:100]}...\"_",
            service_name=service_name,
            metrics=metrics,
            expected_severity=generated.severity,
            expected_root_cause=generated.root_cause,
            expected_action_types=generated.expected_action_types,
            context={
                **generated.context,
                "generated_by": "llm",
                "generation_prompt": prompt,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            tags=tags,
            difficulty=difficulty,
            duration_seconds=300,  # Default 5 minutes
        )

        return scenario

    def _infer_tags(self, root_cause: str, description: str) -> List[ScenarioTag]:
        """Infer appropriate tags from root cause and description."""
        tags = []

        # Check root cause and description for keywords
        text = f"{root_cause} {description}".lower()

        if any(word in text for word in ["memory", "cpu", "disk", "resource"]):
            tags.append(ScenarioTag.RESOURCE)

        if any(word in text for word in ["latency", "slow", "performance", "timeout"]):
            tags.append(ScenarioTag.PERFORMANCE)

        if any(word in text for word in ["crash", "restart", "down", "unavailable"]):
            tags.append(ScenarioTag.AVAILABILITY)

        if any(word in text for word in ["external", "dependency", "api", "database"]):
            tags.append(ScenarioTag.EXTERNAL)

        if any(word in text for word in ["config", "deployment", "environment"]):
            tags.append(ScenarioTag.CONFIGURATION)

        # Default to PERFORMANCE if no tags matched
        if not tags:
            tags.append(ScenarioTag.PERFORMANCE)

        return tags

    def _infer_difficulty(self, severity: str, metric_count: int) -> ScenarioDifficulty:
        """Infer difficulty from severity and complexity."""
        if severity in ["critical", "high"] and metric_count >= 5:
            return ScenarioDifficulty.ADVANCED
        elif severity in ["high", "medium"] and metric_count >= 3:
            return ScenarioDifficulty.INTERMEDIATE
        else:
            return ScenarioDifficulty.BEGINNER


# ============================================
# Singleton Instance
# ============================================

_generator_instance = None


def get_scenario_generator(llm_client: LLMClient = None) -> LLMScenarioGenerator:
    """
    Get or create the singleton scenario generator.

    Args:
        llm_client: Optional LLM client instance

    Returns:
        LLMScenarioGenerator instance
    """
    global _generator_instance

    if _generator_instance is None:
        _generator_instance = LLMScenarioGenerator(llm_client)
        logger.info("Created LLMScenarioGenerator instance")

    return _generator_instance
