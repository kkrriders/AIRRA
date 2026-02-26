"""
Incident model representing detected issues requiring investigation.

Senior Engineering Note:
- JSONB for flexible metadata storage
- Enum for strict status management
- Foreign key relationships with proper cascading
- Indexes on frequently queried columns
"""
import enum
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from sqlalchemy import JSON, Index, String, Text, Enum as SQLEnum, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.hypothesis import Hypothesis
    from app.models.action import Action
    from app.models.engineer_review import EngineerReview
    from app.models.engineer import Engineer
    from app.models.incident_event import IncidentEvent


class IncidentStatus(str, enum.Enum):
    """Incident lifecycle states."""

    DETECTED = "detected"  # Initial detection
    ANALYZING = "analyzing"  # Hypothesis generation in progress
    PENDING_APPROVAL = "pending_approval"  # Awaiting human decision
    APPROVED = "approved"  # Action approved, ready for execution
    EXECUTING = "executing"  # Action being executed
    RESOLVED = "resolved"  # Successfully resolved
    FAILED = "failed"  # Resolution failed
    ESCALATED = "escalated"  # Escalated to human


class IncidentSeverity(str, enum.Enum):
    """Incident severity levels."""

    CRITICAL = "critical"  # P1: Service down
    HIGH = "high"  # P2: Major functionality impaired
    MEDIUM = "medium"  # P3: Minor functionality impaired
    LOW = "low"  # P4: Cosmetic or minor issues


class Incident(Base, TimestampMixin):
    """
    Central incident entity tracking the full lifecycle.

    An incident represents a detected anomaly or issue that requires investigation
    and potential remediation. It aggregates hypotheses, actions, and feedback.
    """

    __tablename__ = "incidents"

    # Primary key
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # Core attributes
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[IncidentStatus] = mapped_column(
        SQLEnum(IncidentStatus),
        nullable=False,
        default=IncidentStatus.DETECTED,
        index=True,
    )
    severity: Mapped[IncidentSeverity] = mapped_column(
        SQLEnum(IncidentSeverity),
        nullable=False,
        index=True,
    )

    # Service context
    affected_service: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    affected_components: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    # Detection metadata
    detected_at: Mapped[datetime] = mapped_column(nullable=False, index=True)
    detection_source: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="prometheus",
    )

    # Assignment tracking
    assigned_engineer_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("engineers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Engineer currently assigned to resolve this incident",
    )

    # Resolution tracking
    resolved_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    resolution_time_seconds: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Time to resolution in seconds",
    )
    resolution_summary: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Summary of how incident was resolved",
    )

    # Flexible metadata storage
    metrics_snapshot: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Snapshot of metrics at detection time",
    )
    context: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Additional context (topology, recent changes, etc.)",
    )

    # Relationships
    hypotheses: Mapped[list["Hypothesis"]] = relationship(
        "Hypothesis",
        back_populates="incident",
        cascade="all, delete-orphan",
        order_by="desc(Hypothesis.confidence_score)",
    )
    actions: Mapped[list["Action"]] = relationship(
        "Action",
        back_populates="incident",
        cascade="all, delete-orphan",
        order_by="Action.created_at",
    )
    engineer_reviews: Mapped[list["EngineerReview"]] = relationship(
        "EngineerReview",
        back_populates="incident",
        cascade="all, delete-orphan",
        order_by="desc(EngineerReview.assigned_at)",
    )
    events: Mapped[list["IncidentEvent"]] = relationship(
        "IncidentEvent",
        back_populates="incident",
        cascade="all, delete-orphan",
        order_by="IncidentEvent.created_at",
    )
    assigned_engineer: Mapped[Optional["Engineer"]] = relationship(
        "Engineer",
        foreign_keys=[assigned_engineer_id],
        lazy="joined",
    )

    # Indexes for common queries
    __table_args__ = (
        Index("idx_incident_status_severity", "status", "severity"),
        Index("idx_incident_detected_at", "detected_at"),
        Index("idx_incident_service_status", "affected_service", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<Incident(id={self.id}, "
            f"service={self.affected_service}, "
            f"status={self.status.value}, "
            f"severity={self.severity.value})>"
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "id": str(self.id),
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "severity": self.severity.value,
            "affected_service": self.affected_service,
            "affected_components": self.affected_components,
            "detected_at": self.detected_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolution_time_seconds": self.resolution_time_seconds,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
