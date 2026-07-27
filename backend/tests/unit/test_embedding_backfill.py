"""
Unit test for the on-demand embedding backfill task (app/worker/tasks/embedding.py).

Verifies it queues embed_incident_task for incidents with a NULL embedding
only — the whole point of the task is to find the gap, not to re-embed
everything.
"""
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from app.models.incident import Incident, IncidentSeverity, IncidentStatus


def _make_incident(*, embedding: list[float] | None) -> Incident:
    return Incident(
        id=uuid4(),
        title="High memory usage",
        description="test",
        status=IncidentStatus.RESOLVED,
        severity=IncidentSeverity.HIGH,
        affected_service="payment-service",
        detected_at=datetime.now(timezone.utc),
        embedding=embedding,
    )


async def test_backfill_queues_only_incidents_missing_an_embedding(test_db):
    missing = _make_incident(embedding=None)
    present = _make_incident(embedding=[0.1] * 384)
    test_db.add_all([missing, present])
    await test_db.commit()

    with patch("app.worker.tasks.embedding.embed_incident_task") as mock_task:
        from app.worker.tasks.embedding import _backfill_missing
        result = await _backfill_missing(batch_size=200)

    assert result == {"status": "ok", "queued": 1}
    mock_task.delay.assert_called_once_with(str(missing.id))
