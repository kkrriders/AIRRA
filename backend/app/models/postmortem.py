"""
Postmortem (Post-Incident Review) Model.

Captures learnings and action items after incident resolution.

Industry terminology:
- ServiceNow: "Post-Incident Review (PIR)"
- Google SRE: "Postmortem"
- AWS: "Correction of Error (COE)"
- PagerDuty: "Post-Incident Analysis"

All mean the same thing: Document what happened, why, and how to prevent it.
"""
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, Text, JSON, Integer, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.incident import Incident
    from app.models.engineer import Engineer


class Postmortem(Base, TimestampMixin):
    """
    Post-Incident Review documentation.

    Created after incident resolution to capture:
    - What happened (timeline)
    - Why it happened (root cause)
    - What we learned
    - How to prevent it
    """

    __tablename__ = "postmortems"

    # Primary key
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # Link to incident (one-to-one relationship)
    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )

    # Who wrote this postmortem
    author_id: Mapped[UUID] = mapped_column(
        ForeignKey("engineers.id", ondelete="SET NULL"),
        nullable=True,
    )

    # === Root Cause Analysis ===

    # What actually caused the incident (ground truth)
    actual_root_cause: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="The true root cause (may differ from AI hypothesis)"
    )

    # Contributing factors
    contributing_factors: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="Additional factors that contributed to the incident"
    )

    # Why detection was delayed (if applicable)
    detection_delay_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Why we didn't catch this earlier"
    )

    # === Impact Assessment ===

    # Duration in minutes
    duration_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Total incident duration from detection to resolution"
    )

    # Number of users affected
    users_affected: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Estimated number of impacted users"
    )

    # Revenue impact (if applicable)
    revenue_impact_usd: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        comment="Estimated revenue loss in USD"
    )

    # === Learnings (Blameless Culture) ===

    # What went well during incident response
    what_went_well: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="Positive aspects to celebrate and reinforce"
    )

    # What could be improved
    what_went_wrong: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="Areas for improvement (systems, not people)"
    )

    # Lessons learned
    lessons_learned: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="Key takeaways for the team"
    )

    # === Action Items ===

    # Follow-up actions to prevent recurrence
    action_items: Mapped[list[dict]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="""
        List of action items with structure:
        [
            {
                "description": "Add memory limit to payment-service pods",
                "owner": "alice@company.com",
                "due_date": "2026-02-28",
                "priority": "high",
                "status": "open"
            }
        ]
        """
    )

    # Prevention measures to implement
    prevention_measures: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="Specific changes to prevent this incident type"
    )

    # Detection improvements
    detection_improvements: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="How to detect this faster next time"
    )

    # Response improvements
    response_improvements: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="How to respond more effectively"
    )

    # === AI Hypothesis Evaluation ===

    # Was the AI hypothesis correct?
    ai_hypothesis_correct: Mapped[Optional[bool]] = mapped_column(
        nullable=True,
        comment="Did the AI correctly identify the root cause?"
    )

    # AI hypothesis evaluation notes
    ai_evaluation_notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Feedback on AI performance for learning"
    )

    # === Metadata ===

    # Additional notes (free-form)
    additional_notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Any other relevant information"
    )

    # Publication status
    published: Mapped[bool] = mapped_column(
        default=False,
        comment="Whether this postmortem is shared with the team"
    )

    # Publication date
    published_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
        comment="When this postmortem was published"
    )

    # Relationships
    incident: Mapped["Incident"] = relationship(
        "Incident",
        backref="postmortem"
    )

    author: Mapped[Optional["Engineer"]] = relationship(
        "Engineer",
        foreign_keys=[author_id]
    )

    def __repr__(self) -> str:
        return (
            f"<Postmortem(incident={self.incident_id}, "
            f"author={self.author_id}, "
            f"published={self.published})>"
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "id": str(self.id),
            "incident_id": str(self.incident_id),
            "author_id": str(self.author_id) if self.author_id else None,
            "actual_root_cause": self.actual_root_cause,
            "contributing_factors": self.contributing_factors,
            "detection_delay_reason": self.detection_delay_reason,
            "duration_minutes": self.duration_minutes,
            "users_affected": self.users_affected,
            "revenue_impact_usd": self.revenue_impact_usd,
            "what_went_well": self.what_went_well,
            "what_went_wrong": self.what_went_wrong,
            "lessons_learned": self.lessons_learned,
            "action_items": self.action_items,
            "prevention_measures": self.prevention_measures,
            "detection_improvements": self.detection_improvements,
            "response_improvements": self.response_improvements,
            "ai_hypothesis_correct": self.ai_hypothesis_correct,
            "ai_evaluation_notes": self.ai_evaluation_notes,
            "additional_notes": self.additional_notes,
            "published": self.published,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def calculate_action_items_completion(self) -> float:
        """Calculate percentage of action items completed."""
        if not self.action_items:
            return 0.0

        completed = sum(1 for item in self.action_items if item.get("status") == "completed")
        return (completed / len(self.action_items)) * 100
