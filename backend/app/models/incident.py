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

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.action import Action
    from app.models.engineer import Engineer
    from app.models.engineer_review import EngineerReview
    from app.models.hypothesis import Hypothesis
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
    assigned_engineer_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("engineers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Engineer currently assigned to resolve this incident",
    )

    # Lifecycle timestamps
    # Set when the incident first enters PENDING_APPROVAL — used as the escalation
    # clock start so that unrelated field updates (metadata, notes) don't reset
    # the SLA window (LOW-6 fix: was using updated_at which resets on any change).
    pending_approval_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Resolution tracking
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)
    resolution_time_seconds: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Time to resolution in seconds",
    )
    resolution_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Summary of how incident was resolved",
    )

    # Semantic embedding for similarity search (pgvector)
    # Populated asynchronously by the embed_incident Celery task after creation.
    # Nullable — incidents created before embeddings were wired will have NULL.
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(384),
        nullable=True,
        comment="384-dim all-MiniLM-L6-v2 embedding for semantic similarity search",
    )

    # RAG retrieval trust score — weights composite similarity during analysis.
    # Higher-trust incidents have more influence on hypothesis generation.
    # Values:
    #   1.0 = human-validated (postmortem with confirmed actual_root_cause)
    #   0.7 = human-approved (action was approved by a human operator)
    #   0.4 = auto-detected (airra_monitor / quick_incident_ui) — default
    #   0.2 = ai_generator (fictional scenarios, excluded from RAG but scored)
    trust_score: Mapped[float] = mapped_column(
        Numeric(precision=3, scale=2),
        nullable=False,
        default=0.4,
        comment="RAG trust: 1.0=human-validated, 0.7=approved, 0.4=auto, 0.2=ai_generated",
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
        # Composite index covers the common query pattern: WHERE detection_source = X AND status = Y
        Index("idx_incident_detection_source_status", "detection_source", "status"),
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
