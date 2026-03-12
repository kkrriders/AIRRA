"""
Unit tests for app/services/event_logger.py

Uses AsyncMock for DB sessions — no real DB needed.
"""
from unittest.mock import AsyncMock
from uuid import uuid4

from app.models.incident_event import IncidentEventType
from app.services.event_logger import EventLogger, event_logger

INCIDENT_ID = uuid4()


class TestEventLoggerLog:
    async def test_log_creates_event_and_flushes(self):
        db = AsyncMock()
        db.flush = AsyncMock()
        logger = EventLogger()
        await logger.log(
            db=db,
            incident_id=INCIDENT_ID,
            event_type=IncidentEventType.DETECTED,
            description="Incident detected",
        )
        db.add.assert_called_once()
        db.flush.assert_awaited_once()

    async def test_log_returns_incident_event(self):
        db = AsyncMock()
        logger = EventLogger()
        event = await logger.log(
            db=db,
            incident_id=INCIDENT_ID,
            event_type=IncidentEventType.DETECTED,
            description="Incident detected",
        )
        from app.models.incident_event import IncidentEvent
        assert isinstance(event, IncidentEvent)

    async def test_log_actor_defaults_to_system(self):
        db = AsyncMock()
        logger = EventLogger()
        event = await logger.log(
            db=db,
            incident_id=INCIDENT_ID,
            event_type=IncidentEventType.DETECTED,
            description="Detected",
            actor=None,
        )
        assert event.actor == "system"

    async def test_log_custom_actor(self):
        db = AsyncMock()
        logger = EventLogger()
        event = await logger.log(
            db=db,
            incident_id=INCIDENT_ID,
            event_type=IncidentEventType.DETECTED,
            description="Detected",
            actor="alice@company.com",
        )
        assert event.actor == "alice@company.com"

    async def test_log_metadata_defaults_to_empty_dict(self):
        db = AsyncMock()
        logger = EventLogger()
        event = await logger.log(
            db=db,
            incident_id=INCIDENT_ID,
            event_type=IncidentEventType.DETECTED,
            description="Detected",
            metadata=None,
        )
        assert event.event_metadata == {}

    async def test_log_with_metadata(self):
        db = AsyncMock()
        logger = EventLogger()
        event = await logger.log(
            db=db,
            incident_id=INCIDENT_ID,
            event_type=IncidentEventType.HYPOTHESES_GENERATED,
            description="Hypotheses generated",
            metadata={"count": 3},
        )
        assert event.event_metadata == {"count": 3}

    async def test_log_event_type_set_correctly(self):
        db = AsyncMock()
        logger = EventLogger()
        event = await logger.log(
            db=db,
            incident_id=INCIDENT_ID,
            event_type=IncidentEventType.INCIDENT_RESOLVED,
            description="Resolved",
        )
        assert event.event_type == IncidentEventType.INCIDENT_RESOLVED

    async def test_log_incident_id_set(self):
        db = AsyncMock()
        logger = EventLogger()
        event = await logger.log(
            db=db,
            incident_id=INCIDENT_ID,
            event_type=IncidentEventType.DETECTED,
            description="Detected",
        )
        assert event.incident_id == INCIDENT_ID

    async def test_log_description_set(self):
        db = AsyncMock()
        logger = EventLogger()
        event = await logger.log(
            db=db,
            incident_id=INCIDENT_ID,
            event_type=IncidentEventType.DETECTED,
            description="Custom description here",
        )
        assert event.description == "Custom description here"


class TestEventLoggerConvenienceMethods:
    async def test_log_detected(self):
        db = AsyncMock()
        logger = EventLogger()
        event = await logger.log_detected(
            db=db,
            incident_id=INCIDENT_ID,
            description="Detected issue",
        )
        assert event.event_type == IncidentEventType.DETECTED
        assert event.actor == "system"

    async def test_log_detected_with_metadata(self):
        db = AsyncMock()
        logger = EventLogger()
        event = await logger.log_detected(
            db=db,
            incident_id=INCIDENT_ID,
            description="Detected",
            metadata={"source": "prometheus"},
        )
        assert event.event_metadata == {"source": "prometheus"}

    async def test_log_hypotheses_generated(self):
        db = AsyncMock()
        logger = EventLogger()
        event = await logger.log_hypotheses_generated(
            db=db,
            incident_id=INCIDENT_ID,
            hypothesis_count=3,
            top_confidence=0.87,
        )
        assert event.event_type == IncidentEventType.HYPOTHESES_GENERATED
        assert event.actor == "airra-bot"
        assert "3" in event.description
        assert event.event_metadata["count"] == 3
        assert event.event_metadata["top_confidence"] == 0.87

    async def test_log_engineer_assigned(self):
        db = AsyncMock()
        logger = EventLogger()
        event = await logger.log_engineer_assigned(
            db=db,
            incident_id=INCIDENT_ID,
            engineer_name="Alice",
            engineer_email="alice@co.com",
        )
        assert event.event_type == IncidentEventType.ENGINEER_ASSIGNED
        assert "Alice" in event.description
        assert event.event_metadata["engineer_email"] == "alice@co.com"

    async def test_log_action_approved(self):
        db = AsyncMock()
        logger = EventLogger()
        event = await logger.log_action_approved(
            db=db,
            incident_id=INCIDENT_ID,
            action_type="restart_pod",
            approver_email="approver@co.com",
        )
        assert event.event_type == IncidentEventType.ACTION_APPROVED
        assert event.actor == "approver@co.com"
        assert "restart_pod" in event.description

    async def test_log_action_executed_success(self):
        db = AsyncMock()
        logger = EventLogger()
        event = await logger.log_action_executed(
            db=db,
            incident_id=INCIDENT_ID,
            action_type="scale_up",
            success=True,
        )
        assert event.event_type == IncidentEventType.ACTION_COMPLETED
        assert "completed successfully" in event.description

    async def test_log_action_executed_failure(self):
        db = AsyncMock()
        logger = EventLogger()
        event = await logger.log_action_executed(
            db=db,
            incident_id=INCIDENT_ID,
            action_type="rollback",
            success=False,
            details={"error": "timeout"},
        )
        assert event.event_type == IncidentEventType.ACTION_FAILED
        assert "failed" in event.description
        assert event.event_metadata == {"error": "timeout"}

    async def test_log_action_executed_no_details(self):
        db = AsyncMock()
        logger = EventLogger()
        event = await logger.log_action_executed(
            db=db,
            incident_id=INCIDENT_ID,
            action_type="restart_pod",
            success=True,
            details=None,
        )
        assert event.event_metadata == {}

    async def test_log_verification_passed(self):
        db = AsyncMock()
        logger = EventLogger()
        event = await logger.log_verification(
            db=db,
            incident_id=INCIDENT_ID,
            passed=True,
            metrics={"cpu_after": 40},
        )
        assert event.event_type == IncidentEventType.VERIFICATION_PASSED
        assert "passed" in event.description

    async def test_log_verification_failed(self):
        db = AsyncMock()
        logger = EventLogger()
        event = await logger.log_verification(
            db=db,
            incident_id=INCIDENT_ID,
            passed=False,
        )
        assert event.event_type == IncidentEventType.VERIFICATION_FAILED
        assert "failed" in event.description
        assert event.event_metadata == {}

    async def test_log_resolved(self):
        db = AsyncMock()
        logger = EventLogger()
        event = await logger.log_resolved(
            db=db,
            incident_id=INCIDENT_ID,
            resolution_time_minutes=25,
        )
        assert event.event_type == IncidentEventType.INCIDENT_RESOLVED
        assert "25" in event.description
        assert event.event_metadata["resolution_time_minutes"] == 25

    async def test_log_comment_short(self):
        db = AsyncMock()
        logger = EventLogger()
        event = await logger.log_comment(
            db=db,
            incident_id=INCIDENT_ID,
            comment="Short comment.",
            author_email="bob@co.com",
        )
        assert event.event_type == IncidentEventType.COMMENT_ADDED
        assert "Short comment." in event.description
        assert event.actor == "bob@co.com"
        assert event.event_metadata["full_comment"] == "Short comment."

    async def test_log_comment_long_truncated(self):
        db = AsyncMock()
        logger = EventLogger()
        long_comment = "x" * 200
        event = await logger.log_comment(
            db=db,
            incident_id=INCIDENT_ID,
            comment=long_comment,
            author_email="bob@co.com",
        )
        assert "..." in event.description
        assert event.event_metadata["full_comment"] == long_comment


class TestEventLoggerGlobalInstance:
    def test_global_instance_exists(self):
        assert event_logger is not None
        assert isinstance(event_logger, EventLogger)
