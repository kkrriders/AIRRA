"""
Unit test for the retention cleanup task (app/worker/tasks/monitoring.py).

Uses the real test_db session (SQLite) so the actual `delete().where(created_at
< cutoff)` query runs, not a mock — the risk here is an off-by-one or wrong
column in the WHERE clause silently deleting (or keeping) the wrong rows.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from app.models.audit_log import AgentAuditLog
from app.models.incident import Incident, IncidentStatus


async def _make_log(db, *, days_old: int) -> AgentAuditLog:
    row = AgentAuditLog(
        event_type="action_approved",
        actor="system",
        outcome="success",
        details={},
    )
    db.add(row)
    await db.flush()
    # created_at is set by TimestampMixin's default; overwrite directly for the test.
    row.created_at = datetime.now(timezone.utc) - timedelta(days=days_old)
    await db.flush()
    return row


async def _age_incident(db, incident: Incident, *, days_old: int) -> Incident:
    incident.created_at = datetime.now(timezone.utc) - timedelta(days=days_old)
    await db.flush()
    return incident


@pytest.mark.asyncio
async def test_retention_cleanup_deletes_only_rows_past_the_window(test_db):
    old_row = await _make_log(test_db, days_old=45)
    new_row = await _make_log(test_db, days_old=5)
    await test_db.commit()

    mock_settings = MagicMock()
    mock_settings.notification_retention_days = 0       # disabled — must not touch notifications
    mock_settings.incident_event_retention_days = 0      # disabled — must not touch incident_events
    mock_settings.audit_log_retention_days = 30          # enabled — 45d old row is past the window
    mock_settings.incident_retention_days = 0             # disabled — must not touch incidents

    with patch("app.config.settings", mock_settings):
        from app.worker.tasks.monitoring import _retention_cleanup
        result = await _retention_cleanup()

    assert result["deleted"] == {"agent_audit_logs": 1}

    remaining = (await test_db.execute(select(AgentAuditLog.id))).scalars().all()
    assert remaining == [new_row.id]
    assert old_row.id not in remaining


@pytest.mark.asyncio
async def test_retention_cleanup_is_a_noop_when_all_windows_disabled(test_db):
    await _make_log(test_db, days_old=9999)
    await test_db.commit()

    mock_settings = MagicMock()
    mock_settings.notification_retention_days = 0
    mock_settings.incident_event_retention_days = 0
    mock_settings.audit_log_retention_days = 0  # default — disabled
    mock_settings.incident_retention_days = 0  # default — disabled

    with patch("app.config.settings", mock_settings):
        from app.worker.tasks.monitoring import _retention_cleanup
        result = await _retention_cleanup()

    assert result["deleted"] == {}
    remaining = (await test_db.execute(select(AgentAuditLog.id))).scalars().all()
    assert len(remaining) == 1


@pytest.mark.asyncio
async def test_retention_cleanup_deletes_terminal_incidents_past_the_window(
    test_db, incident_factory
):
    """A RESOLVED incident older than the window is swept; a recent one is kept."""
    old_resolved = await incident_factory(status=IncidentStatus.RESOLVED)
    await _age_incident(test_db, old_resolved, days_old=45)
    new_resolved = await incident_factory(status=IncidentStatus.RESOLVED)
    await _age_incident(test_db, new_resolved, days_old=5)
    await test_db.commit()

    mock_settings = MagicMock()
    mock_settings.notification_retention_days = 0
    mock_settings.incident_event_retention_days = 0
    mock_settings.audit_log_retention_days = 0
    mock_settings.incident_retention_days = 30

    with patch("app.config.settings", mock_settings):
        from app.worker.tasks.monitoring import _retention_cleanup
        result = await _retention_cleanup()

    assert result["deleted"] == {"incidents": 1}
    remaining = (await test_db.execute(select(Incident.id))).scalars().all()
    assert remaining == [new_resolved.id]


@pytest.mark.asyncio
async def test_retention_cleanup_never_deletes_active_incidents_even_if_old(
    test_db, incident_factory
):
    """PENDING_APPROVAL (non-terminal) must survive the sweep regardless of age."""
    stale_but_active = await incident_factory(status=IncidentStatus.PENDING_APPROVAL)
    await _age_incident(test_db, stale_but_active, days_old=9999)
    await test_db.commit()

    mock_settings = MagicMock()
    mock_settings.notification_retention_days = 0
    mock_settings.incident_event_retention_days = 0
    mock_settings.audit_log_retention_days = 0
    mock_settings.incident_retention_days = 30

    with patch("app.config.settings", mock_settings):
        from app.worker.tasks.monitoring import _retention_cleanup
        result = await _retention_cleanup()

    assert result["deleted"] == {"incidents": 0}
    remaining = (await test_db.execute(select(Incident.id))).scalars().all()
    assert remaining == [stale_but_active.id]


@pytest.mark.asyncio
async def test_retention_cleanup_incidents_disabled_by_default(test_db, incident_factory):
    old_resolved = await incident_factory(status=IncidentStatus.RESOLVED)
    await _age_incident(test_db, old_resolved, days_old=9999)
    await test_db.commit()

    mock_settings = MagicMock()
    mock_settings.notification_retention_days = 0
    mock_settings.incident_event_retention_days = 0
    mock_settings.audit_log_retention_days = 0
    mock_settings.incident_retention_days = 0  # default — disabled

    with patch("app.config.settings", mock_settings):
        from app.worker.tasks.monitoring import _retention_cleanup
        result = await _retention_cleanup()

    assert result["deleted"] == {}
