"""
WebSocket endpoint for real-time incident status streaming.

WS /api/v1/incidents/{id}/stream

Architecture:
  - FastAPI WebSocket accepts the connection and sends the current incident state.
  - A dedicated Redis pub/sub subscriber listens on channel `incident:{id}:events`.
  - When Celery tasks (analysis, escalation, verification) change incident status,
    they publish JSON events to that channel.
  - This endpoint forwards those events to the browser immediately.

This decouples the LLM analysis pipeline from the WebSocket — Celery workers
publish, FastAPI subscribes and fans out. Neither side knows about the other.

Message types sent to client:
  {"type": "connected",      "incident_id": "...", "current_status": "ANALYZING"}
  {"type": "status_update",  "incident_id": "...", "status": "PENDING_APPROVAL", "timestamp": "..."}
  {"type": "hypothesis_ready","incident_id": "...", "hypothesis_count": 2, "top_category": "memory_leak"}
  {"type": "error",          "message": "Incident not found"}
"""
import json
import logging
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.config import settings
from app.database import get_db_context

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/{incident_id}/stream")
async def stream_incident(websocket: WebSocket, incident_id: UUID):
    """Stream real-time incident status updates to the browser."""
    await websocket.accept()

    # Fetch current incident state to send on connect
    async with get_db_context() as db:
        from app.models.incident import Incident
        incident = (
            await db.execute(select(Incident).where(Incident.id == incident_id))
        ).scalar_one_or_none()

    if not incident:
        await websocket.send_json({"type": "error", "message": "Incident not found"})
        await websocket.close(code=4004)
        return

    await websocket.send_json({
        "type": "connected",
        "incident_id": str(incident_id),
        "current_status": incident.status.value,
        "affected_service": incident.affected_service,
        "severity": incident.severity.value,
    })

    # Create a SEPARATE Redis client for pub/sub — pub/sub occupies the
    # connection exclusively and must not share the application-wide pool.
    pubsub_redis = aioredis.from_url(
        str(settings.redis_url),
        encoding="utf-8",
        decode_responses=True,
    )
    pubsub = pubsub_redis.pubsub()
    channel = f"incident:{incident_id}:events"

    try:
        await pubsub.subscribe(channel)
        logger.info("WebSocket subscribed to %s", channel)

        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            try:
                await websocket.send_text(message["data"])
            except WebSocketDisconnect:
                break

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected from %s", channel)
    except Exception as exc:
        logger.error("WebSocket stream error for %s: %s", incident_id, exc)
        try:
            await websocket.send_json({"type": "error", "message": "Stream error"})
        except Exception:
            pass
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub_redis.aclose()
