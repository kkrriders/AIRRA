"""
Unit tests for app/services/audit_service.py

Uses AsyncMock for DB sessions.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.models.audit_log import AgentAuditLog, AuditEventType
from app.services.audit_service import write_audit_log


INCIDENT_ID = uuid4()
ACTION_ID = uuid4()


class TestWriteAuditLog:
    async def test_adds_entry_to_session(self):
        db = AsyncMock()
        await write_audit_log(
            db=db,
            event_type=AuditEventType.ANALYSIS_COMPLETE,
            actor="airra-bot",
            outcome="success",
        )
        db.add.assert_called_once()

    async def test_with_incident_id(self):
        db = AsyncMock()
        await write_audit_log(
            db=db,
            event_type=AuditEventType.ANALYSIS_COMPLETE,
            actor="system",
            outcome="success",
            incident_id=INCIDENT_ID,
        )
        call_args = db.add.call_args[0][0]
        assert isinstance(call_args, AgentAuditLog)
        assert call_args.incident_id == INCIDENT_ID

    async def test_with_action_id(self):
        db = AsyncMock()
        await write_audit_log(
            db=db,
            event_type=AuditEventType.ACTION_APPROVED,
            actor="alice@co.com",
            outcome="success",
            action_id=ACTION_ID,
        )
        call_args = db.add.call_args[0][0]
        assert call_args.action_id == ACTION_ID

    async def test_details_defaults_to_empty_dict(self):
        db = AsyncMock()
        await write_audit_log(
            db=db,
            event_type=AuditEventType.ANALYSIS_COMPLETE,
            actor="system",
            outcome="success",
            details=None,
        )
        call_args = db.add.call_args[0][0]
        assert call_args.details == {}

    async def test_with_details(self):
        db = AsyncMock()
        await write_audit_log(
            db=db,
            event_type=AuditEventType.ACTION_EXECUTE_SUCCEEDED,
            actor="airra-bot",
            outcome="failure",
            details={"error": "timeout"},
        )
        call_args = db.add.call_args[0][0]
        assert call_args.details == {"error": "timeout"}

    async def test_exception_does_not_propagate(self):
        """Audit failures must never break the surrounding business operation."""
        db = AsyncMock()
        db.add.side_effect = Exception("DB connection lost")
        # Should NOT raise
        await write_audit_log(
            db=db,
            event_type=AuditEventType.ANALYSIS_COMPLETE,
            actor="system",
            outcome="success",
        )

    async def test_actor_and_outcome_set(self):
        db = AsyncMock()
        await write_audit_log(
            db=db,
            event_type=AuditEventType.ANALYSIS_COMPLETE,
            actor="bob@co.com",
            outcome="blocked",
        )
        call_args = db.add.call_args[0][0]
        assert call_args.actor == "bob@co.com"
        assert call_args.outcome == "blocked"

    async def test_event_type_set(self):
        db = AsyncMock()
        await write_audit_log(
            db=db,
            event_type=AuditEventType.ACTION_APPROVED,
            actor="alice",
            outcome="success",
        )
        call_args = db.add.call_args[0][0]
        assert call_args.event_type == AuditEventType.ACTION_APPROVED

    async def test_raw_string_event_type(self):
        """event_type can be a raw string for extensibility."""
        db = AsyncMock()
        await write_audit_log(
            db=db,
            event_type="custom_event",
            actor="system",
            outcome="success",
        )
        call_args = db.add.call_args[0][0]
        assert call_args.event_type == "custom_event"
