"""
Additional unit tests for app/services/notification_service.py

Covers DB-driven paths:
- send_incident_notification (lines 73-124)
- _build_incident_message (lines 133-176)
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.models.notification import (
    NotificationChannel,
    NotificationPriority,
    NotificationStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service():
    mock_settings = MagicMock()
    mock_settings.smtp_enabled = False
    mock_settings.smtp_host = "localhost"
    mock_settings.smtp_port = 587
    mock_settings.smtp_username = ""
    mock_settings.smtp_password.get_secret_value.return_value = ""
    mock_settings.smtp_from_email = "airra@test.com"
    mock_settings.smtp_use_tls = False
    mock_settings.frontend_url = "http://localhost:3000"
    mock_settings.slack_webhook_url = ""
    mock_settings.notification_token_secret.get_secret_value.return_value = "test_secret"
    mock_settings.api_key.get_secret_value.return_value = "fallback"

    with patch("app.services.notification_service.settings", mock_settings):
        from app.services.notification_service import NotificationService
        svc = NotificationService()
    return svc


def _mock_engineer(email="eng@co.com", slack_handle=None, name="Alice"):
    eng = MagicMock()
    eng.id = uuid4()
    eng.name = name
    eng.email = email
    eng.slack_handle = slack_handle
    eng.phone = None
    return eng


def _mock_incident(severity="high"):
    inc = MagicMock()
    inc.id = uuid4()
    inc.title = "High Memory Usage"
    inc.affected_service = "payment-service"
    inc.severity = MagicMock()
    inc.severity.value = severity
    inc.status = MagicMock()
    inc.status.value = "analyzing"
    detected_at = MagicMock()
    detected_at.strftime.return_value = "2026-03-11 12:00 UTC"
    inc.detected_at = detected_at
    inc.description = "Memory usage exceeds threshold"
    return inc


def _make_db_with_engineer_and_incident(engineer, incident):
    db = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    notification_id = uuid4()
    call_count = [0]

    async def mock_execute(stmt):
        result = MagicMock()
        if call_count[0] == 0:
            result.scalar_one_or_none.return_value = engineer
        else:
            result.scalar_one_or_none.return_value = incident
        call_count[0] += 1
        return result

    db.execute = mock_execute

    # Mock db.add to capture the notification and assign an id
    def mock_add(obj):
        obj.id = notification_id

    db.add = MagicMock(side_effect=mock_add)
    return db


# ---------------------------------------------------------------------------
# _build_incident_message
# ---------------------------------------------------------------------------

class TestBuildIncidentMessage:
    def test_returns_subject_and_message_tuple(self):
        svc = _make_service()
        eng = _mock_engineer()
        inc = _mock_incident()

        subject, message = svc._build_incident_message(eng, inc, NotificationPriority.HIGH)

        assert isinstance(subject, str)
        assert isinstance(message, str)

    def test_subject_contains_incident_title(self):
        svc = _make_service()
        eng = _mock_engineer()
        inc = _mock_incident()

        subject, _ = svc._build_incident_message(eng, inc, NotificationPriority.CRITICAL)
        assert "High Memory Usage" in subject

    def test_subject_contains_priority(self):
        svc = _make_service()
        eng = _mock_engineer()
        inc = _mock_incident()

        subject, _ = svc._build_incident_message(eng, inc, NotificationPriority.CRITICAL)
        assert "CRITICAL" in subject

    def test_message_contains_engineer_name(self):
        svc = _make_service()
        eng = _mock_engineer(name="Alice")
        inc = _mock_incident()

        _, message = svc._build_incident_message(eng, inc, NotificationPriority.NORMAL)
        assert "Alice" in message

    def test_message_contains_affected_service(self):
        svc = _make_service()
        eng = _mock_engineer()
        inc = _mock_incident()

        _, message = svc._build_incident_message(eng, inc, NotificationPriority.NORMAL)
        assert "payment-service" in message

    def test_message_contains_sla_minutes(self):
        svc = _make_service()
        eng = _mock_engineer()
        inc = _mock_incident()

        _, message = svc._build_incident_message(eng, inc, NotificationPriority.CRITICAL)
        # CRITICAL SLA = 180s = 3 minutes
        assert "3" in message

    def test_all_severity_emoji_values(self):
        svc = _make_service()
        eng = _mock_engineer()

        for severity in ["critical", "high", "medium", "low"]:
            inc = _mock_incident(severity=severity)
            subject, _ = svc._build_incident_message(eng, inc, NotificationPriority.NORMAL)
            assert len(subject) > 0

    def test_unknown_severity_uses_default_emoji(self):
        svc = _make_service()
        eng = _mock_engineer()
        inc = _mock_incident(severity="unknown_sev")

        subject, _ = svc._build_incident_message(eng, inc, NotificationPriority.NORMAL)
        assert "📢" in subject


# ---------------------------------------------------------------------------
# send_incident_notification
# ---------------------------------------------------------------------------

class TestSendIncidentNotification:
    async def test_raises_when_engineer_not_found(self):
        svc = _make_service()
        db = AsyncMock()

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        db.execute = mock_execute

        with pytest.raises(ValueError, match="Engineer"):
            await svc.send_incident_notification(
                db=db,
                engineer_id=uuid4(),
                incident_id=uuid4(),
                channel=NotificationChannel.EMAIL,
                priority=NotificationPriority.HIGH,
            )

    async def test_raises_when_incident_not_found(self):
        svc = _make_service()
        eng = _mock_engineer()
        db = AsyncMock()
        call_count = [0]

        async def mock_execute(stmt):
            result = MagicMock()
            if call_count[0] == 0:
                result.scalar_one_or_none.return_value = eng
            else:
                result.scalar_one_or_none.return_value = None
            call_count[0] += 1
            return result

        db.execute = mock_execute

        with pytest.raises(ValueError, match="Incident"):
            await svc.send_incident_notification(
                db=db,
                engineer_id=eng.id,
                incident_id=uuid4(),
                channel=NotificationChannel.EMAIL,
                priority=NotificationPriority.HIGH,
            )

    async def test_creates_notification_record(self):
        svc = _make_service()
        eng = _mock_engineer()
        inc = _mock_incident()
        db = _make_db_with_engineer_and_incident(eng, inc)

        with patch("app.services.notification_service.token_service") as mock_ts, \
             patch.object(svc, "_send_notification", AsyncMock(return_value=True)):
            mock_ts.generate_token.return_value = ("tok:eng:notif:sig", datetime.now(timezone.utc))
            result = await svc.send_incident_notification(
                db=db,
                engineer_id=eng.id,
                incident_id=inc.id,
                channel=NotificationChannel.EMAIL,
                priority=NotificationPriority.HIGH,
            )

        db.add.assert_called_once()

    async def test_returns_notification_object(self):
        svc = _make_service()
        eng = _mock_engineer()
        inc = _mock_incident()
        db = _make_db_with_engineer_and_incident(eng, inc)

        mock_notif = MagicMock()
        mock_notif.id = uuid4()

        with patch("app.services.notification_service.token_service") as mock_ts, \
             patch("app.services.notification_service.Notification") as mock_notif_cls, \
             patch.object(svc, "_send_notification", AsyncMock(return_value=True)):
            mock_ts.generate_token.return_value = ("tok:eng:notif:sig", datetime.now(timezone.utc))
            mock_notif_cls.return_value = mock_notif
            result = await svc.send_incident_notification(
                db=db,
                engineer_id=eng.id,
                incident_id=inc.id,
                channel=NotificationChannel.EMAIL,
                priority=NotificationPriority.NORMAL,
            )

        assert result is mock_notif

    async def test_slack_channel_creates_notification(self):
        svc = _make_service()
        eng = _mock_engineer(slack_handle="@alice")
        inc = _mock_incident()
        db = _make_db_with_engineer_and_incident(eng, inc)

        with patch("app.services.notification_service.token_service") as mock_ts, \
             patch.object(svc, "_send_notification", AsyncMock(return_value=True)):
            mock_ts.generate_token.return_value = ("tok:eng:notif:sig", datetime.now(timezone.utc))
            result = await svc.send_incident_notification(
                db=db,
                engineer_id=eng.id,
                incident_id=inc.id,
                channel=NotificationChannel.SLACK,
                priority=NotificationPriority.LOW,
            )

        db.add.assert_called_once()
