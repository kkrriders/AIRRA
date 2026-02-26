"""
Incident Event Model - Tracks all events in incident lifecycle.

Used for:
- Auto-generating timeline in post-incident reviews
- Audit trail
- Debugging incident progression

Every significant action creates an event:
- Incident detected
- Hypothesis generated
- Engineer assigned
- Action approved/rejected
- Action executed
- Incident resolved
"""
import enum
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, Text, JSON, Index, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.incident import Incident


class IncidentEventType(str, enum.Enum):
    """Types of events in incident lifecycle."""

    # Detection phase
    DETECTED = "detected"

    # Analysis phase
    ANALYZING_STARTED = "analyzing_started"
    HYPOTHESES_GENERATED = "hypotheses_generated"
    ANALYSIS_FAILED = "analysis_failed"

    # Assignment phase
    ENGINEER_ASSIGNED = "engineer_assigned"
    ENGINEER_UNASSIGNED = "engineer_unassigned"
    ENGINEER_NOTIFIED = "engineer_notified"

    # Approval phase
    PENDING_APPROVAL = "pending_approval"
    ACTION_APPROVED = "action_approved"
    ACTION_REJECTED = "action_rejected"

    # Execution phase
    ACTION_STARTED = "action_started"
    ACTION_COMPLETED = "action_completed"
    ACTION_FAILED = "action_failed"

    # Verification phase
    VERIFICATION_STARTED = "verification_started"
    VERIFICATION_PASSED = "verification_passed"
    VERIFICATION_FAILED = "verification_failed"

    # Resolution phase
    INCIDENT_RESOLVED = "incident_resolved"
    INCIDENT_ESCALATED = "incident_escalated"

    # Other
    COMMENT_ADDED = "comment_added"
    STATUS_CHANGED = "status_changed"


class IncidentEvent(Base, TimestampMixin):
    """
    Event log for incident timeline.

    Each event represents a significant action in the incident lifecycle.
    Used to auto-generate timeline in post-incident reviews.
    """

    __tablename__ = "incident_events"

    # Primary key
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # Foreign key to incident
    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Event details
    event_type: Mapped[IncidentEventType] = mapped_column(
        SQLEnum(IncidentEventType),
        nullable=False,
        index=True,
    )

    # Human-readable description
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Human-readable event description for timeline"
    )

    # Actor (who/what triggered this event)
    actor: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Who triggered this event: 'system', 'alice@company.com', 'airra-bot'"
    )

    # Additional metadata (flexible JSON for event-specific data)
    event_metadata: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Event-specific data (hypothesis details, action params, etc.)"
    )

    # Relationships
    incident: Mapped["Incident"] = relationship(
        "Incident",
        back_populates="events"
    )

    # Indexes for timeline queries (ordered by created_at)
    __table_args__ = (
        Index("idx_incident_events_timeline", "incident_id", "created_at"),
        Index("idx_incident_events_type", "incident_id", "event_type"),
    )

    def __repr__(self) -> str:
        return (
            f"<IncidentEvent(incident={self.incident_id}, "
            f"type={self.event_type.value}, "
            f"time={self.created_at})>"
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "id": str(self.id),
            "incident_id": str(self.incident_id),
            "event_type": self.event_type.value,
            "description": self.description,
            "actor": self.actor,
            "metadata": self.event_metadata,
            "timestamp": self.created_at.isoformat(),
        }
