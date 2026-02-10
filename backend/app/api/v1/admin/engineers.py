"""
Engineer Management API endpoints.

Senior Engineering Note:
- RESTful CRUD operations for engineers
- Pagination support for list endpoints
- Availability tracking for assignment algorithms
- Async request handling with proper error handling
"""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.engineer import Engineer, EngineerStatus
from app.schemas.engineer import (
    EngineerCreate,
    EngineerListResponse,
    EngineerResponse,
    EngineerUpdate,
    EngineerWithStats,
    EngineerAvailability,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/", response_model=EngineerResponse, status_code=201)
async def create_engineer(
    engineer_data: EngineerCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new engineer profile.

    Registers a new engineer who can be assigned incident reviews.
    """
    # Check if email already exists
    stmt = select(Engineer).where(Engineer.email == engineer_data.email)
    existing = (await db.execute(stmt)).scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Engineer with email {engineer_data.email} already exists",
        )

    # Create new engineer
    engineer = Engineer(**engineer_data.model_dump())
    db.add(engineer)

    try:
        await db.commit()
        await db.refresh(engineer)
        logger.info(
            "Engineer created",
            extra={"engineer_id": str(engineer.id), "email": engineer.email},
        )
        return engineer
    except Exception as e:
        await db.rollback()
        logger.error("Failed to create engineer", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="Failed to create engineer")


@router.get("/", response_model=EngineerListResponse)
async def list_engineers(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    status: EngineerStatus | None = Query(None, description="Filter by status"),
    available_only: bool = Query(False, description="Show only available engineers"),
    db: AsyncSession = Depends(get_db),
):
    """
    List all engineers with pagination and filtering.

    Supports filtering by status and availability for assignment workflows.
    """
    # Build base query
    stmt = select(Engineer).order_by(desc(Engineer.created_at))

    # Apply filters
    if status:
        stmt = stmt.where(Engineer.status == status)
    if available_only:
        stmt = stmt.where(Engineer.is_available == True)  # noqa: E712

    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    # Calculate pagination
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1
    if page > total_pages:
        page = total_pages

    # Paginate
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    engineers = result.scalars().all()

    return EngineerListResponse(
        items=engineers,
        total=total,
        page=page,
        page_size=page_size,
        pages=total_pages,
    )


@router.get("/{engineer_id}", response_model=EngineerWithStats)
async def get_engineer(
    engineer_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Get engineer details with statistics.

    Returns complete engineer profile including workload and performance metrics.
    """
    stmt = select(Engineer).where(Engineer.id == engineer_id)
    engineer = (await db.execute(stmt)).scalar_one_or_none()

    if not engineer:
        raise HTTPException(status_code=404, detail="Engineer not found")

    # Calculate statistics
    # TODO: Query actual review counts from engineer_reviews table
    stats = EngineerWithStats(
        **engineer.__dict__,
        pending_reviews=0,  # Will be populated from engineer_reviews
        in_progress_reviews=engineer.current_review_count,
        completed_today=0,  # Will be calculated from today's completed reviews
        capacity_percentage=(
            (engineer.current_review_count / engineer.max_concurrent_reviews * 100)
            if engineer.max_concurrent_reviews > 0
            else 0
        ),
    )

    return stats


@router.patch("/{engineer_id}", response_model=EngineerResponse)
async def update_engineer(
    engineer_id: UUID,
    update_data: EngineerUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    Update engineer profile.

    Allows updating engineer details, status, and availability.
    """
    stmt = select(Engineer).where(Engineer.id == engineer_id)
    engineer = (await db.execute(stmt)).scalar_one_or_none()

    if not engineer:
        raise HTTPException(status_code=404, detail="Engineer not found")

    # Check email uniqueness if being updated
    if update_data.email and update_data.email != engineer.email:
        email_stmt = select(Engineer).where(Engineer.email == update_data.email)
        existing = (await db.execute(email_stmt)).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Engineer with email {update_data.email} already exists",
            )

    # Apply updates
    update_dict = update_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(engineer, field, value)

    # Auto-update is_available based on status
    if "status" in update_dict:
        engineer.is_available = engineer.status == EngineerStatus.ACTIVE

    try:
        await db.commit()
        await db.refresh(engineer)
        logger.info(
            "Engineer updated",
            extra={"engineer_id": str(engineer.id), "updated_fields": list(update_dict.keys())},
        )
        return engineer
    except Exception as e:
        await db.rollback()
        logger.error("Failed to update engineer", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="Failed to update engineer")


@router.delete("/{engineer_id}", status_code=204)
async def delete_engineer(
    engineer_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Delete an engineer profile.

    Note: This will cascade delete all associated reviews.
    Consider soft-delete in production to preserve history.
    """
    stmt = select(Engineer).where(Engineer.id == engineer_id)
    engineer = (await db.execute(stmt)).scalar_one_or_none()

    if not engineer:
        raise HTTPException(status_code=404, detail="Engineer not found")

    # Check if engineer has active reviews
    if engineer.current_review_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete engineer with {engineer.current_review_count} active reviews. "
            "Reassign or complete reviews first.",
        )

    try:
        await db.delete(engineer)
        await db.commit()
        logger.info("Engineer deleted", extra={"engineer_id": str(engineer_id)})
        return None
    except Exception as e:
        await db.rollback()
        logger.error("Failed to delete engineer", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="Failed to delete engineer")


@router.get("/{engineer_id}/availability", response_model=EngineerAvailability)
async def check_engineer_availability(
    engineer_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Check if engineer can accept new review assignments.

    Used by auto-assignment algorithms to find available engineers.
    """
    stmt = select(Engineer).where(Engineer.id == engineer_id)
    engineer = (await db.execute(stmt)).scalar_one_or_none()

    if not engineer:
        raise HTTPException(status_code=404, detail="Engineer not found")

    can_accept = engineer.can_accept_review()
    reason = None

    if not can_accept:
        if engineer.status != EngineerStatus.ACTIVE:
            reason = f"Status: {engineer.status.value}"
        elif not engineer.is_available:
            reason = "Currently unavailable"
        elif engineer.is_at_capacity():
            reason = f"At capacity ({engineer.current_review_count}/{engineer.max_concurrent_reviews})"

    return EngineerAvailability(
        engineer_id=engineer.id,
        name=engineer.name,
        is_available=engineer.is_available,
        current_review_count=engineer.current_review_count,
        max_concurrent_reviews=engineer.max_concurrent_reviews,
        can_accept_review=can_accept,
        reason=reason,
    )


@router.get("/available/list", response_model=list[EngineerResponse])
async def list_available_engineers(
    expertise: str | None = Query(None, description="Filter by expertise area"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get list of engineers currently available for assignments.

    Optionally filter by expertise for intelligent assignment.
    Used by auto-assignment algorithms.
    """
    stmt = (
        select(Engineer)
        .where(
            Engineer.is_available == True,  # noqa: E712
            Engineer.status == EngineerStatus.ACTIVE,
        )
        .order_by(Engineer.current_review_count)  # Load-balance: least busy first
    )

    result = await db.execute(stmt)
    engineers = result.scalars().all()

    # Filter by expertise if specified (JSON array contains check)
    if expertise:
        engineers = [e for e in engineers if expertise in e.expertise]

    # Filter to only those who can accept reviews
    available = [e for e in engineers if e.can_accept_review()]

    return available
