
import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.decision.action_selector import ActionSelector
from app.core.perception.anomaly_detector import AnomalyDetector, categorize_anomaly
from app.core.reasoning.hypothesis_generator import HypothesisGenerator, rank_hypotheses
from app.database import get_db
from app.models.action import Action, ActionStatus
from app.models.hypothesis import Hypothesis
from app.models.incident import Incident, IncidentStatus
from app.schemas.incident import (
    IncidentCreate,
    IncidentFilter,
    IncidentListResponse,
    IncidentResponse,
    IncidentUpdate,
    IncidentWithRelations,
)
from app.schemas.assignment import (
    AutoAssignRequest,
    ManualAssignRequest,
    AssignmentResponse,
    AssignmentInfo,
)
from app.api.rate_limit import llm_rate_limit
from app.services.llm_client import get_llm_client
from app.services.prometheus_client import get_prometheus_client
from app.services.incident_assigner import incident_assigner
from app.services.event_logger import event_logger

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("", response_model=IncidentResponse, status_code=201)
async def create_incident(
    incident_data: IncidentCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new incident.

    This endpoint creates an incident record from detected anomalies.
    """
    incident = Incident(
        title=incident_data.title,
        description=incident_data.description,
        severity=incident_data.severity,
        affected_service=incident_data.affected_service,
        affected_components=incident_data.affected_components,
        detected_at=incident_data.detected_at,
        detection_source=incident_data.detection_source,
        metrics_snapshot=incident_data.metrics_snapshot,
        context=incident_data.context,
    )

    db.add(incident)
    await db.commit()
    await db.refresh(incident)

    logger.info(
        f"Created incident {incident.id} for service {incident.affected_service}",
        extra={"incident_id": str(incident.id), "service": incident.affected_service},
    )

    return incident


@router.get("/{incident_id}", response_model=IncidentWithRelations)
async def get_incident(
    incident_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get incident by ID with related hypotheses and actions."""
    stmt = (
        select(Incident)
        .where(Incident.id == incident_id)
        .options(selectinload(Incident.hypotheses), selectinload(Incident.actions))
    )

    result = await db.execute(stmt)
    incident = result.scalar_one_or_none()

    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    return incident


@router.get("", response_model=IncidentListResponse)
async def list_incidents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: IncidentStatus | None = Query(None, description="Filter by incident status"),
    severity: str | None = Query(None, description="Filter by severity (critical, high, medium, low)"),
    service: str | None = Query(
        None,
        description="Filter by affected service",
        min_length=1,
        max_length=255,
        pattern=r"^[a-zA-Z0-9_-]+$",
    ),
    assigned_engineer_id: UUID | None = Query(None, description="Filter by assigned engineer"),
    search: str | None = Query(
        None,
        description="Text search in title and description",
        min_length=1,
        max_length=255,
    ),
    start_date: datetime | None = Query(None, description="Filter incidents after this date"),
    end_date: datetime | None = Query(None, description="Filter incidents before this date"),
    db: AsyncSession = Depends(get_db),
):
    """
    List incidents with pagination and filtering.

    Supports filtering by:
    - status: Incident status (detected, analyzing, pending_approval, etc.)
    - severity: Incident severity (critical, high, medium, low)
    - service: Affected service name
    - assigned_engineer_id: Filter by assigned engineer
    - search: Text search in title and description (case-insensitive)
    - start_date/end_date: Date range filter
    """
    # Build query
    stmt = select(Incident).order_by(desc(Incident.detected_at))

    # Apply filters
    if status:
        stmt = stmt.where(Incident.status == status)
    if severity:
        from app.models.incident import IncidentSeverity
        try:
            severity_enum = IncidentSeverity(severity.lower())
            stmt = stmt.where(Incident.severity == severity_enum)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid severity: {severity}. Must be one of: critical, high, medium, low"
            )
    if service:
        stmt = stmt.where(Incident.affected_service == service)
    if assigned_engineer_id:
        stmt = stmt.where(Incident.assigned_engineer_id == assigned_engineer_id)
    if search:
        # Case-insensitive search in title and description
        search_pattern = f"%{search}%"
        from sqlalchemy import or_
        stmt = stmt.where(
            or_(
                Incident.title.ilike(search_pattern),
                Incident.description.ilike(search_pattern),
            )
        )
    if start_date:
        stmt = stmt.where(Incident.detected_at >= start_date)
    if end_date:
        stmt = stmt.where(Incident.detected_at <= end_date)

    # Get total count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar_one()

    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    # Clamp page to valid range so out-of-range pages return the last page
    # instead of an empty result with no indication of what happened
    if page > total_pages:
        page = total_pages

    # Apply pagination
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    # Execute query
    result = await db.execute(stmt)
    incidents = result.scalars().all()

    return IncidentListResponse(
        items=incidents,
        total=total,
        page=page,
        page_size=page_size,
        pages=total_pages,
    )


@router.patch("/{incident_id}", response_model=IncidentResponse)
async def update_incident(
    incident_id: UUID,
    update_data: IncidentUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update incident status and metadata."""
    stmt = select(Incident).where(Incident.id == incident_id)
    result = await db.execute(stmt)
    incident = result.scalar_one_or_none()

    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Update fields
    update_dict = update_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(incident, field, value)

    await db.commit()
    await db.refresh(incident)

    return incident


@router.post(
    "/{incident_id}/analyze",
    response_model=dict,
    dependencies=[Depends(llm_rate_limit)],
)
async def analyze_incident(
    incident_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger hypothesis generation for an incident.

    This endpoint:
    1. Fetches metrics from Prometheus
    2. Detects anomalies
    3. Generates hypotheses using LLM
    4. Creates hypothesis records
    5. Updates incident status

    Senior Engineering Note:
    This is the core workflow that ties together all layers.
    """
    # Get incident
    stmt = select(Incident).where(Incident.id == incident_id)
    result = await db.execute(stmt)
    incident = result.scalar_one_or_none()

    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    if incident.status != IncidentStatus.DETECTED:
        raise HTTPException(
            status_code=400,
            detail=f"Incident must be in DETECTED status (current: {incident.status.value})",
        )

    # Update status
    incident.status = IncidentStatus.ANALYZING
    await db.commit()

    try:
        # Get metrics from Prometheus
        prom_client = get_prometheus_client()
        service_metrics = await prom_client.get_service_metrics(
            service_name=incident.affected_service,
            lookback_minutes=5,
        )

        # Detect anomalies
        anomaly_detector = AnomalyDetector(
            threshold_sigma=settings.anomaly_threshold_sigma,
        )

        all_metric_results = []
        for metric_name, results in service_metrics.items():
            all_metric_results.extend(results)

        anomalies = anomaly_detector.detect_multiple(all_metric_results)

        if not anomalies:
            logger.warning(f"No anomalies detected for incident {incident_id}")
            incident.status = IncidentStatus.RESOLVED
            await db.commit()
            return {
                "status": "no_anomalies",
                "message": "No anomalies detected in current metrics",
            }

        # Generate hypotheses using LLM
        llm_client = get_llm_client()
        hypothesis_generator = HypothesisGenerator(llm_client)

        service_context = incident.context.copy()

        hypotheses_response, llm_response = await hypothesis_generator.generate(
            anomalies=anomalies,
            service_name=incident.affected_service,
            service_context=service_context,
        )

        # Create hypothesis records
        ranked_hypotheses = rank_hypotheses(hypotheses_response.hypotheses)

        for rank, hypothesis_item in ranked_hypotheses:
            hypothesis = Hypothesis(
                incident_id=incident.id,
                description=hypothesis_item.description,
                category=hypothesis_item.category,
                confidence_score=hypothesis_item.confidence_score,
                rank=rank,
                evidence={
                    "items": [e.model_dump() for e in hypothesis_item.evidence],
                    "anomalies": [
                        {
                            "metric": a.metric_name,
                            "current_value": a.current_value,
                            "expected_value": a.expected_value,
                            "deviation_sigma": a.deviation_sigma,
                            "category": categorize_anomaly(a),
                        }
                        for a in anomalies
                    ],
                },
                supporting_signals=[a.metric_name for a in anomalies],
                llm_model=llm_response.model,
                llm_prompt_tokens=llm_response.prompt_tokens,
                llm_completion_tokens=llm_response.completion_tokens,
                llm_reasoning=hypothesis_item.reasoning,
            )
            db.add(hypothesis)

        # Generate action recommendation for top hypothesis
        action_selector = ActionSelector()
        top_hypothesis = ranked_hypotheses[0][1]

        action_recommendation = action_selector.select(
            hypothesis=top_hypothesis,
            service_name=incident.affected_service,
            service_context=service_context,
        )

        if action_recommendation:
            action = Action(
                incident_id=incident.id,
                action_type=action_recommendation.action_type,
                name=action_recommendation.name,
                description=action_recommendation.description,
                target_service=action_recommendation.target_service,
                target_resource=action_recommendation.target_resource,
                risk_level=action_recommendation.risk_level,
                risk_score=action_recommendation.risk_score,
                blast_radius=action_recommendation.blast_radius,
                requires_approval=action_recommendation.requires_approval,
                parameters=action_recommendation.parameters,
                execution_mode="dry_run" if settings.dry_run_mode else "live",
                status=ActionStatus.PENDING_APPROVAL,
            )
            db.add(action)

        # Update incident status
        incident.status = IncidentStatus.PENDING_APPROVAL
        await db.commit()

        logger.info(
            f"Generated {len(ranked_hypotheses)} hypotheses for incident {incident_id}",
            extra={
                "incident_id": str(incident_id),
                "hypotheses_count": len(ranked_hypotheses),
                "tokens_used": llm_response.total_tokens,
            },
        )

        return {
            "status": "success",
            "hypotheses_generated": len(ranked_hypotheses),
            "action_recommended": action_recommendation is not None,
            "tokens_used": llm_response.total_tokens,
        }

    except Exception as e:
        logger.error(f"Analysis failed for incident {incident_id}: {str(e)}", exc_info=True)
        incident.status = IncidentStatus.FAILED
        await db.commit()
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


# ============================================================================
# ASSIGNMENT ENDPOINTS
# ============================================================================


@router.post("/{incident_id}/assign", response_model=AssignmentResponse)
async def auto_assign_incident(
    incident_id: UUID,
    request: AutoAssignRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Auto-assign incident to an engineer.

    Uses intelligent assignment strategy:
    - 'on_call': Assigns to current on-call engineer for the service (default)
    - 'load_balanced': Assigns to least busy available engineer

    If primary strategy fails, automatically falls back to load-balanced.
    """
    # Get incident
    stmt = select(Incident).where(Incident.id == incident_id)
    result = await db.execute(stmt)
    incident = result.scalar_one_or_none()

    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Perform assignment
    assignment_result = await incident_assigner.auto_assign(
        db=db,
        incident=incident,
        strategy=request.strategy,
    )

    if not assignment_result.success:
        raise HTTPException(
            status_code=400,
            detail=assignment_result.reason or "Assignment failed",
        )

    await db.commit()

    logger.info(
        f"Auto-assigned incident {incident_id} to engineer {assignment_result.engineer.name} "
        f"using {assignment_result.strategy} strategy"
    )

    return AssignmentResponse(
        success=True,
        engineer=assignment_result.engineer.to_dict() if assignment_result.engineer else None,
        strategy=assignment_result.strategy,
        reason=assignment_result.reason,
    )


@router.post("/{incident_id}/assign/{engineer_id}", response_model=AssignmentResponse)
async def manual_assign_incident(
    incident_id: UUID,
    engineer_id: UUID,
    force: bool = Query(False, description="Force assignment even if at capacity"),
    db: AsyncSession = Depends(get_db),
):
    """
    Manually assign incident to a specific engineer.

    Args:
        incident_id: Incident to assign
        engineer_id: Engineer to assign to
        force: If true, allows assignment even if engineer is at capacity

    Use this for explicit assignment or reassignment.
    """
    # Get incident
    stmt = select(Incident).where(Incident.id == incident_id)
    result = await db.execute(stmt)
    incident = result.scalar_one_or_none()

    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Perform manual assignment
    assignment_result = await incident_assigner.assign_manual(
        db=db,
        incident=incident,
        engineer_id=engineer_id,
        force=force,
    )

    if not assignment_result.success:
        raise HTTPException(
            status_code=400,
            detail=assignment_result.reason or "Assignment failed",
        )

    await db.commit()

    logger.info(
        f"Manually assigned incident {incident_id} to engineer {assignment_result.engineer.name} "
        f"(force={force})"
    )

    return AssignmentResponse(
        success=True,
        engineer=assignment_result.engineer.to_dict() if assignment_result.engineer else None,
        strategy="manual",
        reason=assignment_result.reason,
    )


@router.delete("/{incident_id}/assign", response_model=AssignmentResponse)
async def unassign_incident(
    incident_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Unassign engineer from incident.

    Removes the current assignment and decrements engineer's workload count.
    """
    # Get incident
    stmt = select(Incident).where(Incident.id == incident_id)
    result = await db.execute(stmt)
    incident = result.scalar_one_or_none()

    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Perform unassignment
    assignment_result = await incident_assigner.unassign(
        db=db,
        incident=incident,
    )

    if not assignment_result.success:
        raise HTTPException(
            status_code=400,
            detail=assignment_result.reason or "Unassignment failed",
        )

    await db.commit()

    logger.info(f"Unassigned incident {incident_id}")

    return AssignmentResponse(
        success=True,
        engineer=None,
        strategy=None,
        reason=assignment_result.reason,
    )


@router.get("/{incident_id}/assignment", response_model=AssignmentInfo)
async def get_incident_assignment(
    incident_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Get current assignment information for an incident.

    Returns:
        - Whether incident is assigned
        - Engineer details if assigned
        - Assignment timestamp
    """
    # Get incident with engineer relationship
    stmt = (
        select(Incident)
        .where(Incident.id == incident_id)
        .options(selectinload(Incident.assigned_engineer))
    )
    result = await db.execute(stmt)
    incident = result.scalar_one_or_none()

    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Find assignment event for timestamp
    from app.models.incident_event import IncidentEvent, IncidentEventType

    stmt_event = (
        select(IncidentEvent)
        .where(
            IncidentEvent.incident_id == incident_id,
            IncidentEvent.event_type == IncidentEventType.ENGINEER_ASSIGNED,
        )
        .order_by(desc(IncidentEvent.created_at))
    )
    event_result = await db.execute(stmt_event)
    assignment_event = event_result.scalar_one_or_none()

    return AssignmentInfo(
        incident_id=incident_id,
        is_assigned=incident.assigned_engineer_id is not None,
        assigned_engineer=(
            incident.assigned_engineer.to_dict() if incident.assigned_engineer else None
        ),
        assigned_at=(
            assignment_event.created_at.isoformat() if assignment_event else None
        ),
    )
