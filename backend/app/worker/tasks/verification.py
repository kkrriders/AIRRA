"""
Celery task for post-action verification.

Closes the autonomous agent loop:
    execute_action (HTTP) → verify_action_task (Celery, async) → rollback/escalate

Why a separate Celery task?
    PostActionVerifier.verify_action() sleeps for a configurable stabilization
    window (default 30s, production 120s+) before sampling Prometheus.  Blocking
    the HTTP response for that duration would be unacceptable for an API endpoint.
    The task fires-and-forgets, and the action/incident records are updated when
    it completes.

Rollback policy:
    - DEGRADED + live execution  → executor.rollback() + incident ESCALATED
    - DEGRADED + dry_run         → audit log only (no real infra was changed)
    - PARTIAL_SUCCESS / UNSTABLE → incident ESCALATED (human review)
    - NO_CHANGE + dry_run        → expected (action didn't touch real infra)
    - SUCCESS                    → no further action (incident already RESOLVED)
"""
import asyncio
from datetime import datetime, timezone
from uuid import UUID

from celery import Task
from celery.utils.log import get_task_logger
from sqlalchemy import select

from app.config import settings
from app.core.execution.base import ExecutionResult, ExecutionStatus

# Task time limits derived from the stabilization window so the Celery soft/hard
# limits never fire mid-sleep.  Computed once at import time (settings available).
_STABILIZATION = settings.verification_stabilization_seconds
_TASK_SOFT_LIMIT = _STABILIZATION + 30   # grace for Prometheus query + DB writes
_TASK_HARD_LIMIT = _STABILIZATION + 60
from app.core.execution.kubernetes import get_executor
from app.core.execution.verification import PostActionVerifier, VerificationStatus
from app.database import get_db_context
from app.models.action import Action, ActionStatus
from app.models.audit_log import AuditEventType
from app.models.incident import Incident, IncidentStatus
from app.services.audit_service import write_audit_log
from app.services.prometheus_client import get_prometheus_client
from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)


@celery_app.task(
    bind=True,
    max_retries=1,
    default_retry_delay=30,
    name="app.worker.tasks.verification.verify_action_task",
    acks_late=True,
    queue="celery",
    time_limit=_TASK_HARD_LIMIT,
    soft_time_limit=_TASK_SOFT_LIMIT,
)
def verify_action_task(self: Task, action_id: str, incident_id: str) -> dict:
    """
    Run post-action verification for a completed action.

    Fired by execute_action() after the action succeeds.  Waits for the
    stabilization window then compares before/after Prometheus metrics.
    """
    try:
        return asyncio.run(_run_verification(action_id, incident_id))
    except Exception as exc:
        logger.error(
            f"Verification task failed for action {action_id}: {exc}",
            exc_info=True,
        )
        raise self.retry(exc=exc)


async def _run_verification(action_id: str, incident_id: str) -> dict:
    """Core async verification logic."""
    async with get_db_context() as db:
        # Load the action
        stmt = select(Action).where(Action.id == UUID(action_id))
        result = await db.execute(stmt)
        action = result.scalar_one_or_none()

        if not action:
            logger.warning(f"Verification: action {action_id} not found — skipping")
            return {"status": "skipped", "reason": "action_not_found"}

        if action.status != ActionStatus.SUCCEEDED:
            logger.warning(
                f"Verification: action {action_id} in unexpected status "
                f"'{action.status.value}' — skipping"
            )
            return {"status": "skipped", "reason": f"unexpected_status_{action.status.value}"}

        # Reconstruct a minimal ExecutionResult from stored action data so that
        # PostActionVerifier can derive the pre-action metrics window from
        # executed_at (it fetches Prometheus data from 5 min before that time).
        executed_at = action.executed_at or datetime.now(timezone.utc)
        if executed_at.tzinfo is None:
            executed_at = executed_at.replace(tzinfo=timezone.utc)

        exec_result = ExecutionResult(
            status=ExecutionStatus.SUCCESS,
            message=f"Executed {action.action_type.value} on {action.target_service}",
            started_at=executed_at,
            completed_at=executed_at,
            duration_seconds=float(action.execution_duration_seconds or 0),
            dry_run=(action.execution_mode == "dry_run"),
        )

        # Run verification — blocks for stabilization_window_seconds
        prom_client = get_prometheus_client()
        verifier = PostActionVerifier(
            prometheus_client=prom_client,
            stabilization_window_seconds=settings.verification_stabilization_seconds,
            improvement_threshold=0.20,
        )

        logger.info(
            f"Starting verification for action {action_id} on {action.target_service} "
            f"(waiting {settings.verification_stabilization_seconds}s stabilization)"
        )
        verification = await verifier.verify_action(action.target_service, exec_result)

        logger.info(
            f"Verification complete for action {action_id}: "
            f"status={verification.status.value} recommendation={verification.recommendation}"
        )

        # Persist verification result — JSON column needs full reassignment (not in-place .update())
        action.execution_result = {
            **(action.execution_result or {}),
            "verification": {
                "status": verification.status.value,
                "recommendation": verification.recommendation,
                "improvement_percentage": verification.improvement_percentage,
                "stabilization_seconds": verification.stabilization_seconds,
                "message": verification.message[:500] if verification.message else None,
            },
        }

        is_live = action.execution_mode == "live"

        # --- Rollback path (live execution + degradation) ---
        if verification.recommendation == "rollback" and is_live:
            await _handle_rollback(db, action, exec_result, incident_id)

        # --- Escalation path (any non-success for live execution) ---
        elif verification.status != VerificationStatus.SUCCESS and is_live:
            await _escalate_incident(db, incident_id, action.id, verification.status.value)

        # Write audit entry (committed with everything else by get_db_context())
        await write_audit_log(
            db,
            AuditEventType.VERIFICATION_COMPLETE,
            actor="system",
            outcome="success" if verification.status == VerificationStatus.SUCCESS else "failure",
            incident_id=UUID(incident_id),
            action_id=UUID(action_id),
            details={
                "verification_status": verification.status.value,
                "recommendation": verification.recommendation,
                "execution_mode": action.execution_mode,
                "improvement_percentage": verification.improvement_percentage,
            },
        )

        return {
            "status": verification.status.value,
            "recommendation": verification.recommendation,
            "execution_mode": action.execution_mode,
        }


async def _handle_rollback(
    db,
    action: Action,
    exec_result: ExecutionResult,
    incident_id: str,
) -> None:
    """
    Execute rollback and update action + incident state.

    Called only for live-mode actions whose verification shows DEGRADED status.
    """
    logger.warning(
        f"Metrics degraded after action {action.id} — initiating rollback for {action.target_service}"
    )

    executor = get_executor(action.action_type.value, dry_run=False)
    if executor:
        try:
            rollback_result = await executor.rollback(action.target_service, exec_result)
            logger.info(
                f"Rollback for action {action.id}: {rollback_result.status.value} — {rollback_result.message}"
            )
        except Exception as rb_exc:
            logger.error(f"Rollback executor failed for action {action.id}: {rb_exc}")

    action.status = ActionStatus.ROLLED_BACK

    await _escalate_incident(db, incident_id, action.id, "degraded_auto_rolled_back")

    await write_audit_log(
        db,
        AuditEventType.ACTION_ROLLED_BACK,
        actor="system",
        outcome="failure",
        incident_id=UUID(incident_id),
        action_id=action.id,
        details={
            "reason": "metrics_degraded_post_verification",
            "target_service": action.target_service,
            "action_type": action.action_type.value,
        },
    )


async def _escalate_incident(
    db,
    incident_id: str,
    action_id,
    reason: str,
) -> None:
    """
    Escalate incident to human review when verification detects no improvement.

    Only transitions RESOLVED → ESCALATED.  If the incident is already in a
    terminal or escalated state, the guard prevents an overwrite.
    """
    stmt = select(Incident).where(Incident.id == UUID(incident_id))
    result = await db.execute(stmt)
    incident = result.scalar_one_or_none()

    if incident and incident.status == IncidentStatus.RESOLVED:
        incident.status = IncidentStatus.ESCALATED
        logger.warning(
            f"Incident {incident_id} escalated after verification: reason={reason}"
        )
