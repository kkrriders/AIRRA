"""Action API endpoints."""
import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.action import Action, ActionStatus
from app.models.incident import Incident, IncidentStatus
from app.schemas.action import ActionResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=list[ActionResponse])
async def list_actions(
    skip: int = 0,
    limit: int = 100,
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


@router.post("/{action_id}/execute", response_model=ActionResponse)
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

    # Update status
    action.status = ActionStatus.EXECUTING
    await db.commit()

    try:
        # Simulate execution
        execution_start = datetime.utcnow()

        # In dry-run mode, we just log what would happen
        if action.execution_mode == "dry_run":
            execution_result = {
                "mode": "dry_run",
                "message": f"Would execute {action.action_type.value} on {action.target_service}",
                "parameters": action.parameters,
                "simulated": True,
            }
            success = True
        else:
            # In live mode, execute via appropriate executor
            # This is where you'd integrate with Kubernetes, AWS, etc.
            raise NotImplementedError("Live execution not implemented in MVP")

        execution_end = datetime.utcnow()
        duration_seconds = int((execution_end - execution_start).total_seconds())

        # Update action with result
        action.status = ActionStatus.SUCCEEDED if success else ActionStatus.FAILED
        action.executed_at = execution_start
        action.execution_duration_seconds = duration_seconds
        action.execution_result = execution_result

        # Update incident status
        stmt = select(Incident).where(Incident.id == action.incident_id)
        result = await db.execute(stmt)
        incident = result.scalar_one_or_none()

        if incident and success:
            incident.status = IncidentStatus.RESOLVED
            incident.resolved_at = datetime.utcnow()
            incident.resolution_time_seconds = int(
                (incident.resolved_at - incident.detected_at).total_seconds()
            )

        await db.commit()
        await db.refresh(action)

        logger.info(
            f"Executed action {action_id} with status {action.status.value}",
            extra={"action_id": str(action_id), "execution_mode": action.execution_mode},
        )

        return action

    except Exception as e:
        logger.error(f"Action execution failed: {str(e)}", exc_info=True)
        action.status = ActionStatus.FAILED
        action.execution_result = {"error": str(e)}
        await db.commit()
        raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)}")
