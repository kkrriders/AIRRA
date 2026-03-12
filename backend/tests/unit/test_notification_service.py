"""
Unit tests for app/services/notification_service.py

Covers pure-logic helpers and send-path using mocked DB/SMTP/httpx.
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


def _make_service():
    """Create NotificationService with patched settings."""
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
    mock_settings.notification_token_secret.get_secret_value.return_value = "test_secret_key"
    mock_settings.api_key.get_secret_value.return_value = "api_key_fallback"

    with patch("app.services.notification_service.settings", mock_settings):
        from app.services.notification_service import NotificationService
        svc = NotificationService()
        # Also patch token_service to avoid needing real settings
        svc._token_service_patched = True
    return svc


def _mock_engineer(email="eng@co.com", slack_handle=None, phone=None):
    eng = MagicMock()
    eng.id = uuid4()
    eng.name = "Alice"
    eng.email = email
    eng.slack_handle = slack_handle
    eng.phone = phone
    return eng


def _mock_notification(channel=NotificationChannel.EMAIL):
    notif = MagicMock()
    notif.id = uuid4()
    notif.channel = channel
    notif.subject = "Incident Alert"
    notif.message = "Memory leak detected {{admin_panel_url}}"
    notif.recipient_address = "eng@co.com"
    notif.status = NotificationStatus.PENDING
    notif.retry_count = 0
    notif.max_retries = 3
    return notif


def _mock_incident():
    inc = MagicMock()
    inc.id = uuid4()
    inc.title = "High Memory Usage"
    inc.affected_service = "payment-service"
    inc.severity = MagicMock()
    inc.severity.value = "high"
    inc.status = MagicMock()
    inc.status.value = "analyzing"
    inc.detected_at = datetime.now(timezone.utc)
    inc.description = "Memory usage exceeds threshold"
    return inc


class TestGetSlaTarget:
    def test_critical_is_180s(self):
        from app.services.notification_service import NotificationService
        with patch("app.services.notification_service.settings", MagicMock(
            smtp_enabled=False,
            smtp_password=MagicMock(get_secret_value=lambda: ""),
            smtp_host="", smtp_port=587, smtp_username="",
            smtp_from_email="", smtp_use_tls=False, frontend_url="",
        )):
            svc = NotificationService()
        assert svc._get_sla_target(NotificationPriority.CRITICAL) == 180

    def test_high_is_300s(self):
        from app.services.notification_service import NotificationService
        with patch("app.services.notification_service.settings", MagicMock(
            smtp_enabled=False,
            smtp_password=MagicMock(get_secret_value=lambda: ""),
            smtp_host="", smtp_port=587, smtp_username="",
            smtp_from_email="", smtp_use_tls=False, frontend_url="",
        )):
            svc = NotificationService()
        assert svc._get_sla_target(NotificationPriority.HIGH) == 300

    def test_normal_is_600s(self):
        from app.services.notification_service import NotificationService
        with patch("app.services.notification_service.settings", MagicMock(
            smtp_enabled=False,
            smtp_password=MagicMock(get_secret_value=lambda: ""),
            smtp_host="", smtp_port=587, smtp_username="",
            smtp_from_email="", smtp_use_tls=False, frontend_url="",
        )):
            svc = NotificationService()
        assert svc._get_sla_target(NotificationPriority.NORMAL) == 600

    def test_low_is_1800s(self):
        from app.services.notification_service import NotificationService
        with patch("app.services.notification_service.settings", MagicMock(
            smtp_enabled=False,
            smtp_password=MagicMock(get_secret_value=lambda: ""),
            smtp_host="", smtp_port=587, smtp_username="",
            smtp_from_email="", smtp_use_tls=False, frontend_url="",
        )):
            svc = NotificationService()
        assert svc._get_sla_target(NotificationPriority.LOW) == 1800


def _svc_with_mock_settings():
    """Helper to create a service with mocked settings."""
    from app.services.notification_service import NotificationService
    mock_s = MagicMock()
    mock_s.smtp_enabled = False
    mock_s.smtp_password.get_secret_value.return_value = ""
    mock_s.smtp_host = "smtp.co.com"
    mock_s.smtp_port = 587
    mock_s.smtp_username = ""
    mock_s.smtp_from_email = "test@co.com"
    mock_s.smtp_use_tls = False
    mock_s.frontend_url = "http://localhost:3000"
    mock_s.slack_webhook_url = ""
    with patch("app.services.notification_service.settings", mock_s):
        return NotificationService()


class TestGetRecipientAddress:
    def setup_method(self):
        self.svc = _svc_with_mock_settings()

    def test_email_channel_returns_email(self):
        eng = _mock_engineer(email="alice@co.com")
        result = self.svc._get_recipient_address(eng, NotificationChannel.EMAIL)
        assert result == "alice@co.com"

    def test_slack_channel_returns_slack_handle(self):
        eng = _mock_engineer(slack_handle="@alice")
        result = self.svc._get_recipient_address(eng, NotificationChannel.SLACK)
        assert result == "@alice"

    def test_slack_channel_falls_back_to_email(self):
        eng = _mock_engineer(email="alice@co.com", slack_handle=None)
        result = self.svc._get_recipient_address(eng, NotificationChannel.SLACK)
        assert result == "alice@co.com"

    def test_sms_channel_returns_phone(self):
        eng = _mock_engineer(phone="+14155551234")
        result = self.svc._get_recipient_address(eng, NotificationChannel.SMS)
        assert result == "+14155551234"

    def test_sms_channel_falls_back_to_email(self):
        eng = _mock_engineer(email="alice@co.com", phone=None)
        result = self.svc._get_recipient_address(eng, NotificationChannel.SMS)
        assert result == "alice@co.com"

    def test_unknown_channel_falls_back_to_email(self):
        eng = _mock_engineer(email="alice@co.com")
        result = self.svc._get_recipient_address(eng, "unknown_channel")
        assert result == "alice@co.com"


class TestFormatHtmlEmail:
    def setup_method(self):
        self.svc = _svc_with_mock_settings()

    def test_returns_string(self):
        result = self.svc._format_html_email("Hello world", "http://example.com")
        assert isinstance(result, str)

    def test_contains_admin_url(self):
        result = self.svc._format_html_email("msg", "http://my.admin.url/path")
        assert "http://my.admin.url/path" in result

    def test_contains_message(self):
        result = self.svc._format_html_email("Incident resolved", "http://url")
        assert "Incident resolved" in result

    def test_is_html(self):
        result = self.svc._format_html_email("test", "url")
        assert "<!DOCTYPE html>" in result
        assert "</html>" in result


class TestSendEmail:
    async def test_email_simulation_mode_returns_true(self):
        svc = _svc_with_mock_settings()
        svc.smtp_enabled = False
        svc.smtp_user = ""

        notif = _mock_notification(channel=NotificationChannel.EMAIL)
        eng = _mock_engineer()
        inc = _mock_incident()

        with patch("app.services.notification_service.token_service") as mock_ts:
            mock_ts.generate_admin_panel_url.return_value = ("http://url", datetime.now(timezone.utc))
            result = await svc._send_email(notif, eng, inc)

        assert result is True

    async def test_email_smtp_enabled_sends_real_email(self):
        svc = _svc_with_mock_settings()
        svc.smtp_enabled = True
        svc.smtp_user = "user"
        svc.smtp_password = "pass"
        svc.smtp_use_tls = False

        notif = _mock_notification(channel=NotificationChannel.EMAIL)
        eng = _mock_engineer()
        inc = _mock_incident()

        with patch("app.services.notification_service.token_service") as mock_ts, \
             patch("smtplib.SMTP") as mock_smtp:
            mock_ts.generate_admin_panel_url.return_value = ("http://url", datetime.now(timezone.utc))
            mock_server = MagicMock()
            mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
            mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
            result = await svc._send_email(notif, eng, inc)

        assert result is True

    async def test_email_exception_returns_false(self):
        svc = _svc_with_mock_settings()

        notif = _mock_notification(channel=NotificationChannel.EMAIL)
        eng = _mock_engineer()
        inc = _mock_incident()

        with patch("app.services.notification_service.token_service") as mock_ts:
            mock_ts.generate_admin_panel_url.side_effect = Exception("token error")
            result = await svc._send_email(notif, eng, inc)

        assert result is False

    async def test_email_smtp_with_tls(self):
        svc = _svc_with_mock_settings()
        svc.smtp_enabled = True
        svc.smtp_user = "user"
        svc.smtp_password = "pass"
        svc.smtp_use_tls = True

        notif = _mock_notification(channel=NotificationChannel.EMAIL)
        eng = _mock_engineer()
        inc = _mock_incident()

        with patch("app.services.notification_service.token_service") as mock_ts, \
             patch("smtplib.SMTP") as mock_smtp:
            mock_ts.generate_admin_panel_url.return_value = ("http://url", datetime.now(timezone.utc))
            mock_server = MagicMock()
            mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
            mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
            result = await svc._send_email(notif, eng, inc)

        assert result is True
        mock_server.starttls.assert_called_once()


class TestSendSlack:
    async def test_slack_simulation_mode_returns_true(self):
        svc = _svc_with_mock_settings()
        svc.frontend_url = "http://localhost:3000"

        notif = _mock_notification(channel=NotificationChannel.SLACK)
        eng = _mock_engineer()
        inc = _mock_incident()

        with patch("app.services.notification_service.settings") as mock_s, \
             patch("app.services.notification_service.token_service") as mock_ts:
            mock_s.slack_webhook_url = ""
            mock_ts.generate_admin_panel_url.return_value = ("http://url", datetime.now(timezone.utc))
            result = await svc._send_slack(notif, eng, inc)

        assert result is True

    async def test_slack_real_webhook_success(self):
        svc = _svc_with_mock_settings()

        notif = _mock_notification(channel=NotificationChannel.SLACK)
        eng = _mock_engineer()
        inc = _mock_incident()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None

        with patch("app.services.notification_service.settings") as mock_s, \
             patch("app.services.notification_service.token_service") as mock_ts, \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_s.slack_webhook_url = "https://hooks.slack.com/services/test"
            mock_ts.generate_admin_panel_url.return_value = ("http://url", datetime.now(timezone.utc))
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            result = await svc._send_slack(notif, eng, inc)

        assert result is True

    async def test_slack_exception_returns_false(self):
        svc = _svc_with_mock_settings()
        notif = _mock_notification(channel=NotificationChannel.SLACK)
        eng = _mock_engineer()
        inc = _mock_incident()

        with patch("app.services.notification_service.settings") as mock_s, \
             patch("app.services.notification_service.token_service") as mock_ts:
            mock_s.slack_webhook_url = "https://hooks.slack.com"
            mock_ts.generate_admin_panel_url.side_effect = Exception("token error")
            result = await svc._send_slack(notif, eng, inc)

        assert result is False


class TestSendSms:
    async def test_sms_simulation_returns_true(self):
        svc = _svc_with_mock_settings()
        notif = _mock_notification(channel=NotificationChannel.SMS)
        eng = _mock_engineer()
        result = await svc._send_sms(notif, eng)
        assert result is True


class TestSendNotificationInternal:
    async def test_email_channel_dispatched_correctly(self):
        svc = _svc_with_mock_settings()
        notif = _mock_notification(channel=NotificationChannel.EMAIL)
        eng = _mock_engineer()
        inc = _mock_incident()

        with patch.object(svc, "_send_email", AsyncMock(return_value=True)):
            result = await svc._send_notification(notif, eng, inc)

        assert result is True
        assert notif.status == NotificationStatus.SENT

    async def test_slack_channel_dispatched(self):
        svc = _svc_with_mock_settings()
        notif = _mock_notification(channel=NotificationChannel.SLACK)
        eng = _mock_engineer()
        inc = _mock_incident()

        with patch.object(svc, "_send_slack", AsyncMock(return_value=True)):
            result = await svc._send_notification(notif, eng, inc)

        assert result is True

    async def test_sms_channel_dispatched(self):
        svc = _svc_with_mock_settings()
        notif = _mock_notification(channel=NotificationChannel.SMS)
        eng = _mock_engineer()
        inc = _mock_incident()

        with patch.object(svc, "_send_sms", AsyncMock(return_value=True)):
            result = await svc._send_notification(notif, eng, inc)

        assert result is True

    async def test_failure_increments_retry_count(self):
        svc = _svc_with_mock_settings()
        notif = _mock_notification(channel=NotificationChannel.EMAIL)
        notif.retry_count = 0
        eng = _mock_engineer()
        inc = _mock_incident()

        with patch.object(svc, "_send_email", AsyncMock(return_value=False)):
            result = await svc._send_notification(notif, eng, inc)

        assert result is False
        assert notif.retry_count == 1

    async def test_max_retries_reached_sets_failed_status(self):
        svc = _svc_with_mock_settings()
        notif = _mock_notification(channel=NotificationChannel.EMAIL)
        notif.retry_count = 2
        notif.max_retries = 3
        eng = _mock_engineer()
        inc = _mock_incident()

        with patch.object(svc, "_send_email", AsyncMock(return_value=False)):
            await svc._send_notification(notif, eng, inc)

        assert notif.status == NotificationStatus.FAILED

    async def test_exception_returns_false(self):
        svc = _svc_with_mock_settings()
        notif = _mock_notification(channel=NotificationChannel.EMAIL)
        notif.retry_count = 0
        notif.last_error = None
        eng = _mock_engineer()
        inc = _mock_incident()

        with patch.object(svc, "_send_email", AsyncMock(side_effect=Exception("network error"))):
            result = await svc._send_notification(notif, eng, inc)

        assert result is False
        assert notif.last_error == "network error"

    async def test_unsupported_channel_returns_false(self):
        svc = _svc_with_mock_settings()
        notif = _mock_notification(channel=NotificationChannel.EMAIL)
        notif.channel = "unsupported_channel"
        eng = _mock_engineer()
        inc = _mock_incident()

        result = await svc._send_notification(notif, eng, inc)
        assert result is False


class TestGlobalNotificationServiceInstance:
    def test_global_instance_exists(self):
        from app.services.notification_service import notification_service, NotificationService
        assert isinstance(notification_service, NotificationService)
