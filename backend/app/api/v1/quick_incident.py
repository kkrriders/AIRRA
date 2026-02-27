"""
Quick Incident Creation with Auto-Analysis.

One-click incident creation that automatically:
1. Creates the incident
2. Detects anomalies (or uses provided data)
3. Generates hypotheses using LLM
4. Recommends actions

Perfect for UI workflows where users want immediate results.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException  # noqa: F811
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.decision.action_selector import ActionSelector
from app.core.perception.anomaly_detector import AnomalyDetector, categorize_anomaly
from app.core.reasoning.hypothesis_generator import HypothesisGenerator, rank_hypotheses
from app.database import get_db
from app.models.action import Action, ActionStatus
from app.models.hypothesis import Hypothesis
from app.models.incident import Incident, IncidentSeverity, IncidentStatus
from app.schemas.incident import IncidentWithRelations
from app.api.rate_limit import llm_rate_limit
from app.services.llm_client import get_llm_client
from app.services.prometheus_client import get_prometheus_client

logger = logging.getLogger(__name__)

router = APIRouter()


class QuickIncidentRequest(BaseModel):
    """Request to create and auto-analyze an incident in one call."""

    service_name: str = Field(..., description="Service experiencing the incident")
    title: str | None = Field(None, description="Optional custom title")
    description: str | None = Field(None, description="Optional custom description")
    severity: IncidentSeverity = Field(
        default=IncidentSeverity.MEDIUM,
        description="Incident severity (will be auto-detected if not provided)",
    )

    # Optional: Provide known metrics instead of querying Prometheus
    metrics_snapshot: dict | None = Field(
        None,
        description="Optional: Provide metrics directly (bypasses Prometheus)",
    )

    # Optional: Additional context
    context: dict = Field(
        default_factory=dict,
        description="Additional context (recent deployments, etc.)",
    )


@router.post(
    "/quick-incident",
    response_model=IncidentWithRelations,
    status_code=201,
    dependencies=[Depends(llm_rate_limit)],
)
async def create_and_analyze_incident(
    request: QuickIncidentRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Create an incident and immediately analyze it with LLM.

    This is a convenience endpoint that combines:
    1. Incident creation
    2. Anomaly detection (from Prometheus or provided metrics)
    3. LLM hypothesis generation
    4. Action recommendation

    Perfect for UI workflows where users want immediate results.

    Returns the complete incident with hypotheses and actions.
    """
    try:
        logger.info(f"Quick incident creation for service: {request.service_name}")

        # ========================================
        # Step 1: Detect or Use Provided Metrics
        # ========================================
        anomalies = []
        metrics_snapshot = request.metrics_snapshot or {}

        if not request.metrics_snapshot:
            # Try to fetch from Prometheus
            try:
                logger.info(f"Fetching metrics from Prometheus for {request.service_name}")
                prom_client = get_prometheus_client()
                service_metrics = await prom_client.get_service_metrics(
                    service_name=request.service_name,
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

                # Build metrics snapshot from anomalies
                if anomalies:
                    for anomaly in anomalies:
                        metrics_snapshot[anomaly.metric_name] = {
                            "current": anomaly.current_value,
                            "expected": anomaly.expected_value,
                            "deviation": anomaly.deviation_sigma,
                        }

                logger.info(f"Detected {len(anomalies)} anomalies from Prometheus")

            except Exception as e:
                logger.warning(f"Could not fetch from Prometheus: {str(e)}")
                logger.info("Will create incident with provided/simulated data")

        # If still no metrics, create simulated anomalies based on service name
        # Only allow simulation in non-production environments to prevent false incidents
        if not anomalies:
            if settings.environment == "production":
                raise HTTPException(
                    status_code=503,
                    detail="No anomalies detected and Prometheus data unavailable. "
                    "Cannot create incident without real metrics in production.",
                )

            logger.info("No Prometheus data - creating simulated anomalies for analysis (non-production)")
            anomalies = create_simulated_anomalies(request.service_name, metrics_snapshot)
            # Update metrics snapshot with simulated anomalies if it was empty
            if not metrics_snapshot:
                for anomaly in anomalies:
                    metrics_snapshot[anomaly.metric_name] = {
                        "current": anomaly.current_value,
                        "expected": anomaly.expected_value,
                        "deviation": anomaly.deviation_sigma,
                    }

        # ========================================
        # Step 2: Auto-generate Title & Description
        # ========================================
        if not request.title:
            anomaly_categories = [categorize_anomaly(a) for a in anomalies[:3]]
            categories_str = ', '.join(anomaly_categories[:2]) if anomaly_categories else "Issue"
            request.title = f"Anomalies detected in {request.service_name}: {categories_str}"

        if not request.description:
            anomaly_summaries = []
            for a in anomalies[:5]:
                category = categorize_anomaly(a)
                anomaly_summaries.append(
                    f"- {a.metric_name}: {category} ({a.deviation_sigma:.1f}σ deviation)"
                )
            if not anomaly_summaries:
                anomaly_summaries = ["No specific anomalies detailed."]
            request.description = "Auto-detected anomalies:\n" + "\n".join(anomaly_summaries)

        # Auto-detect severity based on anomalies
        if anomalies:
            max_deviation = max(a.deviation_sigma for a in anomalies)
            if max_deviation >= 5.0:
                request.severity = IncidentSeverity.CRITICAL
            elif max_deviation >= 4.0:
                request.severity = IncidentSeverity.HIGH
            elif max_deviation >= 3.0:
                request.severity = IncidentSeverity.MEDIUM
            else:
                request.severity = IncidentSeverity.LOW

        # ========================================
        # Step 3: Create Incident
        # ========================================
        incident = Incident(
            title=request.title,
            description=request.description,
            severity=request.severity,
            status=IncidentStatus.ANALYZING,  # Start in analyzing state
            affected_service=request.service_name,
            affected_components=[request.service_name],
            detected_at=datetime.now(timezone.utc),
            detection_source="quick_incident_ui",
            metrics_snapshot=metrics_snapshot,
            context=request.context or {},
        )

        db.add(incident)
        await db.flush()  # Get the incident ID

        logger.info(f"Created incident {incident.id} for {request.service_name}")

        # ========================================
        # Step 4: Generate Hypotheses with LLM
        # ========================================
        try:
            logger.info("Generating hypotheses with LLM...")

            llm_client = get_llm_client()
            hypothesis_generator = HypothesisGenerator(llm_client)

            service_context = request.context.copy()
            service_context["service_name"] = request.service_name

            hypotheses_response, llm_response = await hypothesis_generator.generate(
                anomalies=anomalies,
                service_name=request.service_name,
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

            logger.info(f"Generated {len(ranked_hypotheses)} hypotheses")

            # ========================================
            # Step 5: Generate Action Recommendation
            # ========================================
            action_selector = ActionSelector()
            top_hypothesis = ranked_hypotheses[0][1]

            action_recommendation = action_selector.select(
                hypothesis=top_hypothesis,
                service_name=request.service_name,
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
                logger.info("Generated action recommendation")

            # Update incident status
            incident.status = IncidentStatus.PENDING_APPROVAL

        except Exception as e:
            logger.error(f"Analysis failed: {str(e)}", exc_info=True)
            incident.status = IncidentStatus.FAILED
            incident.context["error"] = str(e)
            # Continue to return the incident even if analysis failed

        # ========================================
        # Step 6: Commit and Return
        # ========================================
        await db.commit()

        # Reload incident with relations
        await db.refresh(incident)

        # Manually load relationships
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        stmt = (
            select(Incident)
            .where(Incident.id == incident.id)
            .options(selectinload(Incident.hypotheses), selectinload(Incident.actions))
        )
        result = await db.execute(stmt)
        incident_with_relations = result.scalar_one()

        logger.info(
            f"Quick incident complete: {incident.id} "
            f"({len(incident_with_relations.hypotheses)} hypotheses, "
            f"{len(incident_with_relations.actions)} actions)"
        )

        return incident_with_relations

    except Exception as e:
        logger.error(f"Quick incident creation failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create and analyze incident: {str(e)}",
        )


def create_simulated_anomalies(service_name: str, metrics_snapshot: dict):
    """Create simulated anomalies when Prometheus is not available."""
    from app.core.perception.anomaly_detector import AnomalyDetection

    # If metrics provided, use them
    if metrics_snapshot:
        anomalies = []
        base_timestamp = datetime.now(timezone.utc)

        for metric_name, value in metrics_snapshot.items():
            if isinstance(value, (int, float)):
                # Simple metric
                anomalies.append(
                    AnomalyDetection(
                        metric_name=metric_name,
                        is_anomaly=True,
                        current_value=value,
                        expected_value=value * 0.5,  # Assume 2x is anomalous
                        deviation_sigma=4.0,
                        confidence=0.85,
                        timestamp=base_timestamp,
                        context={"labels": {"service": service_name}},
                    )
                )
            elif isinstance(value, dict) and "current" in value:
                # Detailed metric
                anomalies.append(
                    AnomalyDetection(
                        metric_name=metric_name,
                        is_anomaly=True,
                        current_value=value["current"],
                        expected_value=value.get("expected", value["current"] * 0.5),
                        deviation_sigma=value.get("deviation", 4.0),
                        confidence=0.85,
                        timestamp=base_timestamp,
                        context={"labels": {"service": service_name}},
                    )
                )

        return anomalies

    # Create default simulated anomalies based on service type
    logger.info(f"Creating default simulated anomalies for {service_name}")

    return [
        AnomalyDetection(
            metric_name="memory_usage_bytes",
            is_anomaly=True,
            current_value=8589934592,  # 8GB
            expected_value=2147483648,  # 2GB
            deviation_sigma=4.5,
            confidence=0.90,
            timestamp=datetime.now(timezone.utc),
            context={"labels": {"service": service_name}},
        ),
        AnomalyDetection(
            metric_name="http_request_duration_seconds_p95",
            is_anomaly=True,
            current_value=3.2,
            expected_value=0.5,
            deviation_sigma=4.2,
            confidence=0.88,
            timestamp=datetime.now(timezone.utc),
            context={"labels": {"service": service_name}},
        ),
        AnomalyDetection(
            metric_name="http_requests_total",
            is_anomaly=True,
            current_value=1250,
            expected_value=500,
            deviation_sigma=3.8,
            confidence=0.85,
            timestamp=datetime.now(timezone.utc),
            context={"labels": {"service": service_name, "status": "500"}},
        ),
    ]
