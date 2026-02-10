"""
Review Assignment and Management API endpoints.

Senior Engineering Note:
- Assignment workflow for engineer reviews
- Status tracking and filtering
- Integration with incident lifecycle
"""
import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.engineer import Engineer, EngineerStatus
from app.models.engineer_review import EngineerReview, ReviewStatus, ReviewDecision
from app.models.incident import Incident, IncidentStatus
from app.schemas.engineer_review import (
    EngineerReviewCreate,
    EngineerReviewListResponse,
    EngineerReviewResponse,
    EngineerReviewSubmit,
    EngineerReviewWithRelations,
    ReviewAssignment,
    ReviewDecisionRequest,
    ReviewComparison,
)
from app.schemas.incident import IncidentResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/incidents/{incident_id}/assign", response_model=EngineerReviewResponse, status_code=201)
async def assign_review_to_engineer(
    incident_id: UUID,
    assignment: ReviewAssignment,
    db: AsyncSession = Depends(get_db),
):
    """
    Assign an incident to an engineer for review.

    Creates a review assignment and updates engineer workload.
    """
    # Verify incident exists and is in appropriate state
    incident_stmt = select(Incident).where(Incident.id == incident_id)
    incident = (await db.execute(incident_stmt)).scalar_one_or_none()

    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Verify engineer exists and can accept review
    engineer_stmt = select(Engineer).where(Engineer.id == assignment.engineer_id)
    engineer = (await db.execute(engineer_stmt)).scalar_one_or_none()

    if not engineer:
        raise HTTPException(status_code=404, detail="Engineer not found")

    if not engineer.can_accept_review():
        raise HTTPException(
            status_code=400,
            detail=f"Engineer cannot accept review: "
            f"status={engineer.status.value}, "
            f"available={engineer.is_available}, "
            f"capacity={engineer.current_review_count}/{engineer.max_concurrent_reviews}",
        )

    # Check if already assigned
    existing_stmt = select(EngineerReview).where(
        EngineerReview.incident_id == incident_id,
        EngineerReview.status.in_([ReviewStatus.ASSIGNED, ReviewStatus.IN_PROGRESS]),
    )
    existing = (await db.execute(existing_stmt)).scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Incident already has an active review (review_id={existing.id})",
        )

    # Create review assignment
    review = EngineerReview(
        incident_id=incident_id,
        engineer_id=assignment.engineer_id,
        assigned_at=datetime.utcnow(),
        priority=assignment.priority,
        notes=assignment.notes,
    )
    db.add(review)

    # Update engineer workload
    engineer.current_review_count += 1
    if engineer.current_review_count >= engineer.max_concurrent_reviews:
        engineer.is_available = False

    # Update incident status if needed
    if incident.status == IncidentStatus.DETECTED:
        incident.status = IncidentStatus.PENDING_APPROVAL  # Or create new status PENDING_REVIEW

    try:
        await db.commit()
        await db.refresh(review)
        logger.info(
            "Review assigned",
            extra={
                "review_id": str(review.id),
                "incident_id": str(incident_id),
                "engineer_id": str(assignment.engineer_id),
            },
        )
        return review
    except Exception as e:
        await db.rollback()
        logger.error("Failed to assign review", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="Failed to assign review")


@router.get("/incidents/pending-review", response_model=list[IncidentResponse])
async def list_incidents_pending_review(
    limit: int = Query(50, ge=1, le=100, description="Maximum items to return"),
    db: AsyncSession = Depends(get_db),
):
    """
    List incidents that need engineer review assignment.

    Returns incidents that:
    - Have low AI confidence scores
    - Are marked as critical severity
    - Don't have an active review assignment
    """
    # Find incidents without active reviews
    # This is a simplified version - in production, add more sophisticated filtering
    stmt = (
        select(Incident)
        .where(
            Incident.status.in_([
                IncidentStatus.DETECTED,
                IncidentStatus.ANALYZING,
                IncidentStatus.PENDING_APPROVAL,
            ])
        )
        .order_by(
            desc(Incident.severity),  # Critical first
            Incident.detected_at,  # Oldest first
        )
        .limit(limit)
    )

    result = await db.execute(stmt)
    incidents = result.scalars().all()

    # Filter out incidents that already have active reviews
    incident_ids = [str(inc.id) for inc in incidents]
    if incident_ids:
        review_stmt = select(EngineerReview.incident_id).where(
            EngineerReview.incident_id.in_(incident_ids),
            EngineerReview.status.in_([ReviewStatus.ASSIGNED, ReviewStatus.IN_PROGRESS]),
        )
        assigned_ids = set((await db.execute(review_stmt)).scalars().all())
        incidents = [inc for inc in incidents if inc.id not in assigned_ids]

    return incidents


@router.get("/incidents/under-review", response_model=EngineerReviewListResponse)
async def list_incidents_under_review(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    engineer_id: UUID | None = Query(None, description="Filter by engineer"),
    db: AsyncSession = Depends(get_db),
):
    """
    List incidents currently under engineer review.

    Returns reviews that are assigned or in progress.
    """
    stmt = (
        select(EngineerReview)
        .where(
            EngineerReview.status.in_([ReviewStatus.ASSIGNED, ReviewStatus.IN_PROGRESS])
        )
        .order_by(desc(EngineerReview.assigned_at))
    )

    if engineer_id:
        stmt = stmt.where(EngineerReview.engineer_id == engineer_id)

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
    reviews = result.scalars().all()

    return EngineerReviewListResponse(
        items=reviews,
        total=total,
        page=page,
        page_size=page_size,
        pages=total_pages,
    )


@router.post("/reviews/{review_id}/start", response_model=EngineerReviewResponse)
async def start_review(
    review_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Mark a review as started by the engineer.

    Updates status to IN_PROGRESS and records start time.
    """
    stmt = select(EngineerReview).where(EngineerReview.id == review_id)
    review = (await db.execute(stmt)).scalar_one_or_none()

    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    if review.status != ReviewStatus.ASSIGNED:
        raise HTTPException(
            status_code=400,
            detail=f"Review cannot be started from status: {review.status.value}",
        )

    review.status = ReviewStatus.IN_PROGRESS
    review.started_at = datetime.utcnow()

    await db.commit()
    await db.refresh(review)

    logger.info("Review started", extra={"review_id": str(review_id)})
    return review


@router.post("/reviews/{review_id}/submit", response_model=EngineerReviewResponse)
async def submit_review(
    review_id: UUID,
    submission: EngineerReviewSubmit,
    db: AsyncSession = Depends(get_db),
):
    """
    Submit a completed engineer review.

    Records engineer's analysis, alternative hypotheses, and suggested approach.
    """
    stmt = select(EngineerReview).where(EngineerReview.id == review_id)
    review = (await db.execute(stmt)).scalar_one_or_none()

    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    if review.status not in [ReviewStatus.ASSIGNED, ReviewStatus.IN_PROGRESS]:
        raise HTTPException(
            status_code=400,
            detail=f"Review cannot be submitted from status: {review.status.value}",
        )

    # Update review with submission data
    review.status = ReviewStatus.SUBMITTED
    review.submitted_at = datetime.utcnow()
    review.ai_hypotheses_reviewed = submission.ai_hypotheses_reviewed
    review.ai_confidence_assessment = submission.ai_confidence_assessment
    review.alternative_hypotheses = submission.alternative_hypotheses
    review.suggested_approach = submission.suggested_approach
    review.engineer_confidence_score = submission.engineer_confidence_score
    review.notes = submission.notes
    review.tags = submission.tags

    # Calculate review time
    if review.started_at:
        review.review_time_minutes = review.calculate_review_time()

    await db.commit()
    await db.refresh(review)

    logger.info(
        "Review submitted",
        extra={
            "review_id": str(review_id),
            "engineer_confidence": submission.engineer_confidence_score,
        },
    )
    return review


@router.get("/reviews/{review_id}", response_model=EngineerReviewWithRelations)
async def get_review(
    review_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Get review details with related incident and engineer.
    """
    stmt = (
        select(EngineerReview)
        .options(
            selectinload(EngineerReview.incident),
            selectinload(EngineerReview.engineer),
        )
        .where(EngineerReview.id == review_id)
    )
    review = (await db.execute(stmt)).scalar_one_or_none()

    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    return review


@router.get("/engineers/{engineer_id}/reviews", response_model=EngineerReviewListResponse)
async def get_engineer_review_history(
    engineer_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: ReviewStatus | None = Query(None, description="Filter by status"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get review history for a specific engineer.
    """
    stmt = (
        select(EngineerReview)
        .where(EngineerReview.engineer_id == engineer_id)
        .order_by(desc(EngineerReview.assigned_at))
    )

    if status:
        stmt = stmt.where(EngineerReview.status == status)

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
    reviews = result.scalars().all()

    return EngineerReviewListResponse(
        items=reviews,
        total=total,
        page=page,
        page_size=page_size,
        pages=total_pages,
    )


@router.get("/incidents/{incident_id}/comparison", response_model=ReviewComparison)
async def get_ai_vs_engineer_comparison(
    incident_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Compare AI and Engineer approaches for decision-making.

    Returns side-by-side comparison of AI hypothesis vs Engineer analysis.
    """
    # Get incident with hypotheses
    incident_stmt = (
        select(Incident)
        .options(selectinload(Incident.hypotheses))
        .where(Incident.id == incident_id)
    )
    incident = (await db.execute(incident_stmt)).scalar_one_or_none()

    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Get submitted review
    review_stmt = (
        select(EngineerReview)
        .where(
            EngineerReview.incident_id == incident_id,
            EngineerReview.status == ReviewStatus.SUBMITTED,
        )
        .order_by(desc(EngineerReview.submitted_at))
    )
    review = (await db.execute(review_stmt)).scalar_one_or_none()

    if not review:
        raise HTTPException(
            status_code=404,
            detail="No submitted review found for this incident",
        )

    # Build AI approach summary
    ai_hypotheses = [
        {
            "id": str(h.id),
            "description": h.root_cause,
            "confidence": h.confidence_score,
            "evidence": h.evidence,
        }
        for h in incident.hypotheses
    ]
    ai_confidence = max((h.confidence_score for h in incident.hypotheses), default=0.0)

    # Build comparison
    differences = []
    if review.alternative_hypotheses:
        differences.append(f"Engineer proposed {len(review.alternative_hypotheses)} alternative hypotheses")

    recommendations = []
    if review.engineer_confidence_score and review.engineer_confidence_score > ai_confidence:
        recommendations.append("Engineer has higher confidence - consider engineer approach")
    elif ai_confidence > (review.engineer_confidence_score or 0):
        recommendations.append("AI has higher confidence - consider AI approach")

    return ReviewComparison(
        incident_id=incident_id,
        ai_approach={
            "hypotheses": ai_hypotheses,
            "top_hypothesis": ai_hypotheses[0] if ai_hypotheses else None,
        },
        engineer_approach={
            "assessment": review.ai_confidence_assessment,
            "alternative_hypotheses": review.alternative_hypotheses,
            "suggested_approach": review.suggested_approach,
        },
        ai_confidence=ai_confidence,
        engineer_confidence=review.engineer_confidence_score or 0.0,
        differences=differences if differences else ["Approaches are similar"],
        recommendations=recommendations if recommendations else ["Review both approaches carefully"],
    )


@router.post("/incidents/{incident_id}/choose-approach", response_model=EngineerReviewResponse)
async def make_review_decision(
    incident_id: UUID,
    decision_request: ReviewDecisionRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Make a decision on which approach to execute (AI vs Engineer).

    Records the decision and prepares for execution.
    """
    # Get the review
    review_stmt = (
        select(EngineerReview)
        .where(
            EngineerReview.incident_id == incident_id,
            EngineerReview.status == ReviewStatus.SUBMITTED,
        )
        .order_by(desc(EngineerReview.submitted_at))
    )
    review = (await db.execute(review_stmt)).scalar_one_or_none()

    if not review:
        raise HTTPException(
            status_code=404,
            detail="No submitted review found for this incident",
        )

    if review.decision != ReviewDecision.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Decision already made: {review.decision.value}",
        )

    # Record decision
    review.decision = decision_request.decision
    review.decision_made_at = datetime.utcnow()
    review.decision_rationale = decision_request.rationale

    # Update statuses
    if decision_request.decision == ReviewDecision.ENGINEER_APPROACH:
        review.status = ReviewStatus.ACCEPTED
    elif decision_request.decision == ReviewDecision.AI_APPROACH:
        review.status = ReviewStatus.REJECTED

    # Update engineer workload
    engineer_stmt = select(Engineer).where(Engineer.id == review.engineer_id)
    engineer = (await db.execute(engineer_stmt)).scalar_one_or_none()
    if engineer and engineer.current_review_count > 0:
        engineer.current_review_count -= 1
        if engineer.status == EngineerStatus.ACTIVE:
            engineer.is_available = True

    await db.commit()
    await db.refresh(review)

    logger.info(
        "Review decision made",
        extra={
            "review_id": str(review.id),
            "decision": decision_request.decision.value,
        },
    )
    return review
