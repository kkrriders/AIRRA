"""
On-call schedule model for tracking engineer availability by time and service.

Senior Engineering Note:
- Supports rotating on-call schedules
- Team/service-specific assignments
- Timezone-aware scheduling
- Integration with engineer availability
"""
import enum
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    ForeignKey,
    Index,
    String,
    Enum as SQLEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.engineer import Engineer


class OnCallPriority(str, enum.Enum):
    """On-call priority level for escalation chain."""

    PRIMARY = "primary"  # First responder
    SECONDARY = "secondary"  # Backup if primary doesn't respond
    TERTIARY = "tertiary"  # Last resort escalation


class OnCallSchedule(Base, TimestampMixin):
    """
    On-call schedule assignments linking engineers to services/teams during specific time periods.

    Supports:
    - Rotating on-call schedules
    - Service-specific assignments
    - Escalation chains (primary, secondary, tertiary)
    - Timezone-aware scheduling
    """

    __tablename__ = "on_call_schedules"

    # Primary key
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # Foreign key
    engineer_id: Mapped[UUID] = mapped_column(
        ForeignKey("engineers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Schedule details
    service: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Specific service (e.g., 'payment-service'). NULL = all services",
    )
    team: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        comment="Team responsibility (e.g., 'backend', 'platform'). NULL = all teams",
    )

    # Time range (timezone-aware)
    start_time: Mapped[datetime] = mapped_column(
        nullable=False,
        index=True,
        comment="On-call shift start time (UTC)",
    )
    end_time: Mapped[datetime] = mapped_column(
        nullable=False,
        index=True,
        comment="On-call shift end time (UTC)",
    )

    # Priority for escalation
    priority: Mapped[OnCallPriority] = mapped_column(
        SQLEnum(OnCallPriority),
        nullable=False,
        default=OnCallPriority.PRIMARY,
        index=True,
        comment="Escalation priority level",
    )

    # Schedule metadata
    schedule_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Human-readable schedule name (e.g., 'Week 1 Rotation')",
    )
    rotation_week: Mapped[Optional[int]] = mapped_column(
        nullable=True,
        comment="Week number in rotation cycle (for recurring schedules)",
    )

    # Status
    is_active: Mapped[bool] = mapped_column(
        nullable=False,
        default=True,
        index=True,
        comment="Whether this schedule is currently active",
    )

    # Relationships
    engineer: Mapped["Engineer"] = relationship(
        "Engineer",
        back_populates="on_call_schedules",
        lazy="joined",
    )

    # Indexes for common queries
    __table_args__ = (
        # Find who's on-call now
        Index("idx_oncall_active_time", "is_active", "start_time", "end_time"),
        # Find on-call for specific service
        Index("idx_oncall_service_time", "service", "start_time", "end_time"),
        # Find on-call engineer
        Index("idx_oncall_engineer_time", "engineer_id", "start_time", "end_time"),
        # Escalation priority lookup
        Index("idx_oncall_priority", "priority", "is_active", "start_time"),
    )

    def __repr__(self) -> str:
        return (
            f"<OnCallSchedule(id={self.id}, "
            f"engineer_id={self.engineer_id}, "
            f"service={self.service}, "
            f"priority={self.priority.value}, "
            f"start={self.start_time}, "
            f"end={self.end_time})>"
        )

    def is_currently_on_call(self, now: Optional[datetime] = None) -> bool:
        """Check if this schedule is currently active."""
        if not self.is_active:
            return False

        check_time = now or datetime.now(timezone.utc)
        return self.start_time <= check_time <= self.end_time

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "id": str(self.id),
            "engineer_id": str(self.engineer_id),
            "service": self.service,
            "team": self.team,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "priority": self.priority.value,
            "schedule_name": self.schedule_name,
            "rotation_week": self.rotation_week,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
