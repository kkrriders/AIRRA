"""
Postmortem (Post-Incident Review) API endpoints.

Provides:
- Timeline generation (auto from events)
- Postmortem CRUD
- Action item tracking
"""
import logging
from datetime import datetime, timezone, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import verify_api_key
from app.database import get_db
from app.models.incident import Incident
from app.models.incident_event import IncidentEvent
from app.models.postmortem import Postmortem
from app.schemas.postmortem import (
    PostmortemCreate,
    PostmortemUpdate,
    PostmortemResponse,
    TimelineEvent,
    IncidentTimeline,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/incidents/{incident_id}/timeline", response_model=IncidentTimeline)
async def get_incident_timeline(
    incident_id: UUID,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """
    Get incident timeline (auto-generated from events).

    Returns chronological list of all events in the incident lifecycle.
    Used for postmortem generation and debugging.
    """
    # Verify incident exists
    incident = await db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Get all events ordered by timestamp
    stmt = (
        select(IncidentEvent)
        .where(IncidentEvent.incident_id == incident_id)
        .order_by(IncidentEvent.created_at)
    )
    result = await db.execute(stmt)
    events = result.scalars().all()

    # Calculate duration if resolved
    duration_minutes = None
    if incident.resolved_at and incident.detected_at:
        duration = incident.resolved_at - incident.detected_at
        duration_minutes = int(duration.total_seconds() / 60)

    return IncidentTimeline(
        incident_id=incident_id,
        events=[TimelineEvent.from_orm(e) for e in events],
        total_events=len(events),
        duration_minutes=duration_minutes,
    )


@router.post("/postmortems", response_model=PostmortemResponse, status_code=201)
async def create_postmortem(
    data: PostmortemCreate,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """
    Create a post-incident review (postmortem).

    Should be created after incident resolution to document:
    - Root cause
    - Impact
    - Learnings
    - Action items
    """
    # Verify incident exists
    incident = await db.get(Incident, data.incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Check if postmortem already exists
    stmt = select(Postmortem).where(Postmortem.incident_id == data.incident_id)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Postmortem already exists for this incident"
        )

    # Create postmortem
    postmortem = Postmortem(
        **data.model_dump(),
        author_id=None,  # TODO: Get from auth context when available
    )

    db.add(postmortem)
    await db.commit()
    await db.refresh(postmortem)

    logger.info(f"Postmortem created for incident {data.incident_id}")

    return PostmortemResponse.from_orm(postmortem)


@router.get("/postmortems/{postmortem_id}", response_model=PostmortemResponse)
async def get_postmortem(
    postmortem_id: UUID,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """Get a postmortem by ID."""
    postmortem = await db.get(Postmortem, postmortem_id)
    if not postmortem:
        raise HTTPException(status_code=404, detail="Postmortem not found")

    return PostmortemResponse.from_orm(postmortem)


@router.get("/incidents/{incident_id}/postmortem", response_model=PostmortemResponse)
async def get_postmortem_by_incident(
    incident_id: UUID,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """Get postmortem for a specific incident."""
    stmt = select(Postmortem).where(Postmortem.incident_id == incident_id)
    postmortem = (await db.execute(stmt)).scalar_one_or_none()

    if not postmortem:
        raise HTTPException(
            status_code=404,
            detail="No postmortem found for this incident"
        )

    return PostmortemResponse.from_orm(postmortem)


@router.patch("/postmortems/{postmortem_id}", response_model=PostmortemResponse)
async def update_postmortem(
    postmortem_id: UUID,
    data: PostmortemUpdate,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """Update a postmortem."""
    postmortem = await db.get(Postmortem, postmortem_id)
    if not postmortem:
        raise HTTPException(status_code=404, detail="Postmortem not found")

    # Update fields
    update_data = data.model_dump(exclude_unset=True)

    # Handle publication
    if "published" in update_data and update_data["published"] and not postmortem.published:
        update_data["published_at"] = datetime.now(timezone.utc)

    for key, value in update_data.items():
        setattr(postmortem, key, value)

    await db.commit()
    await db.refresh(postmortem)

    logger.info(f"Postmortem {postmortem_id} updated")

    return PostmortemResponse.from_orm(postmortem)


@router.delete("/postmortems/{postmortem_id}", status_code=204)
async def delete_postmortem(
    postmortem_id: UUID,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """Delete a postmortem."""
    postmortem = await db.get(Postmortem, postmortem_id)
    if not postmortem:
        raise HTTPException(status_code=404, detail="Postmortem not found")

    await db.delete(postmortem)
    await db.commit()

    logger.info(f"Postmortem {postmortem_id} deleted")


@router.get("/postmortems", response_model=list[PostmortemResponse])
async def list_postmortems(
    published_only: bool = Query(False, description="Show only published postmortems"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """List all postmortems."""
    stmt = select(Postmortem).order_by(Postmortem.created_at.desc())

    if published_only:
        stmt = stmt.where(Postmortem.published == True)

    stmt = stmt.limit(limit).offset(offset)

    result = await db.execute(stmt)
    postmortems = result.scalars().all()

    return [PostmortemResponse.from_orm(p) for p in postmortems]
