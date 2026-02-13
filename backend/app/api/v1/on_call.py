"""
On-Call Schedule API endpoints.

Senior Engineering Note:
- CRUD operations for on-call schedules
- Find current on-call engineer
- Escalation chain lookup
- Pagination support
"""
import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import verify_api_key
from app.database import get_db
from app.models.on_call_schedule import OnCallSchedule, OnCallPriority
from app.schemas.on_call_schedule import (
    OnCallScheduleCreate,
    OnCallScheduleUpdate,
    OnCallScheduleResponse,
    OnCallScheduleWithEngineer,
    OnCallFindRequest,
    OnCallListResponse,
)
from app.services.on_call_finder import on_call_finder

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/", response_model=OnCallScheduleResponse, status_code=201)
async def create_on_call_schedule(
    schedule_data: OnCallScheduleCreate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """
    Create a new on-call schedule assignment.

    Assigns an engineer to be on-call for a specific service/team
    during a time period with a priority level.
    """
    schedule = OnCallSchedule(
        engineer_id=schedule_data.engineer_id,
        service=schedule_data.service,
        team=schedule_data.team,
        start_time=schedule_data.start_time,
        end_time=schedule_data.end_time,
        priority=schedule_data.priority,
        schedule_name=schedule_data.schedule_name,
        rotation_week=schedule_data.rotation_week,
        is_active=schedule_data.is_active,
    )

    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)

    logger.info(
        f"Created on-call schedule {schedule.id} for engineer {schedule.engineer_id}",
        extra={
            "schedule_id": str(schedule.id),
            "engineer_id": str(schedule.engineer_id),
            "service": schedule.service,
        },
    )

    return schedule


@router.get("/{schedule_id}", response_model=OnCallScheduleResponse)
async def get_on_call_schedule(
    schedule_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """Get on-call schedule by ID."""
    stmt = select(OnCallSchedule).where(OnCallSchedule.id == schedule_id)
    result = await db.execute(stmt)
    schedule = result.scalar_one_or_none()

    if not schedule:
        raise HTTPException(status_code=404, detail="On-call schedule not found")

    return schedule


@router.get("/", response_model=OnCallListResponse)
async def list_on_call_schedules(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: str | None = Query(None, pattern=r"^[a-zA-Z0-9_-]+$"),
    team: str | None = None,
    engineer_id: UUID | None = None,
    is_active: bool | None = None,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """
    List on-call schedules with pagination and filtering.

    Supports filtering by service, team, engineer, and active status.
    """
    # Build query
    stmt = select(OnCallSchedule).order_by(desc(OnCallSchedule.start_time))

    if service:
        stmt = stmt.where(OnCallSchedule.service == service)
    if team:
        stmt = stmt.where(OnCallSchedule.team == team)
    if engineer_id:
        stmt = stmt.where(OnCallSchedule.engineer_id == engineer_id)
    if is_active is not None:
        stmt = stmt.where(OnCallSchedule.is_active == is_active)

    # Get total count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar_one()

    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    # Clamp page to valid range
    if page > total_pages:
        page = total_pages

    # Apply pagination
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    # Execute query
    result = await db.execute(stmt)
    schedules = result.scalars().all()

    return OnCallListResponse(
        items=schedules,
        total=total,
        page=page,
        page_size=page_size,
        pages=total_pages,
    )


@router.patch("/{schedule_id}", response_model=OnCallScheduleResponse)
async def update_on_call_schedule(
    schedule_id: UUID,
    update_data: OnCallScheduleUpdate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """Update an on-call schedule."""
    stmt = select(OnCallSchedule).where(OnCallSchedule.id == schedule_id)
    result = await db.execute(stmt)
    schedule = result.scalar_one_or_none()

    if not schedule:
        raise HTTPException(status_code=404, detail="On-call schedule not found")

    # Update fields
    update_dict = update_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(schedule, field, value)

    await db.commit()
    await db.refresh(schedule)

    return schedule


@router.delete("/{schedule_id}", status_code=204)
async def delete_on_call_schedule(
    schedule_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """Delete an on-call schedule."""
    stmt = select(OnCallSchedule).where(OnCallSchedule.id == schedule_id)
    result = await db.execute(stmt)
    schedule = result.scalar_one_or_none()

    if not schedule:
        raise HTTPException(status_code=404, detail="On-call schedule not found")

    await db.delete(schedule)
    await db.commit()

    logger.info(f"Deleted on-call schedule {schedule_id}")


@router.post("/find-current", response_model=dict)
async def find_current_on_call(
    request: OnCallFindRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """
    Find who's currently on-call for a service/team.

    Returns the on-call engineer with their schedule and priority level.
    Automatically handles escalation chain if primary is unavailable.
    """
    result = await on_call_finder.find_on_call_engineer(
        db,
        service=request.service,
        team=request.team,
        at_time=request.time,
        priority=request.priority,
    )

    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"No on-call engineer found for service={request.service}, team={request.team}",
        )

    return result.to_dict()


@router.post("/escalation-chain", response_model=list[dict])
async def get_escalation_chain(
    request: OnCallFindRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """
    Get the complete escalation chain (PRIMARY → SECONDARY → TERTIARY).

    Useful for displaying who to contact if primary doesn't respond.
    """
    chain = await on_call_finder.find_escalation_chain(
        db,
        service=request.service,
        team=request.team,
        at_time=request.time,
    )

    if not chain:
        raise HTTPException(
            status_code=404,
            detail=f"No escalation chain found for service={request.service}, team={request.team}",
        )

    return [result.to_dict() for result in chain]


@router.get("/current/all", response_model=list[dict])
async def get_all_current_on_call(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """
    Get all currently on-call engineers across all services.

    Useful for dashboards showing on-call status.
    """
    results = await on_call_finder.get_all_current_on_call(db)

    return [result.to_dict() for result in results]
