"""
Postmortem API Schemas
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ActionItem(BaseModel):
    """Single action item in postmortem."""

    description: str = Field(..., min_length=1, max_length=500)
    owner: str = Field(..., description="Email of person responsible")
    due_date: Optional[str] = Field(None, description="Due date (YYYY-MM-DD)")
    priority: str = Field("medium", description="low, medium, high, critical")
    status: str = Field("open", description="open, in_progress, completed, cancelled")


class PostmortemCreate(BaseModel):
    """Create a new postmortem."""

    incident_id: UUID
    actual_root_cause: str = Field(..., min_length=10, max_length=2000)
    contributing_factors: list[str] = Field(default=[])
    detection_delay_reason: Optional[str] = None

    # Impact
    duration_minutes: int = Field(..., ge=0)
    users_affected: Optional[int] = Field(None, ge=0)
    revenue_impact_usd: Optional[float] = Field(None, ge=0)

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
    ai_hypothesis_correct: Optional[bool] = None
    ai_evaluation_notes: Optional[str] = None

    # Notes
    additional_notes: Optional[str] = None


class PostmortemUpdate(BaseModel):
    """Update an existing postmortem."""

    actual_root_cause: Optional[str] = Field(None, min_length=10, max_length=2000)
    contributing_factors: Optional[list[str]] = None
    detection_delay_reason: Optional[str] = None

    # Impact
    duration_minutes: Optional[int] = Field(None, ge=0)
    users_affected: Optional[int] = Field(None, ge=0)
    revenue_impact_usd: Optional[float] = Field(None, ge=0)

    # Learnings
    what_went_well: Optional[list[str]] = None
    what_went_wrong: Optional[list[str]] = None
    lessons_learned: Optional[list[str]] = None

    # Actions
    action_items: Optional[list[ActionItem]] = None
    prevention_measures: Optional[list[str]] = None
    detection_improvements: Optional[list[str]] = None
    response_improvements: Optional[list[str]] = None

    # AI evaluation
    ai_hypothesis_correct: Optional[bool] = None
    ai_evaluation_notes: Optional[str] = None

    # Notes
    additional_notes: Optional[str] = None

    # Publication
    published: Optional[bool] = None


class PostmortemResponse(BaseModel):
    """Postmortem response."""

    id: UUID
    incident_id: UUID
    author_id: Optional[UUID]

    # Root cause
    actual_root_cause: str
    contributing_factors: list[str]
    detection_delay_reason: Optional[str]

    # Impact
    duration_minutes: int
    users_affected: Optional[int]
    revenue_impact_usd: Optional[float]

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
    ai_hypothesis_correct: Optional[bool]
    ai_evaluation_notes: Optional[str]

    # Meta
    additional_notes: Optional[str]
    published: bool
    published_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TimelineEvent(BaseModel):
    """Timeline event for display."""

    id: UUID
    event_type: str
    description: str
    actor: Optional[str]
    metadata: dict
    timestamp: datetime

    class Config:
        from_attributes = True


class IncidentTimeline(BaseModel):
    """Full incident timeline."""

    incident_id: UUID
    events: list[TimelineEvent]
    total_events: int
    duration_minutes: Optional[int]
