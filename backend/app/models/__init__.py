"""
Database models using SQLAlchemy 2.0.

Senior Engineering Note:
- Async support with asyncpg
- Declarative base with mapped_column for type safety
- Proper indexes for query performance
- Timestamps on all tables for audit trails
"""
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all database models."""

    type_annotation_map = {
        datetime: DateTime(timezone=True),
    }


class TimestampMixin:
    """Mixin for created_at and updated_at timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


__all__ = ["Base", "TimestampMixin"]


# Import every model module so SQLAlchemy's declarative registry is complete the
# moment `app.models` is imported. Without this, any entry point that imports only
# a subset (e.g. the Celery anomaly-monitor task importing just Incident) hits
# "mapper failed to locate a name 'EngineerReview'/'Hypothesis'" when the Incident
# mapper configures its relationships. Kept at the bottom so Base/TimestampMixin
# are already defined when each module does `from app.models import Base`.
from app.models import (  # noqa: E402,F401
    action,
    audit_log,
    engineer,
    engineer_review,
    hypothesis,
    incident,
    incident_event,
    incident_pattern,
    notification,
    on_call_schedule,
    postmortem,
    user,
)
