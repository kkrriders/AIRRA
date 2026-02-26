import logging
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.database import get_db_context
from app.models.action import Action, ActionStatus
from app.models.hypothesis import Hypothesis
from app.models.incident import Incident, IncidentStatus

logger = logging.getLogger(__name__)


class IncidentOutcome(BaseModel):
    """Captured outcome of an incident resolution."""

    incident_id: UUID
    hypothesis_id: Optional[UUID] = None
    hypothesis_correct: bool = False
    action_id: Optional[UUID] = None
    action_effective: bool = False
    time_to_resolution_minutes: Optional[int] = None
    human_override: bool = False
    override_reason: Optional[str] = None
    resolution_notes: str = ""


class PatternSignature(BaseModel):
    """Signature of an incident pattern for matching."""

    pattern_id: str = Field(..., description="Unique pattern identifier")
    name: str = Field(..., description="Human-readable pattern name")
    category: str = Field(..., description="Incident category")
    signal_indicators: list[str] = Field(..., description="Key signal patterns")
    confidence_adjustment: float = Field(
        default=0.0, ge=-0.5, le=0.5, description="Confidence adjustment based on history"
    )
    occurrence_count: int = Field(default=1, description="How many times this pattern occurred")
    success_rate: float = Field(default=0.0, ge=0.0, le=1.0, description="Resolution success rate")


class LearningEngine:
    """
    Engine for capturing feedback and improving system performance.

    Responsibilities:
    1. Capture incident outcomes
    2. Update hypothesis confidence scores
    3. Build and refine pattern library
    4. Generate runbook improvement suggestions
    """

    def __init__(self):
        self.patterns: dict[str, PatternSignature] = {}

    async def capture_outcome(self, outcome: IncidentOutcome) -> None:
        """
        Capture the outcome of an incident resolution.

        Args:
            outcome: Structured outcome data
        """
        try:
            logger.info(f"Capturing outcome for incident {outcome.incident_id}")

            async with get_db_context() as db:
                # Get incident
                from sqlalchemy import select

                stmt = select(Incident).where(Incident.id == outcome.incident_id)
                result = await db.execute(stmt)
                incident = result.scalar_one_or_none()

                if not incident:
                    logger.error(f"Incident {outcome.incident_id} not found")
                    return

                # Update incident resolution metrics
                if incident.resolved_at and incident.detected_at:
                    resolution_time = (incident.resolved_at - incident.detected_at).total_seconds()
                    incident.resolution_time_seconds = int(resolution_time)

                # Get hypothesis if provided
                if outcome.hypothesis_id:
                    stmt = select(Hypothesis).where(Hypothesis.id == outcome.hypothesis_id)
                    result = await db.execute(stmt)
                    hypothesis = result.scalar_one_or_none()

                    if hypothesis:
                        # Update hypothesis validation
                        hypothesis.validated = outcome.hypothesis_correct
                        hypothesis.validation_feedback = outcome.resolution_notes

                        # Update pattern library
                        await self._update_pattern_library(
                            incident=incident,
                            hypothesis=hypothesis,
                            was_correct=outcome.hypothesis_correct,
                        )

                # Get action if provided
                if outcome.action_id:
                    stmt = select(Action).where(Action.id == outcome.action_id)
                    result = await db.execute(stmt)
                    action = result.scalar_one_or_none()

                    if action:
                        # Record action effectiveness
                        action.execution_result = action.execution_result or {}
                        action.execution_result["effective"] = outcome.action_effective
                        action.execution_result["resolution_notes"] = outcome.resolution_notes

                # Update incident context with learning metadata
                incident.context = incident.context or {}
                incident.context["learning"] = {
                    "hypothesis_correct": outcome.hypothesis_correct,
                    "action_effective": outcome.action_effective,
                    "human_override": outcome.human_override,
                    "override_reason": outcome.override_reason,
                    "captured_at": datetime.utcnow().isoformat(),
                }

                await db.commit()

                logger.info(
                    f"Outcome captured for incident {outcome.incident_id} "
                    f"(hypothesis_correct={outcome.hypothesis_correct}, "
                    f"action_effective={outcome.action_effective})"
                )

        except Exception as e:
            logger.error(f"Failed to capture outcome: {str(e)}", exc_info=True)

    async def _update_pattern_library(
        self,
        incident: Incident,
        hypothesis: Hypothesis,
        was_correct: bool,
    ) -> None:
        """Update the pattern library based on outcome."""
        try:
            # Create pattern signature
            pattern_id = f"{incident.affected_service}:{hypothesis.category}"

            if pattern_id in self.patterns:
                pattern = self.patterns[pattern_id]

                # Update occurrence count
                pattern.occurrence_count += 1

                # Update success rate
                if was_correct:
                    pattern.success_rate = (
                        pattern.success_rate * (pattern.occurrence_count - 1) + 1
                    ) / pattern.occurrence_count
                else:
                    pattern.success_rate = (
                        pattern.success_rate * (pattern.occurrence_count - 1)
                    ) / pattern.occurrence_count

                # Adjust confidence based on success rate
                if pattern.success_rate > 0.8:
                    pattern.confidence_adjustment = 0.1
                elif pattern.success_rate < 0.3:
                    pattern.confidence_adjustment = -0.1
                else:
                    pattern.confidence_adjustment = 0.0

                logger.info(
                    f"Updated pattern {pattern_id}: "
                    f"occurrences={pattern.occurrence_count}, "
                    f"success_rate={pattern.success_rate:.2%}"
                )

            else:
                # Create new pattern
                pattern = PatternSignature(
                    pattern_id=pattern_id,
                    name=f"{incident.affected_service} - {hypothesis.category}",
                    category=hypothesis.category,
                    signal_indicators=hypothesis.supporting_signals,
                    confidence_adjustment=0.0,
                    occurrence_count=1,
                    success_rate=1.0 if was_correct else 0.0,
                )
                self.patterns[pattern_id] = pattern

                logger.info(f"Created new pattern {pattern_id}")

        except Exception as e:
            logger.error(f"Failed to update pattern library: {str(e)}")

    async def get_pattern(self, service: str, category: str) -> Optional[PatternSignature]:
        """Get pattern for a service and category."""
        pattern_id = f"{service}:{category}"
        return self.patterns.get(pattern_id)

    async def get_confidence_adjustment(self, service: str, category: str) -> float:
        """
        Get confidence adjustment for a hypothesis based on historical patterns.

        Returns:
            Confidence adjustment (-0.5 to +0.5)
        """
        pattern = await self.get_pattern(service, category)
        if pattern:
            return pattern.confidence_adjustment
        return 0.0

    async def generate_insights(self, days: int = 30) -> dict:
        """
        Generate insights from learning data.

        Returns:
            Dict with insights about system performance
        """
        try:
            async with get_db_context() as db:
                from sqlalchemy import func, select

                # Get incidents from last N days
                since = datetime.utcnow() - timedelta(days=days)

                # Count total incidents
                stmt = select(func.count()).select_from(Incident).where(Incident.detected_at >= since)
                result = await db.execute(stmt)
                total_incidents = result.scalar_one()

                # Count resolved incidents
                stmt = (
                    select(func.count())
                    .select_from(Incident)
                    .where(
                        Incident.detected_at >= since, Incident.status == IncidentStatus.RESOLVED
                    )
                )
                result = await db.execute(stmt)
                resolved_incidents = result.scalar_one()

                # Calculate average resolution time
                stmt = (
                    select(func.avg(Incident.resolution_time_seconds))
                    .select_from(Incident)
                    .where(
                        Incident.detected_at >= since,
                        Incident.status == IncidentStatus.RESOLVED,
                        Incident.resolution_time_seconds.isnot(None),
                    )
                )
                result = await db.execute(stmt)
                avg_resolution_time = result.scalar_one() or 0

                # Count validated hypotheses
                stmt = (
                    select(func.count())
                    .select_from(Hypothesis)
                    .where(Hypothesis.validated == True)  # noqa: E712
                )
                result = await db.execute(stmt)
                correct_hypotheses = result.scalar_one()

                # Count total hypotheses
                stmt = select(func.count()).select_from(Hypothesis)
                result = await db.execute(stmt)
                total_hypotheses = result.scalar_one()

                # Calculate hypothesis accuracy
                hypothesis_accuracy = (
                    (correct_hypotheses / total_hypotheses) if total_hypotheses > 0 else 0.0
                )

                # Count successful actions
                stmt = (
                    select(func.count())
                    .select_from(Action)
                    .where(Action.status == ActionStatus.SUCCEEDED)
                )
                result = await db.execute(stmt)
                successful_actions = result.scalar_one()

                return {
                    "period_days": days,
                    "total_incidents": total_incidents,
                    "resolved_incidents": resolved_incidents,
                    "resolution_rate": (
                        (resolved_incidents / total_incidents) if total_incidents > 0 else 0.0
                    ),
                    "avg_resolution_time_seconds": int(avg_resolution_time),
                    "avg_resolution_time_minutes": int(avg_resolution_time / 60),
                    "hypothesis_accuracy": hypothesis_accuracy,
                    "total_hypotheses": total_hypotheses,
                    "correct_hypotheses": correct_hypotheses,
                    "successful_actions": successful_actions,
                    "patterns_learned": len(self.patterns),
                }

        except Exception as e:
            logger.error(f"Failed to generate insights: {str(e)}", exc_info=True)
            return {}


# Global learning engine instance
_learning_engine: Optional[LearningEngine] = None


def get_learning_engine() -> LearningEngine:
    """Get the global learning engine instance."""
    global _learning_engine
    if _learning_engine is None:
        _learning_engine = LearningEngine()
    return _learning_engine
