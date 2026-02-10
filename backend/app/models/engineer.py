"""
Engineer model representing human experts who review AI hypotheses.

Senior Engineering Note:
- Tracks engineer availability and workload for auto-assignment
- JSON for flexible expertise and metadata
- Relationship with review records for history tracking
"""
import enum
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Integer, String, Index, JSON, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.engineer_review import EngineerReview


class EngineerStatus(str, enum.Enum):
    """Engineer availability status."""

    ACTIVE = "active"  # Available for assignments
    BUSY = "busy"  # At capacity, no new assignments
    OFFLINE = "offline"  # Not available
    ON_LEAVE = "on_leave"  # Temporarily unavailable


class Engineer(Base, TimestampMixin):
    """
    Engineer entity representing human experts who validate AI analysis.

    Engineers can be assigned incidents for review, provide alternative
    hypotheses, and suggest different approaches when AI confidence is low.
    """

    __tablename__ = "engineers"

    # Primary key
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # Core attributes
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
    )

    # Expertise and specialization
    expertise: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="Areas of expertise (e.g., ['kubernetes', 'databases', 'networking'])",
    )
    department: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Availability tracking
    status: Mapped[EngineerStatus] = mapped_column(
        SQLEnum(EngineerStatus),
        nullable=False,
        default=EngineerStatus.ACTIVE,
        index=True,
    )
    is_available: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="Quick availability flag for assignment queries",
    )
    max_concurrent_reviews: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
        comment="Maximum number of concurrent review assignments",
    )
    current_review_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Current number of active reviews",
    )

    # Performance metrics
    total_reviews_completed: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Lifetime review count",
    )
    average_review_time_minutes: Mapped[Optional[float]] = mapped_column(
        nullable=True,
        comment="Average time to complete a review",
    )

    # Contact and additional info
    slack_handle: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    additional_info: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Additional metadata (timezone, preferences, etc.)",
    )

    # Relationships
    reviews: Mapped[list["EngineerReview"]] = relationship(
        "EngineerReview",
        back_populates="engineer",
        cascade="all, delete-orphan",
        order_by="desc(EngineerReview.assigned_at)",
    )

    # Indexes for common queries
    __table_args__ = (
        Index("idx_engineer_available", "is_available", "status"),
        Index("idx_engineer_workload", "current_review_count", "is_available"),
    )

    def __repr__(self) -> str:
        return (
            f"<Engineer(id={self.id}, "
            f"name={self.name}, "
            f"status={self.status.value}, "
            f"reviews={self.current_review_count}/{self.max_concurrent_reviews})>"
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "id": str(self.id),
            "name": self.name,
            "email": self.email,
            "expertise": self.expertise,
            "department": self.department,
            "status": self.status.value,
            "is_available": self.is_available,
            "max_concurrent_reviews": self.max_concurrent_reviews,
            "current_review_count": self.current_review_count,
            "total_reviews_completed": self.total_reviews_completed,
            "average_review_time_minutes": self.average_review_time_minutes,
            "slack_handle": self.slack_handle,
            "phone": self.phone,
            "additional_info": self.additional_info,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def is_at_capacity(self) -> bool:
        """Check if engineer is at review capacity."""
        return self.current_review_count >= self.max_concurrent_reviews

    def can_accept_review(self) -> bool:
        """Check if engineer can accept a new review assignment."""
        return (
            self.is_available
            and self.status == EngineerStatus.ACTIVE
            and not self.is_at_capacity()
        )
