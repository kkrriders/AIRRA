"""
Agent Audit Log model — immutable record of every agent decision.

Every significant agent action (approve, reject, execute, policy block)
is written here for traceability and forensics (OWASP LLM08: Excessive Agency).

Design decisions:
- incident_id / action_id are SET NULL on-delete, not CASCADE — audit entries
  must outlive the referenced rows so the audit trail remains queryable even
  after incidents are cleaned up.
- event_type stored as String(64) not SQLAlchemy Enum — avoids migrations
  when new event types are added in the future.
- details is a JSON blob for event-specific data without schema churn.
"""
import enum
from uuid import UUID, uuid4

from sqlalchemy import JSON, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, TimestampMixin


class AuditEventType(str, enum.Enum):
    """Well-known event types written by the agent."""

    ACTION_APPROVED = "action_approved"
    ACTION_REJECTED = "action_rejected"
    ACTION_EXECUTE_STARTED = "action_execute_started"
    ACTION_EXECUTE_SUCCEEDED = "action_execute_succeeded"
    ACTION_EXECUTE_FAILED = "action_execute_failed"
    ACTION_ROLLED_BACK = "action_rolled_back"
    POLICY_BLOCKED = "policy_blocked"
    ANALYSIS_COMPLETE = "analysis_complete"
    VERIFICATION_COMPLETE = "verification_complete"


class AgentAuditLog(Base, TimestampMixin):
    """
    Immutable structured record of what the agent did and why.

    Written at every approval, rejection, execution, and policy veto so
    operators can answer "why did the agent do X to Y at time Z?" without
    grepping unstructured logs.
    """

    __tablename__ = "agent_audit_logs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    event_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="AuditEventType value or custom string for forward-compatible extension",
    )
    actor: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Who triggered the event: user email, 'system', or 'celery_worker'",
    )
    outcome: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="success | failure | blocked",
    )

    # Nullable FKs — SET NULL preserves audit entries after row deletion
    incident_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("incidents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("actions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    details: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Event-specific structured data (action_type, risk_level, veto_reason, etc.)",
    )

    __table_args__ = (
        Index("idx_audit_event_actor", "event_type", "actor"),
        Index("idx_audit_incident_event", "incident_id", "event_type"),
    )
