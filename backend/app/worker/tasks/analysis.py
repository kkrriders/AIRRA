"""
Celery task for incident analysis (hypothesis generation + action selection).

Extracted from the /analyze endpoint so LLM work happens in a worker process
instead of blocking the HTTP response. The endpoint now returns 202 immediately
and enqueues this task.
"""
import asyncio
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
from app.models.audit_log import AuditEventType
from app.models.hypothesis import Hypothesis
from app.models.incident import Incident, IncidentStatus
from app.models.postmortem import Postmortem
from app.services.audit_service import write_audit_log
from app.services.dependency_graph import get_dependency_graph
from app.services.embedding_service import get_embedding_service
from app.services.llm_client import get_llm_client
from app.services.prometheus_client import get_prometheus_client
from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)


def _compute_match_confidence(
    current_service: str,
    current_metric_names: frozenset,
    past_incident: "Incident",
    vector_distance: float,
) -> float:
    """
    Multi-signal composite confidence that a past incident matches the current one.

    Components (weighted sum):
    - Vector similarity  (50%): semantic closeness of incident descriptions.
      Derived from cosine distance ∈ [0,2] → similarity ∈ [0,1].
    - Service match      (30%): same service = 1.0, topologically related = 0.5,
      unrelated = 0.0.  Using the dependency graph avoids penalising cascading
      failures where a DB outage manifests in multiple upstream services.
    - Metric overlap     (20%): Jaccard similarity of anomaly metric names.
      Two incidents with different dominant metrics are unlikely to share a root cause
      even if their text descriptions are similar.

    Returns 0.0–1.0.  Compare against settings.similarity_skip_threshold.
    """
    # 1. Vector similarity
    vector_sim = max(0.0, 1.0 - vector_distance / 2.0)

    # 2. Service match
    if current_service == past_incident.affected_service:
        service_match = 1.0
    else:
        try:
            dep_graph = get_dependency_graph()
            if dep_graph.is_upstream_of(current_service, past_incident.affected_service) \
                    or dep_graph.is_upstream_of(past_incident.affected_service, current_service):
                service_match = 0.5
            else:
                service_match = 0.0
        except Exception:
            service_match = 0.0

    # 3. Metric overlap (Jaccard similarity)
    past_metrics: frozenset = frozenset((past_incident.metrics_snapshot or {}).keys())
    if current_metric_names or past_metrics:
        union = len(current_metric_names | past_metrics)
        metric_overlap = len(current_metric_names & past_metrics) / union if union > 0 else 0.0
    else:
        metric_overlap = 0.5  # No metrics on either side — neutral

    return (vector_sim * 0.5) + (service_match * 0.3) + (metric_overlap * 0.2)


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
            # 5s cap prevents a saturated DB pool from blocking the hard time limit.
            asyncio.run(
                asyncio.wait_for(_mark_incident_failed(incident_id), timeout=5.0)
            )
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
        # NEW-22 fix: use exception type name instead of str(exc) — raw exception
        # messages can contain DB connection strings or file paths and are stored
        # in the Celery result backend (Redis) in plaintext.
        return {"status": "error", "error": type(exc).__name__}
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
                # NEW-6 fix: a clean Prometheus window doesn't mean the incident
                # is resolved — the metrics may have already recovered, or the
                # scrape window may be too narrow. Mark FAILED so a human reviews
                # it rather than silently closing a potentially real incident.
                logger.warning(f"No anomalies detected for incident {incident_id} — marking FAILED for human review")
                incident.status = IncidentStatus.FAILED
                return {"status": "no_anomalies", "message": "No current anomalies — incident needs manual review"}

            # --- Stage 6-7: Semantic similarity retrieval via pgvector ---
            # Generate embedding for the current incident (uses IncidentSummarizer
            # internally — no LLM call, just structured text + sentence-transformers).
            embedding_service = get_embedding_service()
            try:
                query_embedding = embedding_service.embed_incident(incident)
                incident.embedding = query_embedding
                # Persist the embedding now so future incidents can retrieve this one
                # (don't wait for the background embed_incident_task which may not run
                #  until after we need the embedding for retrieval here).
            except Exception as embed_exc:
                logger.warning(f"Could not generate embedding for {incident_id}: {embed_exc}")
                query_embedding = None

            past_context: list[dict] = []
            if query_embedding is not None:
                # --- Item 5: Hybrid retrieval — fetch wider candidate pool ---
                # Fetch 10 candidates by vector distance, then re-rank by composite
                # score (vector + service match + metric overlap) to improve precision.
                similar_stmt = (
                    select(
                        Incident,
                        Postmortem,
                        Incident.embedding.cosine_distance(query_embedding).label("distance"),
                    )
                    .join(Postmortem, Postmortem.incident_id == Incident.id)
                    .where(
                        Incident.status == IncidentStatus.RESOLVED,
                        Incident.id != incident.id,
                        Incident.embedding.isnot(None),
                        # Exclude AI-generated incidents: fictional root causes corrupt RAG
                        Incident.detection_source != "ai_generator",
                    )
                    .order_by(Incident.embedding.cosine_distance(query_embedding))
                    .limit(10)  # wider pool; composite scoring selects top-3 for LLM
                )
                similar_result = await db.execute(similar_stmt)
                similar_rows = similar_result.all()

                if similar_rows:
                    # --- Items 1 & 4: Composite match confidence ---
                    # Re-rank candidates by multi-signal composite confidence so that
                    # a strong vector match from the wrong service is ranked below a
                    # moderate vector match from the same service with matching metrics.
                    current_metric_names: frozenset = frozenset(
                        a.metric_name for a in anomalies
                    )
                    scored_rows = sorted(
                        [
                            (
                                # Composite confidence weighted by the past incident's
                                # trust_score. Human-validated incidents (1.0) get full
                                # weight; auto-detected ones (0.4) are downweighted so
                                # a fictional or low-quality past incident can't dominate
                                # RAG context. See: incident.trust_score column + 008 migration.
                                _compute_match_confidence(
                                    current_service=incident.affected_service,
                                    current_metric_names=current_metric_names,
                                    past_incident=row.Incident,
                                    vector_distance=row.distance or 1.0,
                                ) * float(row.Incident.trust_score),
                                row,
                            )
                            for row in similar_rows
                        ],
                        key=lambda t: t[0],
                        reverse=True,
                    )

                    top_composite, top_row = scored_rows[0]

                    # --- Stage 12 (updated): Cost optimisation — composite skip ---
                    # Only reuse past resolution when ALL three signals agree
                    # (composite >= threshold).  Pure vector similarity alone can
                    # match incidents with similar descriptions but different root
                    # causes (e.g. two services with same title, different upstreams).
                    if top_composite >= settings.similarity_skip_threshold:
                        logger.info(
                            f"Incident {incident_id}: composite confidence {top_composite:.2f} "
                            f"(threshold {settings.similarity_skip_threshold}) matches "
                            f"{top_row.Incident.id} — skipping LLM, reusing past resolution"
                        )
                        incident.context = {
                            **(incident.context or {}),
                            "similarity_skip": {
                                "source_incident_id": str(top_row.Incident.id),
                                "vector_distance": round(top_row.distance or 1.0, 4),
                                "composite_confidence": round(top_composite, 3),
                                "root_cause_reused": top_row.Postmortem.actual_root_cause,
                            },
                        }
                        incident.status = IncidentStatus.PENDING_APPROVAL
                        return {
                            "status": "similarity_skip",
                            "source_incident": str(top_row.Incident.id),
                            "composite_confidence": round(top_composite, 3),
                        }

                    # Pass top-3 (by composite score) as RAG context for LLM
                    past_context = [
                        {
                            "title": row.Incident.title,
                            "root_cause": row.Postmortem.actual_root_cause,
                            "resolved_at": (
                                row.Incident.resolved_at.isoformat()
                                if row.Incident.resolved_at
                                else None
                            ),
                            "composite_confidence": round(composite, 3),
                        }
                        for composite, row in scored_rows[:3]
                    ]
                    logger.info(
                        f"Hybrid retrieval found {len(similar_rows)} candidates, "
                        f"top-3 selected (composite scores: "
                        f"{[round(s, 2) for s, _ in scored_rows[:3]]}) for {incident_id}"
                    )
            else:
                # Fallback: same-service time-sort when embedding unavailable
                fallback_stmt = (
                    select(Incident, Postmortem)
                    .join(Postmortem, Postmortem.incident_id == Incident.id)
                    .where(
                        Incident.affected_service == incident.affected_service,
                        Incident.status == IncidentStatus.RESOLVED,
                        Incident.id != incident.id,
                    )
                    .order_by(Incident.resolved_at.desc())
                    .limit(3)
                )
                fallback_result = await db.execute(fallback_stmt)
                past_context = [
                    {
                        "title": row.Incident.title,
                        "root_cause": row.Postmortem.actual_root_cause,
                        "resolved_at": (
                            row.Incident.resolved_at.isoformat()
                            if row.Incident.resolved_at
                            else None
                        ),
                    }
                    for row in fallback_result.all()
                ]
                logger.info(f"Embedding unavailable — using fallback time-sort retrieval for {incident_id}")

            # Generate hypotheses via LLM
            llm_client = get_llm_client()
            hypothesis_generator = HypothesisGenerator(llm_client)

            service_context = incident.context.copy()
            hypotheses_response, llm_response = await hypothesis_generator.generate(
                anomalies=anomalies,
                service_name=incident.affected_service,
                service_context=service_context.copy(),  # NEW-1: independent copy per callsite
                past_context=past_context,
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

            # Generate action recommendation for top hypothesis.
            # I2 fix: guard against LLM returning zero hypotheses.
            action_recommendation = None
            if not ranked_hypotheses:
                logger.warning(
                    f"LLM returned no hypotheses for incident {incident_id} — "
                    "skipping action selection"
                )
            else:
                action_selector = ActionSelector()
                top_hypothesis = ranked_hypotheses[0][1]
                action_recommendation = action_selector.select(
                    hypothesis=top_hypothesis,
                    service_name=incident.affected_service,
                    service_context=service_context.copy(),  # NEW-1: independent copy per callsite
                )

                # PolicyEngine veto — write audit entry so operators can see
                # why no action was proposed (not a silent drop).
                if action_recommendation is None and action_selector.last_policy_veto:
                    await write_audit_log(
                        db,
                        AuditEventType.POLICY_BLOCKED,
                        actor="system",
                        outcome="blocked",
                        incident_id=incident.id,
                        action_id=None,
                        details={
                            "veto_reason": action_selector.last_policy_veto,
                            "hypothesis_category": top_hypothesis.category,
                            "target_service": incident.affected_service,
                        },
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
            # NEW-22 fix: store exception type name, not raw message (Celery result backend).
            return {"status": "failed", "error": type(e).__name__}


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
