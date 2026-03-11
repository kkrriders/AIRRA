"""
Celery task for generating and storing incident embeddings.

Called after incident creation (anomaly_monitor, API) and after resolution
(learning_engine) to keep embeddings rich with outcome context.
"""
import asyncio
from uuid import UUID

from celery.utils.log import get_task_logger
from sqlalchemy import select

from app.database import get_db_context
from app.models.incident import Incident
from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)


@celery_app.task(
    name="embed_incident",
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def embed_incident_task(incident_id: str, extra_context: dict | None = None) -> dict:
    """
    Generate and persist a vector embedding for an incident.

    Args:
        incident_id: UUID string of the incident to embed.
        extra_context: Optional enrichment dict (e.g. resolved incidents get
                       {"actual_root_cause": "...", "resolution": "..."}).

    Returns:
        {"status": "ok"} on success, {"status": "error", "error": ...} on failure.
    """
    try:
        return asyncio.run(_embed(incident_id, extra_context))
    except Exception as exc:
        logger.error(f"embed_incident_task failed for {incident_id}: {exc}", exc_info=True)
        raise embed_incident_task.retry(exc=exc)


async def _embed(incident_id: str, extra_context: dict | None) -> dict:
    """Async core: load incident → summarize → embed → persist."""
    from app.services.embedding_service import get_embedding_service

    async with get_db_context() as db:
        stmt = select(Incident).where(Incident.id == UUID(incident_id))
        result = await db.execute(stmt)
        incident = result.scalar_one_or_none()

        if not incident:
            logger.warning(f"embed_incident: incident {incident_id} not found — skipping")
            return {"status": "not_found"}

        embedding_service = get_embedding_service()

        # SentenceTransformer.encode() is CPU-bound and blocking.
        # Run in a thread pool so we don't block the event loop's I/O.
        import asyncio
        loop = asyncio.get_running_loop()
        vector = await loop.run_in_executor(
            None,  # default ThreadPoolExecutor
            lambda: embedding_service.embed_incident(incident, extra_context=extra_context),
        )

        incident.embedding = vector
        await db.commit()

        logger.info(
            f"Embedded incident {incident_id} "
            f"({'with extra context' if extra_context else 'initial embedding'})"
        )
        return {"status": "ok", "dims": len(vector)}
