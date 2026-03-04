"""
Pydantic schemas for EngineerReview API requests and responses.

Senior Engineering Note:
- Strict validation with type hints
- Separate schemas for create/update/response
- ConfigDict for ORM integration
"""
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.engineer_review import ReviewDecision, ReviewStatus

if TYPE_CHECKING:
    from app.schemas.engineer import EngineerResponse
    from app.schemas.incident import IncidentResponse


class EngineerReviewBase(BaseModel):
    """Base schema with common fields."""

    notes: str = Field(default="", description="Engineer's detailed notes and reasoning")
    tags: list[str] = Field(
        default_factory=list,
        description="Tags for categorizing review (e.g., ['complex', 'escalation'])",
    )


class EngineerReviewCreate(EngineerReviewBase):
    """Schema for creating a new review (assignment)."""

    incident_id: UUID
    engineer_id: UUID
    priority: str = Field(
        default="normal",
        pattern="^(low|normal|high|critical)$",
        description="Review priority level",
    )
    additional_info: dict = Field(default_factory=dict)


class EngineerReviewUpdate(BaseModel):
    """Schema for updating a review (engineer submits review)."""

    status: ReviewStatus | None = None
    started_at: datetime | None = None
    submitted_at: datetime | None = None
    ai_hypotheses_reviewed: dict | None = Field(
        None,
        description="Map of hypothesis_id -> validation result (validated/rejected/uncertain)",
    )
    ai_confidence_assessment: str | None = Field(
        None,
        description="Engineer's assessment of AI confidence scores",
    )
    alternative_hypotheses: list[dict] | None = Field(
        None,
        description="Engineer-proposed alternative root causes",
    )
    suggested_approach: dict | None = Field(
        None,
        description="Engineer's suggested remediation approach",
    )
    engineer_confidence_score: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Engineer's confidence in their approach (0-1)",
    )
    notes: str | None = None
    tags: list[str] | None = None


class EngineerReviewSubmit(BaseModel):
    """Schema for submitting a completed review."""

    ai_hypotheses_reviewed: dict = Field(
        ...,
        description="Validation of each AI hypothesis",
    )
    ai_confidence_assessment: str = Field(
        ...,
        min_length=1,
        description="Assessment of AI's confidence and reasoning",
    )
    alternative_hypotheses: list[dict] = Field(
        default_factory=list,
        description="Alternative root cause hypotheses from engineer",
    )
    suggested_approach: dict = Field(
        ...,
        description="Engineer's suggested remediation steps",
    )
    engineer_confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in the suggested approach",
    )
    notes: str = Field(..., min_length=1, description="Detailed review notes")
    tags: list[str] = Field(default_factory=list)


class EngineerReviewResponse(EngineerReviewBase):
    """Schema for review responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    incident_id: UUID
    engineer_id: UUID
    status: ReviewStatus
    assigned_at: datetime
    started_at: datetime | None = None
    submitted_at: datetime | None = None
    review_time_minutes: float | None = None
    ai_hypotheses_reviewed: dict
    ai_confidence_assessment: str | None = None
    alternative_hypotheses: list[dict]
    suggested_approach: dict
    engineer_confidence_score: float | None = None
    decision: ReviewDecision
    decision_made_at: datetime | None = None
    decision_rationale: str | None = None
    approach_executed: str | None = None
    execution_successful: bool | None = None
    outcome_notes: str | None = None
    priority: str
    additional_info: dict
    created_at: datetime
    updated_at: datetime


class EngineerReviewWithRelations(EngineerReviewResponse):
    """Schema for review with related entities."""

    engineer: Optional["EngineerResponse"] = None
    incident: Optional["IncidentResponse"] = None


class EngineerReviewListResponse(BaseModel):
    """Schema for paginated review list."""

    items: list[EngineerReviewResponse]
    total: int
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1, le=100)
    pages: int = Field(..., ge=0)


class ReviewAssignment(BaseModel):
    """Schema for assigning a review to an engineer."""

    engineer_id: UUID
    priority: str = Field(
        default="normal",
        pattern="^(low|normal|high|critical)$",
    )
    notes: str = Field(default="", description="Assignment notes")


class ReviewDecisionRequest(BaseModel):
    """Schema for making a decision on AI vs Engineer approach."""

    decision: ReviewDecision = Field(
        ...,
        description="Which approach to execute (ai_approach/engineer_approach/hybrid)",
    )
    rationale: str = Field(
        ...,
        min_length=1,
        description="Explanation for the decision",
    )


class ReviewComparison(BaseModel):
    """Schema for comparing AI and Engineer approaches."""

    incident_id: UUID
    ai_approach: dict = Field(..., description="AI's hypothesis and suggested actions")
    engineer_approach: dict = Field(..., description="Engineer's analysis and suggestions")
    ai_confidence: float = Field(..., ge=0.0, le=1.0)
    engineer_confidence: float = Field(..., ge=0.0, le=1.0)
    differences: list[str] = Field(..., description="Key differences between approaches")
    recommendations: list[str] = Field(..., description="Recommendations for decision")


# Rebuild model to resolve forward references
from app.schemas.engineer import EngineerResponse  # noqa: E402
from app.schemas.incident import IncidentResponse  # noqa: E402

EngineerReviewWithRelations.model_rebuild()
