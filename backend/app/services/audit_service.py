"""
Audit service — appends structured entries to agent_audit_logs.

Called from API endpoints (approvals, actions) and Celery tasks (analysis).

Transaction semantics:
    write_audit_log() adds the entry to the *current* session but does NOT
    call db.commit(). The caller's existing commit() persists it atomically
    with the surrounding business operation. If that commit rolls back, the
    audit entry also rolls back — no orphaned phantom records.

Failure isolation:
    Any exception inside write_audit_log() is caught and logged; it must
    never propagate to break the surrounding business operation.
"""
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AgentAuditLog, AuditEventType

logger = logging.getLogger(__name__)


async def write_audit_log(
    db: AsyncSession,
    event_type: AuditEventType | str,
    actor: str,
    outcome: str,
    incident_id: UUID | None = None,
    action_id: UUID | None = None,
    details: dict | None = None,
) -> None:
    """
    Append an audit entry to the open session.

    Args:
        db:           Active AsyncSession — must be open and not yet committed.
        event_type:   AuditEventType enum value or raw string for extensibility.
        actor:        Who/what triggered the event (email, "system", "celery_worker").
        outcome:      "success" | "failure" | "blocked".
        incident_id:  Related incident UUID (nullable).
        action_id:    Related action UUID (nullable).
        details:      Event-specific structured data dict.
    """
    try:
        # AuditEventType is a str subclass — SQLAlchemy stores the str value directly.
        entry = AgentAuditLog(
            event_type=event_type,
            actor=actor,
            outcome=outcome,
            incident_id=incident_id,
            action_id=action_id,
            details=details or {},
        )
        db.add(entry)
    except Exception as exc:
        # Audit failures must never break the surrounding business operation.
        logger.error(
            "audit_log_write_failed event_type=%s actor=%s error=%s",
            event_type,
            actor,
            type(exc).__name__,
        )
