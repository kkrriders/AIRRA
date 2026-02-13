
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
from app.api.rate_limit import llm_rate_limit
from app.services.llm_client import get_llm_client
from app.services.prometheus_client import get_prometheus_client

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/", response_model=IncidentResponse, status_code=201)
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


@router.get("/", response_model=IncidentListResponse)
async def list_incidents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: IncidentStatus | None = Query(None, description="Filter by incident status"),
    service: str | None = Query(
        None,
        description="Filter by affected service",
        min_length=1,
        max_length=255,
        pattern=r"^[a-zA-Z0-9_-]+$",
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    List incidents with pagination and filtering.

    Supports filtering by status and service.
    Service name is validated to prevent SQL injection.
    """
    # Build query
    stmt = select(Incident).order_by(desc(Incident.detected_at))

    if status:
        stmt = stmt.where(Incident.status == status)
    if service:
        stmt = stmt.where(Incident.affected_service == service)

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
