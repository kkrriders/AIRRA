"""
Unit tests for app/services/token_service.py

Uses patched settings to avoid needing real secret values.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4


def _make_token_service():
    """Create a TokenService with a test secret."""
    from app.services.token_service import TokenService

    svc = TokenService.__new__(TokenService)
    svc._secret = b"test_secret_key_for_unit_tests"
    return svc


class TestTokenServiceInit:
    def test_init_uses_notification_token_secret(self, monkeypatch):
        """When notification_token_secret is set, it should be used."""

        mock_settings = MagicMock()
        mock_settings.notification_token_secret.get_secret_value.return_value = "my_notif_secret"
        mock_settings.api_key.get_secret_value.return_value = "api_key_fallback"

        with patch("app.services.token_service.settings", mock_settings):
            from app.services.token_service import TokenService
            svc = TokenService()
            assert svc._secret == b"my_notif_secret"

    def test_init_falls_back_to_api_key_when_secret_empty(self, monkeypatch):
        """When notification_token_secret is empty, fall back to api_key."""
        mock_settings = MagicMock()
        mock_settings.notification_token_secret.get_secret_value.return_value = ""
        mock_settings.api_key.get_secret_value.return_value = "fallback_api_key"

        with patch("app.services.token_service.settings", mock_settings):
            from app.services.token_service import TokenService
            svc = TokenService()
            assert svc._secret == b"fallback_api_key"


class TestGenerateToken:
    def setup_method(self):
        self.svc = _make_token_service()
        self.notification_id = uuid4()
        self.engineer_id = uuid4()

    def test_returns_tuple(self):
        token, expires = self.svc.generate_token(self.notification_id, self.engineer_id)
        assert isinstance(token, str)
        assert isinstance(expires, datetime)

    def test_token_has_four_parts(self):
        token, _ = self.svc.generate_token(self.notification_id, self.engineer_id)
        parts = token.split(":")
        assert len(parts) == 4

    def test_expiration_in_future(self):
        _, expires = self.svc.generate_token(self.notification_id, self.engineer_id)
        assert expires > datetime.now(timezone.utc)

    def test_custom_expiry_hours(self):
        _, expires = self.svc.generate_token(
            self.notification_id, self.engineer_id, expiry_hours=4
        )
        now = datetime.now(timezone.utc)
        # Should expire in roughly 4 hours
        assert expires > now + timedelta(hours=3, minutes=59)

    def test_token_contains_notification_id(self):
        token, _ = self.svc.generate_token(self.notification_id, self.engineer_id)
        assert str(self.notification_id) in token

    def test_token_contains_engineer_id(self):
        token, _ = self.svc.generate_token(self.notification_id, self.engineer_id)
        assert str(self.engineer_id) in token

    def test_different_tokens_each_call(self):
        token1, _ = self.svc.generate_token(self.notification_id, self.engineer_id)
        token2, _ = self.svc.generate_token(self.notification_id, self.engineer_id)
        # Random part makes each token unique
        assert token1 != token2


class TestValidateToken:
    def setup_method(self):
        self.svc = _make_token_service()
        self.notification_id = uuid4()
        self.engineer_id = uuid4()

    def test_valid_token_returns_true(self):
        token, expires = self.svc.generate_token(self.notification_id, self.engineer_id)
        valid, error = self.svc.validate_token(
            token, self.notification_id, self.engineer_id, expires
        )
        assert valid is True
        assert error is None

    def test_expired_token_returns_false(self):
        token, _ = self.svc.generate_token(self.notification_id, self.engineer_id)
        past_expiry = datetime.now(timezone.utc) - timedelta(hours=1)
        valid, error = self.svc.validate_token(
            token, self.notification_id, self.engineer_id, past_expiry
        )
        assert valid is False
        assert "expired" in error.lower()

    def test_wrong_notification_id_returns_false(self):
        token, expires = self.svc.generate_token(self.notification_id, self.engineer_id)
        wrong_id = uuid4()
        valid, error = self.svc.validate_token(
            token, wrong_id, self.engineer_id, expires
        )
        assert valid is False
        assert "notification" in error.lower()

    def test_wrong_engineer_id_returns_false(self):
        token, expires = self.svc.generate_token(self.notification_id, self.engineer_id)
        wrong_id = uuid4()
        valid, error = self.svc.validate_token(
            token, self.notification_id, wrong_id, expires
        )
        assert valid is False
        assert "engineer" in error.lower()

    def test_tampered_signature_returns_false(self):
        token, expires = self.svc.generate_token(self.notification_id, self.engineer_id)
        # Tamper with the last part (signature)
        parts = token.split(":")
        parts[-1] = "0" * len(parts[-1])
        tampered_token = ":".join(parts)
        valid, error = self.svc.validate_token(
            tampered_token, self.notification_id, self.engineer_id, expires
        )
        assert valid is False
        assert "signature" in error.lower()

    def test_malformed_token_wrong_parts_count(self):
        valid, error = self.svc.validate_token(
            "only:three:parts",
            self.notification_id,
            self.engineer_id,
            datetime.now(timezone.utc) + timedelta(hours=1),
        )
        assert valid is False
        assert "format" in error.lower()

    def test_exception_returns_validation_failed(self):
        # Pass a non-string token to trigger exception path
        valid, error = self.svc.validate_token(
            None,  # type: ignore
            self.notification_id,
            self.engineer_id,
            datetime.now(timezone.utc) + timedelta(hours=1),
        )
        assert valid is False
        assert error is not None


class TestGenerateAdminPanelUrl:
    def setup_method(self):
        self.svc = _make_token_service()
        self.notification_id = uuid4()
        self.engineer_id = uuid4()

    def test_returns_tuple(self):
        url, expires = self.svc.generate_admin_panel_url(
            self.notification_id, self.engineer_id
        )
        assert isinstance(url, str)
        assert isinstance(expires, datetime)

    def test_url_contains_notification_id(self):
        url, _ = self.svc.generate_admin_panel_url(
            self.notification_id, self.engineer_id
        )
        assert str(self.notification_id) in url

    def test_url_contains_token_param(self):
        url, _ = self.svc.generate_admin_panel_url(
            self.notification_id, self.engineer_id
        )
        assert "?token=" in url

    def test_custom_base_url(self):
        url, _ = self.svc.generate_admin_panel_url(
            self.notification_id, self.engineer_id,
            base_url="https://my.airra.example.com",
        )
        assert url.startswith("https://my.airra.example.com")
