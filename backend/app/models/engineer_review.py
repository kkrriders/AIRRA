"""
EngineerReview model tracking human expert reviews of AI-generated hypotheses.

Senior Engineering Note:
- Links incidents, engineers, and review outcomes
- Stores AI hypothesis validation and alternative approaches
- Status tracking for review lifecycle
- Foreign keys with proper cascading
"""
import enum
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Index,
    String,
    Text,
    ForeignKey,
    Float,
    Enum as SQLEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.incident import Incident
    from app.models.engineer import Engineer


class ReviewStatus(str, enum.Enum):
    """Engineer review lifecycle states."""

    ASSIGNED = "assigned"  # Assigned to engineer, not started
    IN_PROGRESS = "in_progress"  # Engineer actively working on review
    SUBMITTED = "submitted"  # Review submitted, awaiting decision
    ACCEPTED = "accepted"  # Engineer's approach accepted and executed
    REJECTED = "rejected"  # AI approach chosen instead
    CANCELLED = "cancelled"  # Review cancelled (incident resolved, etc.)


class ReviewDecision(str, enum.Enum):
    """Decision outcome for review comparison."""

    AI_APPROACH = "ai_approach"  # Use AI's hypothesis and actions
    ENGINEER_APPROACH = "engineer_approach"  # Use engineer's suggestion
    HYBRID_APPROACH = "hybrid_approach"  # Combine both approaches
    PENDING = "pending"  # No decision made yet


class EngineerReview(Base, TimestampMixin):
    """
    Review record tracking engineer validation of AI hypotheses.

    Represents a single review assignment where an engineer evaluates
    AI-generated hypotheses and potentially suggests alternatives.
    """

    __tablename__ = "engineer_reviews"

    # Primary key
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # Foreign keys
    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    engineer_id: Mapped[UUID] = mapped_column(
        ForeignKey("engineers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Review lifecycle tracking
    status: Mapped[ReviewStatus] = mapped_column(
        SQLEnum(ReviewStatus),
        nullable=False,
        default=ReviewStatus.ASSIGNED,
        index=True,
    )
    assigned_at: Mapped[datetime] = mapped_column(nullable=False, index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    review_time_minutes: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        comment="Time spent on review in minutes",
    )

    # AI hypothesis validation
    ai_hypotheses_reviewed: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Map of hypothesis_id -> validation result (validated/rejected/uncertain)",
    )
    ai_confidence_assessment: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Engineer's assessment of AI confidence scores",
    )

    # Engineer's alternative analysis
    alternative_hypotheses: Mapped[list[dict]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="Engineer-proposed alternative root causes",
    )
    suggested_approach: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Engineer's suggested remediation approach",
    )
    engineer_confidence_score: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        comment="Engineer's confidence in their suggested approach (0-1)",
    )

    # Review content
    notes: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        comment="Engineer's detailed notes and reasoning",
    )
    tags: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="Tags for categorizing review (e.g., ['complex', 'needs-escalation'])",
    )

    # Decision tracking
    decision: Mapped[ReviewDecision] = mapped_column(
        SQLEnum(ReviewDecision),
        nullable=False,
        default=ReviewDecision.PENDING,
        index=True,
    )
    decision_made_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    decision_rationale: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Explanation for choosing AI vs Engineer approach",
    )

    # Outcome tracking
    approach_executed: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="Which approach was executed (ai/engineer/hybrid)",
    )
    execution_successful: Mapped[Optional[bool]] = mapped_column(nullable=True)
    outcome_notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Notes about execution outcome",
    )

    # Additional info
    priority: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="normal",
        comment="Review priority (low/normal/high/critical)",
    )
    additional_info: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Additional metadata",
    )

    # Relationships
    incident: Mapped["Incident"] = relationship(
        "Incident",
        back_populates="engineer_reviews",
    )
    engineer: Mapped["Engineer"] = relationship(
        "Engineer",
        back_populates="reviews",
    )

    # Indexes for common queries
    __table_args__ = (
        Index("idx_review_status_assigned", "status", "assigned_at"),
        Index("idx_review_engineer_status", "engineer_id", "status"),
        Index("idx_review_incident", "incident_id", "status"),
        Index("idx_review_decision", "decision", "decision_made_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<EngineerReview(id={self.id}, "
            f"incident_id={self.incident_id}, "
            f"engineer_id={self.engineer_id}, "
            f"status={self.status.value}, "
            f"decision={self.decision.value})>"
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "id": str(self.id),
            "incident_id": str(self.incident_id),
            "engineer_id": str(self.engineer_id),
            "status": self.status.value,
            "assigned_at": self.assigned_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "review_time_minutes": self.review_time_minutes,
            "ai_hypotheses_reviewed": self.ai_hypotheses_reviewed,
            "ai_confidence_assessment": self.ai_confidence_assessment,
            "alternative_hypotheses": self.alternative_hypotheses,
            "suggested_approach": self.suggested_approach,
            "engineer_confidence_score": self.engineer_confidence_score,
            "notes": self.notes,
            "tags": self.tags,
            "decision": self.decision.value,
            "decision_made_at": self.decision_made_at.isoformat() if self.decision_made_at else None,
            "decision_rationale": self.decision_rationale,
            "approach_executed": self.approach_executed,
            "execution_successful": self.execution_successful,
            "outcome_notes": self.outcome_notes,
            "priority": self.priority,
            "additional_info": self.additional_info,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def calculate_review_time(self) -> Optional[float]:
        """Calculate review time in minutes if both timestamps exist."""
        if self.started_at and self.submitted_at:
            delta = self.submitted_at - self.started_at
            return delta.total_seconds() / 60.0
        return None

    def is_pending_decision(self) -> bool:
        """Check if review is submitted but decision not made."""
        return self.status == ReviewStatus.SUBMITTED and self.decision == ReviewDecision.PENDING
