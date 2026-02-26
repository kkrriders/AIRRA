"""
Celery task for incident analysis (hypothesis generation + action selection).

Extracted from the /analyze endpoint so LLM work happens in a worker process
instead of blocking the HTTP response. The endpoint now returns 202 immediately
and enqueues this task.
"""
import asyncio
import logging
from uuid import UUID

from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from celery.utils.log import get_task_logger
from sqlalchemy import select

from app.config import settings
from app.core.decision.action_selector import ActionSelector
from app.core.perception.anomaly_detector import AnomalyDetector, categorize_anomaly
from app.core.reasoning.hypothesis_generator import HypothesisGenerator, rank_hypotheses
from app.database import get_db_context
from app.models.action import Action, ActionStatus
from app.models.hypothesis import Hypothesis
from app.models.incident import Incident, IncidentStatus
from app.services.llm_client import get_llm_client
from app.services.prometheus_client import get_prometheus_client
from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    name="app.worker.tasks.analysis.analyze_incident",
    acks_late=True,
)
def analyze_incident(self: Task, incident_id: str) -> dict:
    """
    Run full incident analysis pipeline (Prometheus → anomaly detect → LLM → DB).

    asyncio.run() is the correct pattern here: Celery workers are sync processes,
    so each task creates its own event loop for async SQLAlchemy + httpx calls.
    """
    try:
        return asyncio.run(_run_analysis(incident_id))
    except SoftTimeLimitExceeded:
        logger.error(f"Analysis task soft time limit exceeded for {incident_id}")
        try:
            asyncio.run(_mark_incident_failed(incident_id))
        except Exception as cleanup_exc:
            # Log but do not suppress — the SoftTimeLimitExceeded must still propagate
            # so Celery knows the task was killed and can apply acks_late behaviour.
            logger.error(
                f"Failed to mark incident {incident_id} as FAILED during timeout cleanup: "
                f"{cleanup_exc}"
            )
        raise
    except ValueError as exc:
        # Non-retryable structural error (e.g. malformed UUID in incident_id).
        # Retrying would produce the same result — log and return.
        logger.error(
            f"Analysis task got non-retryable error for {incident_id}: {exc}",
            exc_info=True,
        )
        return {"status": "error", "error": str(exc)}
    except Exception as exc:
        logger.error(
            f"Analysis task failed for {incident_id}: {exc}",
            exc_info=True,
        )
        raise self.retry(exc=exc)


async def _run_analysis(incident_id: str) -> dict:
    """
    Core analysis logic — identical to the former inline endpoint implementation.

    Runs inside an asyncio event loop created by the Celery task wrapper.

    Transaction contract: get_db_context() auto-commits on clean exit and
    rollbacks on exception. This function therefore uses 'return' (not 'raise')
    in error paths that set incident.status = FAILED — letting the context
    manager commit the status update normally. Re-raising would trigger the
    rollback branch, discarding the status update and leaving the incident
    permanently stuck in ANALYZING.
    """
    async with get_db_context() as db:
        stmt = select(Incident).where(Incident.id == UUID(incident_id))
        result = await db.execute(stmt)
        incident = result.scalar_one_or_none()

        if not incident:
            logger.error(f"Incident {incident_id} not found in analysis task")
            return {"status": "error", "message": "Incident not found"}

        if incident.status != IncidentStatus.ANALYZING:
            logger.warning(
                f"Incident {incident_id} is in status {incident.status.value}, "
                "expected ANALYZING — skipping"
            )
            return {"status": "skipped", "reason": "unexpected status"}

        try:
            # Fetch Prometheus metrics for the affected service
            prom_client = get_prometheus_client()
            service_metrics = await prom_client.get_service_metrics(
                service_name=incident.affected_service,
                lookback_minutes=5,
            )

            # Detect anomalies across all metrics
            anomaly_detector = AnomalyDetector(
                threshold_sigma=settings.anomaly_threshold_sigma,
            )
            all_metric_results = []
            for results in service_metrics.values():
                all_metric_results.extend(results)

            anomalies = anomaly_detector.detect_multiple(all_metric_results)

            if not anomalies:
                logger.warning(f"No anomalies detected for incident {incident_id}")
                incident.status = IncidentStatus.RESOLVED
                return {"status": "no_anomalies", "message": "No anomalies in current metrics"}

            # Generate hypotheses via LLM
            llm_client = get_llm_client()
            hypothesis_generator = HypothesisGenerator(llm_client)

            hypotheses_response, llm_response = await hypothesis_generator.generate(
                anomalies=anomalies,
                service_name=incident.affected_service,
                service_context=incident.context.copy(),
            )

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
                service_context=incident.context.copy(),
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

            incident.status = IncidentStatus.PENDING_APPROVAL

            logger.info(
                f"Analysis complete for incident {incident_id}: "
                f"{len(ranked_hypotheses)} hypotheses, "
                f"{llm_response.total_tokens} tokens used"
            )

            return {
                "status": "success",
                "hypotheses_generated": len(ranked_hypotheses),
                "action_recommended": action_recommendation is not None,
                "tokens_used": llm_response.total_tokens,
            }

        except Exception as e:
            logger.error(f"Analysis failed for incident {incident_id}: {e}", exc_info=True)
            incident.status = IncidentStatus.FAILED
            # Return (not raise) so get_db_context sees a clean exit and auto-commits
            # the FAILED status. Raising would trigger the rollback branch, discarding
            # the status update and permanently sticking the incident in ANALYZING.
            return {"status": "failed", "error": str(e)}


async def _mark_incident_failed(incident_id: str) -> None:
    """Mark incident as FAILED when a task is killed by time limit."""
    try:
        async with get_db_context() as db:
            stmt = select(Incident).where(Incident.id == UUID(incident_id))
            result = await db.execute(stmt)
            incident = result.scalar_one_or_none()
            if incident:
                incident.status = IncidentStatus.FAILED
    except Exception as e:
        logger.error(f"Failed to mark incident {incident_id} as FAILED: {e}")
