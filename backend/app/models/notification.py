"""
Notification model for tracking engineer notifications and acknowledgements.

Senior Engineering Note:
- Multi-channel support (email, Slack, SMS)
- Acknowledgement tracking for SLA monitoring
- Retry logic for failed notifications
- Secure token generation for email links
"""
import enum
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    ForeignKey,
    Index,
    String,
    Text,
    Integer,
    Enum as SQLEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.engineer import Engineer
    from app.models.incident import Incident


class NotificationChannel(str, enum.Enum):
    """Notification delivery channel."""

    EMAIL = "email"
    SLACK = "slack"
    SMS = "sms"
    WEBHOOK = "webhook"


class NotificationStatus(str, enum.Enum):
    """Notification delivery status."""

    PENDING = "pending"  # Queued for delivery
    SENT = "sent"  # Successfully sent
    DELIVERED = "delivered"  # Confirmed delivered (if supported by channel)
    FAILED = "failed"  # Delivery failed
    ACKNOWLEDGED = "acknowledged"  # Engineer acknowledged receipt


class NotificationPriority(str, enum.Enum):
    """Notification urgency level."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class Notification(Base, TimestampMixin):
    """
    Notification record tracking engineer communications.

    Tracks multi-channel notifications to engineers about incidents,
    including delivery status, acknowledgement, and escalation.
    """

    __tablename__ = "notifications"

    # Primary key
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # Foreign keys
    engineer_id: Mapped[UUID] = mapped_column(
        ForeignKey("engineers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    incident_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="Related incident (NULL for general notifications)",
    )

    # Notification details
    channel: Mapped[NotificationChannel] = mapped_column(
        SQLEnum(NotificationChannel),
        nullable=False,
        index=True,
    )
    status: Mapped[NotificationStatus] = mapped_column(
        SQLEnum(NotificationStatus),
        nullable=False,
        default=NotificationStatus.PENDING,
        index=True,
    )
    priority: Mapped[NotificationPriority] = mapped_column(
        SQLEnum(NotificationPriority),
        nullable=False,
        default=NotificationPriority.NORMAL,
        index=True,
    )

    # Message content
    subject: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="Notification subject/title",
    )
    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Notification message body",
    )

    # Delivery tracking
    recipient_address: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Email address, Slack user ID, phone number, etc.",
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
        index=True,
        comment="When notification was sent",
    )
    delivered_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
        comment="When notification was confirmed delivered",
    )

    # Acknowledgement tracking
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
        index=True,
        comment="When engineer acknowledged the notification",
    )
    acknowledgement_token: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        unique=True,
        index=True,
        comment="Secure token for tracking email link clicks",
    )
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
        comment="When the acknowledgement token expires",
    )

    # Response time SLA tracking
    response_time_seconds: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Time from sent to acknowledged in seconds",
    )
    sla_target_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=300,  # 5 minutes default
        comment="Target response time SLA",
    )
    sla_met: Mapped[Optional[bool]] = mapped_column(
        nullable=True,
        index=True,
        comment="Whether SLA was met (NULL if not yet acknowledged)",
    )

    # Retry logic
    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of delivery retry attempts",
    )
    max_retries: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
        comment="Maximum retry attempts",
    )
    last_error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Last delivery error message",
    )

    # Escalation tracking
    escalated: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        index=True,
        comment="Whether this notification was escalated",
    )
    escalated_to_engineer_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("engineers.id", ondelete="SET NULL"),
        nullable=True,
        comment="Engineer this was escalated to (if escalated)",
    )
    escalated_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
        comment="When escalation occurred",
    )

    # Relationships
    engineer: Mapped["Engineer"] = relationship(
        "Engineer",
        foreign_keys=[engineer_id],
        lazy="joined",
    )
    incident: Mapped[Optional["Incident"]] = relationship(
        "Incident",
        lazy="selectin",
    )

    # Indexes for common queries
    __table_args__ = (
        # Find pending notifications
        Index("idx_notification_pending", "status", "priority", "created_at"),
        # Find by engineer and incident
        Index("idx_notification_engineer_incident", "engineer_id", "incident_id"),
        # Find by acknowledgement token
        Index("idx_notification_token", "acknowledgement_token", "token_expires_at"),
        # SLA monitoring
        Index("idx_notification_sla", "sent_at", "acknowledged_at", "sla_met"),
        # Escalation queries
        Index("idx_notification_escalated", "escalated", "escalated_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Notification(id={self.id}, "
            f"engineer_id={self.engineer_id}, "
            f"channel={self.channel.value}, "
            f"status={self.status.value}, "
            f"priority={self.priority.value})>"
        )

    def calculate_response_time(self) -> Optional[int]:
        """Calculate response time in seconds."""
        if self.sent_at and self.acknowledged_at:
            delta = self.acknowledged_at - self.sent_at
            return int(delta.total_seconds())
        return None

    def check_sla(self) -> Optional[bool]:
        """Check if SLA was met."""
        response_time = self.calculate_response_time()
        if response_time is not None:
            return response_time <= self.sla_target_seconds
        return None

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "id": str(self.id),
            "engineer_id": str(self.engineer_id),
            "incident_id": str(self.incident_id) if self.incident_id else None,
            "channel": self.channel.value,
            "status": self.status.value,
            "priority": self.priority.value,
            "subject": self.subject,
            "message": self.message,
            "recipient_address": self.recipient_address,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "delivered_at": self.delivered_at.isoformat() if self.delivered_at else None,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "response_time_seconds": self.response_time_seconds,
            "sla_target_seconds": self.sla_target_seconds,
            "sla_met": self.sla_met,
            "retry_count": self.retry_count,
            "escalated": self.escalated,
            "escalated_at": self.escalated_at.isoformat() if self.escalated_at else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
