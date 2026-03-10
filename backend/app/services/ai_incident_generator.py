"""
AI-Powered Incident Generator

Continuously generates realistic, unique incident scenarios using LLM.
Runs as a background task to simulate ongoing system monitoring.
"""
import logging
import random
from datetime import datetime, timezone

from app.config import settings
from app.database import get_db_context
from app.models.incident import Incident, IncidentSeverity, IncidentStatus

logger = logging.getLogger(__name__)


class AIIncidentGenerator:
    """
    Generates realistic incidents using AI/LLM.

    Purpose:
    - Create variety in demo incidents
    - Simulate continuous monitoring
    - Showcase AI capabilities
    - Rate-limited to control API costs
    """

    def __init__(
        self,
        interval_minutes: int = 30,
        incidents_per_cycle: int = 1,
        enabled: bool = True,
    ):
        self.interval_minutes = interval_minutes
        self.incidents_per_cycle = incidents_per_cycle
        self.enabled = enabled

        # Service pool for variety
        self.services = [
            "payment-service",
            "order-service",
            "user-service",
            "inventory-service",
            "notification-service",
            "auth-service",
            "search-service",
            "recommendation-service",
            "analytics-service",
        ]

        # Incident patterns for LLM prompts
        self.incident_patterns = [
            "memory_leak",
            "cpu_spike",
            "high_latency",
            "error_rate_spike",
            "disk_full",
            "connection_pool_exhausted",
            "cache_miss_storm",
            "database_deadlock",
            "api_timeout",
            "rate_limit_exceeded",
        ]

    async def generate_once(self) -> None:
        """
        Public facade for Celery tasks — run a single generation cycle.

        Celery monitoring tasks call this instead of the private
        _generate_incidents() so the contract is explicit (S1 fix).
        """
        await self._generate_incidents()

    async def _generate_incidents(self):
        """Generate AI-powered incidents for this cycle."""
        try:
            from app.services.llm_client import get_llm_client

            # NEW-10 fix: pass the generator model at construction time instead of
            # mutating the returned instance. The shared singleton (if cached) would
            # otherwise have its .model field changed, corrupting concurrent callers
            # (e.g. hypothesis generator) that rely on the reasoning model.
            # llama-3.1-8b-instant is on Groq's free tier and is sufficient
            # for creative incident text generation (no deep reasoning needed).
            llm_client = get_llm_client(model=settings.llm_generator_model)

            async with get_db_context() as db:
                for _ in range(self.incidents_per_cycle):
                    try:
                        # Select random service and pattern
                        service = random.choice(self.services)
                        pattern = random.choice(self.incident_patterns)

                        # Generate incident using LLM
                        prompt = self._create_generation_prompt(service, pattern)

                        logger.info(
                            f"Generating AI incident for {service} ({pattern}) "
                            f"using {settings.llm_generator_model}"
                        )

                        response = await llm_client.generate(
                            prompt=prompt,
                            system_prompt="You are an expert SRE generating realistic incident scenarios for training and demos.",
                            temperature=0.9,  # Higher creativity for varied incidents
                            max_tokens=500,
                        )

                        # Parse LLM response and create incident
                        incident_data = self._parse_llm_response(
                            response.content,
                            service,
                            pattern
                        )

                        # Create incident in database
                        incident = Incident(
                            title=incident_data["title"],
                            description=incident_data["description"],
                            severity=incident_data["severity"],
                            status=IncidentStatus.DETECTED,
                            affected_service=service,
                            affected_components=[service],
                            detected_at=datetime.now(timezone.utc),
                            detection_source="ai_generator",
                            metrics_snapshot=incident_data.get("metrics", {}),
                            context={
                                "ai_generated": True,
                                "pattern": pattern,
                                "generation_timestamp": datetime.now(timezone.utc).isoformat(),
                            },
                            # AI-generated incidents carry fictional root causes.
                            # Low trust prevents them from poisoning RAG context
                            # even if the detection_source filter is ever relaxed.
                            trust_score=0.2,
                        )

                        db.add(incident)
                        # S2 fix: flush to obtain DB-generated ID without committing
                        # mid-loop. The context manager commits atomically on exit.
                        await db.flush()
                        await db.refresh(incident)

                        logger.info(
                            f"Created AI-generated incident: {incident.id} "
                            f"({service}, {incident_data['severity']})"
                        )

                    except Exception as e:
                        logger.warning(f"Failed to generate single incident: {str(e)}")
                        continue

        except Exception as e:
            logger.error(f"Failed to generate AI incidents: {str(e)}", exc_info=True)

    def _create_generation_prompt(self, service: str, pattern: str) -> str:
        """Create LLM prompt for incident generation."""
        return f"""Generate a realistic production incident scenario for a microservice.

Service: {service}
Incident Pattern: {pattern}

Generate a JSON object with:
1. title: Brief incident title (50-80 chars)
2. description: Detailed description with symptoms and context (200-300 words)
3. severity: "critical", "high", "medium", or "low"
4. metrics: Dict of 3-5 relevant metrics showing anomalies

Make it realistic, specific, and unique. Include:
- What users are experiencing
- Observable symptoms (metrics, logs, alerts)
- Potential business impact
- Time of onset

Output ONLY valid JSON, no markdown or extra text:
{{
  "title": "...",
  "description": "...",
  "severity": "...",
  "metrics": {{"metric_name": {{"current": 1000, "expected": 100, "deviation": 5.2}}}}
}}"""

    def _parse_llm_response(
        self, response: str, service: str, pattern: str
    ) -> dict:
        """Parse LLM response into incident data."""
        import json

        from app.services.llm_client import extract_json_from_llm_response

        try:
            # Extract JSON using bracket-counting parser (handles markdown code
            # blocks, preamble text, and nested objects correctly).
            content = extract_json_from_llm_response(response)
            data = json.loads(content)

            # Validate and normalize
            return {
                "title": f"[AI] {data.get('title', 'AI-generated incident')[:100]}",
                "description": data.get('description', f"AI-generated incident for {service}"),
                "severity": self._normalize_severity(data.get('severity', 'medium')),
                "metrics": data.get('metrics', {}),
            }

        except Exception as e:
            logger.warning(f"Failed to parse LLM response: {str(e)}")

            # Fallback to basic incident
            return {
                "title": f"[AI] {pattern.replace('_', ' ').title()} in {service}",
                "description": f"AI-generated incident: {pattern} detected in {service}. This is a simulated incident for demonstration purposes.",
                "severity": IncidentSeverity.MEDIUM,
                "metrics": {},
            }

    def _normalize_severity(self, severity: str) -> IncidentSeverity:
        """Normalize severity string to enum."""
        severity_map = {
            "critical": IncidentSeverity.CRITICAL,
            "high": IncidentSeverity.HIGH,
            "medium": IncidentSeverity.MEDIUM,
            "low": IncidentSeverity.LOW,
        }
        return severity_map.get(severity.lower(), IncidentSeverity.MEDIUM)


# Global generator instance
_generator: AIIncidentGenerator | None = None


def get_ai_generator() -> AIIncidentGenerator:
    """Get the global AI generator instance."""
    global _generator
    if _generator is None:
        # Configuration from environment
        interval = 30  # Default 30 minutes
        rate = 1  # Default 1 incident per cycle
        enabled = settings.environment == "development"  # Only in dev

        _generator = AIIncidentGenerator(
            interval_minutes=interval,
            incidents_per_cycle=rate,
            enabled=enabled,
        )
    return _generator


