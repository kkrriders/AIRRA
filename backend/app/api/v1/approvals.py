"""
Approval workflow endpoints.

Senior Engineering Note:
This implements the human-in-the-loop pattern, critical for production safety.
"""
import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.action import Action, ActionStatus
from app.models.incident import Incident, IncidentStatus
from app.schemas.action import ActionApprove, ActionReject, ActionResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/pending", response_model=list[ActionResponse])
async def get_pending_approvals(
    db: AsyncSession = Depends(get_db),
):
    """
    Get all actions pending approval.

    This would typically be shown in a dashboard for operators.
    """
    stmt = (
        select(Action)
        .where(Action.status == ActionStatus.PENDING_APPROVAL)
        .order_by(Action.created_at)
    )

    result = await db.execute(stmt)
    actions = result.scalars().all()

    return actions


@router.post("/{action_id}/approve", response_model=ActionResponse)
async def approve_action(
    action_id: UUID,
    approval_data: ActionApprove,
    db: AsyncSession = Depends(get_db),
):
    """
    Approve an action for execution.

    Senior Engineering Note:
    This is the critical safety gate. In production, you'd:
    - Verify user permissions (RBAC)
    - Log approval for audit trail
    - Send notifications
    - Update ServiceNow ticket
    """
    stmt = select(Action).where(Action.id == action_id)
    result = await db.execute(stmt)
    action = result.scalar_one_or_none()

    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    if action.status != ActionStatus.PENDING_APPROVAL:
        raise HTTPException(
            status_code=400,
            detail=f"Action is not pending approval (current status: {action.status.value})",
        )

    # Update action
    action.status = ActionStatus.APPROVED
    action.approved_by = approval_data.approved_by
    action.approved_at = datetime.utcnow()
    action.execution_mode = approval_data.execution_mode

    # Update incident status
    stmt = select(Incident).where(Incident.id == action.incident_id)
    result = await db.execute(stmt)
    incident = result.scalar_one_or_none()

    if incident:
        incident.status = IncidentStatus.APPROVED

    await db.commit()
    await db.refresh(action)

    logger.info(
        f"Action {action_id} approved by {approval_data.approved_by}",
        extra={
            "action_id": str(action_id),
            "approved_by": approval_data.approved_by,
            "execution_mode": approval_data.execution_mode,
        },
    )

    return action


@router.post("/{action_id}/reject", response_model=ActionResponse)
async def reject_action(
    action_id: UUID,
    rejection_data: ActionReject,
    db: AsyncSession = Depends(get_db),
):
    """
    Reject an action.

    Senior Engineering Note:
    Rejection feedback is valuable for:
    - Improving hypothesis generation
    - Calibrating confidence scores
    - Training better models
    """
    stmt = select(Action).where(Action.id == action_id)
    result = await db.execute(stmt)
    action = result.scalar_one_or_none()

    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    if action.status != ActionStatus.PENDING_APPROVAL:
        raise HTTPException(
            status_code=400,
            detail=f"Action is not pending approval (current status: {action.status.value})",
        )

    # Update action
    action.status = ActionStatus.REJECTED
    action.rejection_reason = rejection_data.rejection_reason

    # Update incident - escalate to human
    stmt = select(Incident).where(Incident.id == action.incident_id)
    result = await db.execute(stmt)
    incident = result.scalar_one_or_none()

    if incident:
        incident.status = IncidentStatus.ESCALATED

    await db.commit()
    await db.refresh(action)

    logger.info(
        f"Action {action_id} rejected by {rejection_data.rejected_by}",
        extra={
            "action_id": str(action_id),
            "rejected_by": rejection_data.rejected_by,
            "reason": rejection_data.rejection_reason,
        },
    )

    return action
