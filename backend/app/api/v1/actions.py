"""Action API endpoints."""
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.rate_limit import write_rate_limit
from app.core.execution.base import ExecutionStatus
from app.core.execution.kubernetes import get_executor
from app.database import get_db
from app.models.action import Action, ActionStatus
from app.models.audit_log import AuditEventType
from app.models.hypothesis import Hypothesis
from app.models.incident import Incident, IncidentStatus
from app.schemas.action import ActionResponse
from app.services.audit_service import write_audit_log
from app.services.learning_engine import IncidentOutcome, get_learning_engine

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=list[ActionResponse])
async def list_actions(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List all actions."""
    stmt = select(Action).order_by(Action.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{action_id}", response_model=ActionResponse)
async def get_action(
    action_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get action by ID."""
    stmt = select(Action).where(Action.id == action_id)
    result = await db.execute(stmt)
    action = result.scalar_one_or_none()

    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    return action


@router.get("/incident/{incident_id}", response_model=list[ActionResponse])
async def get_incident_actions(
    incident_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get all actions for an incident."""
    stmt = select(Action).where(Action.incident_id == incident_id).order_by(Action.created_at)
    result = await db.execute(stmt)
    actions = result.scalars().all()

    return actions


@router.post("/{action_id}/execute", response_model=ActionResponse, dependencies=[Depends(write_rate_limit)])
async def execute_action(
    action_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Execute an approved action.

    Senior Engineering Note:
    In production, this would:
    1. Validate action is approved
    2. Execute via appropriate executor (K8s, AWS, etc.)
    3. Track execution result
    4. Update incident status

    For MVP, we simulate execution in dry-run mode.
    """
    stmt = select(Action).where(Action.id == action_id)
    result = await db.execute(stmt)
    action = result.scalar_one_or_none()

    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    if action.status != ActionStatus.APPROVED:
        raise HTTPException(
            status_code=400,
            detail=f"Action must be approved first (current status: {action.status.value})",
        )

    # NEW-12 fix: fetch incident before the first commit and guard that it is
    # still APPROVED. Transition it to EXECUTING atomically with the action so
    # the final RESOLVED guard can use a single expected status and concurrent
    # lifecycle changes (escalation, failure) are detected before execution starts.
    incident_stmt = select(Incident).where(Incident.id == action.incident_id)
    incident_result = await db.execute(incident_stmt)
    incident = incident_result.scalar_one_or_none()

    if incident:
        if incident.status != IncidentStatus.APPROVED:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot execute action: incident is in '{incident.status.value}' status "
                    "(expected 'approved')"
                ),
            )
        incident.status = IncidentStatus.EXECUTING

    # Update action status
    action.status = ActionStatus.EXECUTING
    await write_audit_log(
        db,
        AuditEventType.ACTION_EXECUTE_STARTED,
        actor="operator",
        outcome="success",
        incident_id=action.incident_id,
        action_id=action.id,
        details={
            "action_type": action.action_type.value,
            "target_service": action.target_service,
            "execution_mode": action.execution_mode,
            "risk_level": action.risk_level.value,
        },
    )
    await db.commit()

    try:
        execution_start = datetime.now(timezone.utc)

        # Dispatch to the typed executor for this action type.
        # The executor handles both dry_run and live modes internally,
        # including K8s client loading, resource name validation, and rollback.
        is_dry_run = action.execution_mode == "dry_run"
        executor = get_executor(action.action_type.value, dry_run=is_dry_run)

        if executor:
            exec_result = await executor.execute(action.target_service, action.parameters)
            success = exec_result.status == ExecutionStatus.SUCCESS
            execution_result = {
                "status": exec_result.status.value,
                "message": exec_result.message,
                "details": exec_result.details,
                "dry_run": exec_result.dry_run,
            }
        elif is_dry_run:
            # Unregistered action type — inline fallback for dry_run only
            execution_result = {
                "mode": "dry_run",
                "message": f"Would execute {action.action_type.value} on {action.target_service}",
                "parameters": action.parameters,
                "simulated": True,
            }
            success = True
        else:
            raise NotImplementedError(
                f"Live execution not implemented for action type: {action.action_type.value}"
            )

        execution_end = datetime.now(timezone.utc)
        duration_seconds = int((execution_end - execution_start).total_seconds())

        # Update action with result
        action.status = ActionStatus.SUCCEEDED if success else ActionStatus.FAILED
        action.executed_at = execution_start
        action.execution_duration_seconds = duration_seconds
        action.execution_result = execution_result

        # NEW-12 fix: re-fetch incident to detect concurrent lifecycle changes
        # (e.g. escalation by lifecycle manager between EXECUTING commit and now).
        refetch_stmt = select(Incident).where(Incident.id == action.incident_id)
        refetch_result = await db.execute(refetch_stmt)
        incident = refetch_result.scalar_one_or_none()

        if incident and success:
            if incident.status != IncidentStatus.EXECUTING:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Cannot resolve incident: current status is "
                        f"'{incident.status.value}' (expected 'executing')"
                    ),
                )
            incident.status = IncidentStatus.RESOLVED
            incident.resolved_at = datetime.now(timezone.utc)
            # Normalize detected_at to UTC-aware before subtraction.
            # SQLite (used in tests) returns naive datetimes; PostgreSQL with
            # TIMESTAMP WITH TIME ZONE returns aware ones. Treating naive as UTC
            # is correct here because all writes use datetime.now(timezone.utc).
            detected_at = incident.detected_at
            if detected_at.tzinfo is None:
                detected_at = detected_at.replace(tzinfo=timezone.utc)
            incident.resolution_time_seconds = int(
                (incident.resolved_at - detected_at).total_seconds()
            )
            incident.resolution_summary = f"Resolved via action: {action.name}"

        await write_audit_log(
            db,
            AuditEventType.ACTION_EXECUTE_SUCCEEDED,
            actor="operator",
            outcome="success",
            incident_id=action.incident_id,
            action_id=action.id,
            details={
                "action_type": action.action_type.value,
                "target_service": action.target_service,
                "execution_mode": action.execution_mode,
                "duration_seconds": duration_seconds,
            },
        )

        await db.commit()
        await db.refresh(action)

        logger.info(
            f"Executed action {action_id} with status {action.status.value}",
            extra={"action_id": str(action_id), "execution_mode": action.execution_mode},
        )

        # Feed outcome back to the learning engine so patterns improve over time.
        # This is what makes the system a *learning* agent rather than a stateless
        # LLM wrapper — the outcome of every execution is recorded and used to
        # adjust hypothesis confidence for future similar incidents.
        if incident and success:
            try:
                top_hypothesis_stmt = (
                    select(Hypothesis)
                    .where(Hypothesis.incident_id == incident.id)
                    .order_by(Hypothesis.rank)
                    .limit(1)
                )
                top_hyp_result = await db.execute(top_hypothesis_stmt)
                top_hypothesis = top_hyp_result.scalar_one_or_none()

                resolution_minutes = (
                    incident.resolution_time_seconds // 60
                    if incident.resolution_time_seconds
                    else None
                )

                outcome = IncidentOutcome(
                    incident_id=incident.id,
                    hypothesis_id=top_hypothesis.id if top_hypothesis else None,
                    hypothesis_correct=True,
                    action_id=action.id,
                    action_effective=True,
                    time_to_resolution_minutes=resolution_minutes,
                    human_override=False,
                    resolution_notes=f"Resolved via {action.action_type.value} in {action.execution_mode} mode",
                )
                engine = get_learning_engine()
                await engine.capture_outcome(outcome)
            except Exception as learn_err:
                # Learning failures must never break the execution response.
                logger.warning(
                    f"Learning engine update failed for action {action_id}: {learn_err}"
                )

        # Queue post-action verification as a background Celery task so the
        # HTTP response returns immediately.  The task waits for the
        # stabilization window, compares before/after Prometheus metrics, and
        # auto-escalates (or rolls back for live mode) if the action degraded
        # the service.
        if success:
            try:
                # deferred to avoid circular import
                from app.worker.tasks.verification import verify_action_task
                verify_action_task.delay(str(action_id), str(action.incident_id))
                logger.info(f"Verification task queued for action {action_id}")
            except Exception as v_err:
                logger.warning(f"Failed to queue verification task for action {action_id}: {v_err}")

        return action

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Action execution failed: {str(e)}", exc_info=True)
        action.status = ActionStatus.FAILED
        # NEW-7 fix: store error type rather than raw exception string so
        # internal details aren't leaked through the ActionResponse JSON.
        action.execution_result = {"error": "execution_failed", "error_type": type(e).__name__}
        await write_audit_log(
            db,
            AuditEventType.ACTION_EXECUTE_FAILED,
            actor="operator",
            outcome="failure",
            incident_id=action.incident_id,
            action_id=action.id,
            details={
                "action_type": action.action_type.value,
                "target_service": action.target_service,
                "error_type": type(e).__name__,
            },
        )
        await db.commit()
        raise HTTPException(status_code=500, detail="Action execution failed")
