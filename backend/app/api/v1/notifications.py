"""
Notification API endpoints.

Senior Engineering Note:
- Send incident notifications to engineers
- Track acknowledgements via secure tokens
- SLA monitoring and reporting
- Multi-channel support
"""
import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import verify_api_key
from app.database import get_db
from app.models.notification import Notification, NotificationStatus
from app.schemas.notification import (
    NotificationCreate,
    NotificationUpdate,
    NotificationResponse,
    NotificationAcknowledge,
    NotificationSendRequest,
    NotificationStatsResponse,
    NotificationListResponse,
)
from app.services.notification_service import notification_service
from app.services.token_service import token_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/send", response_model=NotificationResponse, status_code=201)
async def send_notification(
    request: NotificationSendRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """
    Send an incident notification to an engineer.

    Automatically generates secure token for acknowledgement tracking.
    """
    try:
        notification = await notification_service.send_incident_notification(
            db,
            engineer_id=request.engineer_id,
            incident_id=request.incident_id,
            channel=request.channel,
            priority=request.priority,
        )

        logger.info(
            f"Sent notification {notification.id} to engineer {request.engineer_id}",
            extra={
                "notification_id": str(notification.id),
                "engineer_id": str(request.engineer_id),
                "incident_id": str(request.incident_id),
                "channel": request.channel.value,
            },
        )

        return notification

    except Exception as e:
        logger.error(f"Failed to send notification: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send notification: {str(e)}")


@router.post("/acknowledge", response_model=dict)
async def acknowledge_notification(
    ack_data: NotificationAcknowledge,
    db: AsyncSession = Depends(get_db),
):
    """
    Acknowledge a notification using the token from the email link.

    This endpoint does NOT require API key authentication (token is sufficient).
    """
    # Find notification by token
    stmt = select(Notification).where(
        Notification.acknowledgement_token == ack_data.token
    )
    result = await db.execute(stmt)
    notification = result.scalar_one_or_none()

    if not notification:
        raise HTTPException(status_code=404, detail="Invalid or expired token")

    # Validate token
    is_valid, error = token_service.validate_token(
        ack_data.token,
        notification.id,
        notification.engineer_id,
        notification.token_expires_at,
    )

    if not is_valid:
        raise HTTPException(status_code=403, detail=f"Token validation failed: {error}")

    # Check if already acknowledged
    if notification.acknowledged_at:
        return {
            "status": "already_acknowledged",
            "acknowledged_at": notification.acknowledged_at.isoformat(),
            "response_time_seconds": notification.response_time_seconds,
        }

    # Mark as acknowledged
    notification.acknowledged_at = datetime.utcnow()
    notification.status = NotificationStatus.ACKNOWLEDGED

    # Calculate response time
    response_time = notification.calculate_response_time()
    notification.response_time_seconds = response_time

    # Check SLA
    sla_met = notification.check_sla()
    notification.sla_met = sla_met

    await db.commit()

    logger.info(
        f"Notification {notification.id} acknowledged by engineer {notification.engineer_id}",
        extra={
            "notification_id": str(notification.id),
            "response_time_seconds": response_time,
            "sla_met": sla_met,
        },
    )

    return {
        "status": "acknowledged",
        "acknowledged_at": notification.acknowledged_at.isoformat(),
        "response_time_seconds": response_time,
        "sla_met": sla_met,
        "incident_id": str(notification.incident_id) if notification.incident_id else None,
    }


@router.get("/{notification_id}", response_model=NotificationResponse)
async def get_notification(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """Get notification by ID."""
    stmt = select(Notification).where(Notification.id == notification_id)
    result = await db.execute(stmt)
    notification = result.scalar_one_or_none()

    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    return notification


@router.get("/", response_model=NotificationListResponse)
async def list_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    engineer_id: UUID | None = None,
    incident_id: UUID | None = None,
    status: NotificationStatus | None = None,
    escalated: bool | None = None,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """
    List notifications with pagination and filtering.

    Supports filtering by engineer, incident, status, and escalation state.
    """
    # Build query
    stmt = select(Notification).order_by(desc(Notification.created_at))

    if engineer_id:
        stmt = stmt.where(Notification.engineer_id == engineer_id)
    if incident_id:
        stmt = stmt.where(Notification.incident_id == incident_id)
    if status:
        stmt = stmt.where(Notification.status == status)
    if escalated is not None:
        stmt = stmt.where(Notification.escalated == escalated)

    # Get total count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar_one()

    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    # Clamp page
    if page > total_pages:
        page = total_pages

    # Apply pagination
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    # Execute query
    result = await db.execute(stmt)
    notifications = result.scalars().all()

    return NotificationListResponse(
        items=notifications,
        total=total,
        page=page,
        page_size=page_size,
        pages=total_pages,
    )


@router.patch("/{notification_id}", response_model=NotificationResponse)
async def update_notification(
    notification_id: UUID,
    update_data: NotificationUpdate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """Update a notification (for manual status changes)."""
    stmt = select(Notification).where(Notification.id == notification_id)
    result = await db.execute(stmt)
    notification = result.scalar_one_or_none()

    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    # Update fields
    update_dict = update_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(notification, field, value)

    await db.commit()
    await db.refresh(notification)

    return notification


@router.get("/stats/summary", response_model=NotificationStatsResponse)
async def get_notification_stats(
    engineer_id: UUID | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """
    Get notification statistics for monitoring and reporting.

    Returns counts, averages, and SLA compliance rates.
    """
    # Build base query
    stmt = select(Notification)

    if engineer_id:
        stmt = stmt.where(Notification.engineer_id == engineer_id)
    if start_date:
        stmt = stmt.where(Notification.created_at >= start_date)
    if end_date:
        stmt = stmt.where(Notification.created_at <= end_date)

    # Execute query
    result = await db.execute(stmt)
    notifications = result.scalars().all()

    # Calculate stats
    total_sent = sum(1 for n in notifications if n.sent_at is not None)
    total_delivered = sum(1 for n in notifications if n.delivered_at is not None)
    total_acknowledged = sum(1 for n in notifications if n.acknowledged_at is not None)
    total_failed = sum(1 for n in notifications if n.status == NotificationStatus.FAILED)

    # Calculate average response time
    response_times = [n.response_time_seconds for n in notifications if n.response_time_seconds]
    avg_response_time = sum(response_times) / len(response_times) if response_times else None

    # Calculate SLA compliance rate
    sla_results = [n.sla_met for n in notifications if n.sla_met is not None]
    sla_compliance = sum(sla_results) / len(sla_results) if sla_results else None

    # Calculate escalation rate
    total_escalated = sum(1 for n in notifications if n.escalated)
    escalation_rate = total_escalated / len(notifications) if notifications else None

    return NotificationStatsResponse(
        total_sent=total_sent,
        total_delivered=total_delivered,
        total_acknowledged=total_acknowledged,
        total_failed=total_failed,
        average_response_time_seconds=avg_response_time,
        sla_compliance_rate=sla_compliance,
        escalation_rate=escalation_rate,
    )
