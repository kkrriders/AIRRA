"""
Learning and Feedback API endpoints.

Endpoints for capturing outcomes and viewing learning insights.
"""
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.learning_engine import (
    IncidentOutcome,
    get_learning_engine,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class OutcomeRequest(BaseModel):
    """Request to capture incident outcome."""

    hypothesis_id: str | None = None
    hypothesis_correct: bool = False
    action_id: str | None = None
    action_effective: bool = False
    human_override: bool = False
    override_reason: str | None = None
    resolution_notes: str = ""


@router.post("/{incident_id}/outcome")
async def capture_outcome(
    incident_id: UUID,
    outcome_request: OutcomeRequest,
):
    """
    Capture the outcome of an incident resolution for learning.

    This endpoint records whether:
    - The hypothesis was correct
    - The action was effective
    - Human intervention was needed

    This data improves future predictions.
    """
    try:
        learning_engine = get_learning_engine()

        outcome = IncidentOutcome(
            incident_id=str(incident_id),
            hypothesis_id=outcome_request.hypothesis_id,
            hypothesis_correct=outcome_request.hypothesis_correct,
            action_id=outcome_request.action_id,
            action_effective=outcome_request.action_effective,
            human_override=outcome_request.human_override,
            override_reason=outcome_request.override_reason,
            resolution_notes=outcome_request.resolution_notes,
        )

        await learning_engine.capture_outcome(outcome)

        return {
            "status": "success",
            "message": "Outcome captured successfully",
        }

    except Exception as e:
        logger.error(f"Failed to capture outcome: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to capture outcome: {str(e)}")


@router.get("/insights")
async def get_insights(days: int = 30):
    """
    Get learning insights and system performance metrics.

    Returns statistics on:
    - Incident resolution rates
    - Hypothesis accuracy
    - Action effectiveness
    - Learned patterns

    Args:
        days: Number of days to analyze (default: 30)
    """
    try:
        learning_engine = get_learning_engine()
        insights = await learning_engine.generate_insights(days=days)

        return insights

    except Exception as e:
        logger.error(f"Failed to generate insights: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate insights: {str(e)}")


@router.get("/patterns")
async def get_patterns():
    """
    Get learned incident patterns.

    Returns all patterns in the pattern library with their success rates.
    """
    try:
        learning_engine = get_learning_engine()

        patterns = [
            {
                "pattern_id": pattern.pattern_id,
                "name": pattern.name,
                "category": pattern.category,
                "occurrence_count": pattern.occurrence_count,
                "success_rate": pattern.success_rate,
                "confidence_adjustment": pattern.confidence_adjustment,
            }
            for pattern in learning_engine.patterns.values()
        ]

        return {
            "total_patterns": len(patterns),
            "patterns": patterns,
        }

    except Exception as e:
        logger.error(f"Failed to get patterns: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get patterns: {str(e)}")
