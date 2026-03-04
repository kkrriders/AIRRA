"""
Postmortem API Schemas
"""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ActionItem(BaseModel):
    """Single action item in postmortem."""

    description: str = Field(..., min_length=1, max_length=500)
    owner: str = Field(..., description="Email of person responsible")
    due_date: str | None = Field(None, description="Due date (YYYY-MM-DD)")
    priority: str = Field("medium", description="low, medium, high, critical")
    status: str = Field("open", description="open, in_progress, completed, cancelled")


class PostmortemCreate(BaseModel):
    """Create a new postmortem."""

    incident_id: UUID
    actual_root_cause: str = Field(..., min_length=10, max_length=2000)
    contributing_factors: list[str] = Field(default=[])
    detection_delay_reason: str | None = None

    # Impact
    duration_minutes: int = Field(..., ge=0)
    users_affected: int | None = Field(None, ge=0)
    revenue_impact_usd: float | None = Field(None, ge=0)

    # Learnings
    what_went_well: list[str] = Field(default=[])
    what_went_wrong: list[str] = Field(default=[])
    lessons_learned: list[str] = Field(default=[])

    # Actions
    action_items: list[ActionItem] = Field(default=[])
    prevention_measures: list[str] = Field(default=[])
    detection_improvements: list[str] = Field(default=[])
    response_improvements: list[str] = Field(default=[])

    # AI evaluation
    ai_hypothesis_correct: bool | None = None
    ai_evaluation_notes: str | None = None

    # Notes
    additional_notes: str | None = None


class PostmortemUpdate(BaseModel):
    """Update an existing postmortem."""

    actual_root_cause: str | None = Field(None, min_length=10, max_length=2000)
    contributing_factors: list[str] | None = None
    detection_delay_reason: str | None = None

    # Impact
    duration_minutes: int | None = Field(None, ge=0)
    users_affected: int | None = Field(None, ge=0)
    revenue_impact_usd: float | None = Field(None, ge=0)

    # Learnings
    what_went_well: list[str] | None = None
    what_went_wrong: list[str] | None = None
    lessons_learned: list[str] | None = None

    # Actions
    action_items: list[ActionItem] | None = None
    prevention_measures: list[str] | None = None
    detection_improvements: list[str] | None = None
    response_improvements: list[str] | None = None

    # AI evaluation
    ai_hypothesis_correct: bool | None = None
    ai_evaluation_notes: str | None = None

    # Notes
    additional_notes: str | None = None

    # Publication
    published: bool | None = None


class PostmortemResponse(BaseModel):
    """Postmortem response."""

    id: UUID
    incident_id: UUID
    author_id: UUID | None

    # Root cause
    actual_root_cause: str
    contributing_factors: list[str]
    detection_delay_reason: str | None

    # Impact
    duration_minutes: int
    users_affected: int | None
    revenue_impact_usd: float | None

    # Learnings
    what_went_well: list[str]
    what_went_wrong: list[str]
    lessons_learned: list[str]

    # Actions
    action_items: list[dict]
    prevention_measures: list[str]
    detection_improvements: list[str]
    response_improvements: list[str]

    # AI evaluation
    ai_hypothesis_correct: bool | None
    ai_evaluation_notes: str | None

    # Meta
    additional_notes: str | None
    published: bool
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TimelineEvent(BaseModel):
    """Timeline event for display."""

    id: UUID
    event_type: str
    description: str
    actor: str | None
    metadata: dict
    timestamp: datetime

    class Config:
        from_attributes = True


class IncidentTimeline(BaseModel):
    """Full incident timeline."""

    incident_id: UUID
    events: list[TimelineEvent]
    total_events: int
    duration_minutes: int | None
