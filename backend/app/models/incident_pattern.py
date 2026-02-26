"""
IncidentPattern model for persisting learned patterns across restarts.

Serves as the PostgreSQL source-of-truth for the LearningEngine's in-memory cache.
"""
from uuid import uuid4

from sqlalchemy import JSON, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, TimestampMixin


class IncidentPattern(Base, TimestampMixin):
    """
    Persisted pattern learned from incident outcomes.

    pattern_id is the semantic key: "{service}:{category}" (e.g. "payment-service:memory_leak").
    The LearningEngine keeps an in-memory dict as L1 cache and upserts here after every update.
    """

    __tablename__ = "incident_patterns"

    # Native PostgreSQL UUID — consistent with Incident, Hypothesis, Action models (S3 fix)
    id: Mapped[uuid4] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    # UniqueConstraint in __table_args__ creates the unique index — no need for
    # unique=True here, which would create a second redundant unique index (S4 fix)
    pattern_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    signal_indicators: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    confidence_adjustment: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    success_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    __table_args__ = (
        # Single unique constraint on pattern_id — PostgreSQL implements this as
        # one unique index. Adding unique=True on the column would create a second
        # redundant index, wasting storage and write overhead.
        UniqueConstraint("pattern_id", name="uq_incident_patterns_pattern_id"),
        Index("ix_incident_patterns_category", "category"),
    )
