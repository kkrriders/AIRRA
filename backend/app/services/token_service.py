"""
Token service for generating and validating secure notification acknowledgement tokens.

Senior Engineering Note:
- Uses cryptographically secure random tokens
- Time-limited expiration (default 1 hour)
- HMAC signature for tamper detection
- Constant-time comparison to prevent timing attacks
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from app.config import settings


class TokenService:
    """Service for generating and validating secure tokens."""

    def __init__(self):
        """Initialize token service with secret key from settings."""
        # Use API key as secret for token generation
        self._secret = settings.api_key.get_secret_value().encode("utf-8")

    def generate_token(
        self,
        notification_id: UUID,
        engineer_id: UUID,
        expiry_hours: int = 1,
    ) -> tuple[str, datetime]:
        """
        Generate a secure token for notification acknowledgement.

        Args:
            notification_id: The notification being acknowledged
            engineer_id: The engineer who should acknowledge
            expiry_hours: Token validity period in hours

        Returns:
            Tuple of (token, expiration_datetime)
        """
        # Generate random token (32 bytes = 64 hex chars)
        random_part = secrets.token_urlsafe(32)

        # Create payload: token + notification_id + engineer_id
        payload = f"{random_part}:{notification_id}:{engineer_id}"

        # Generate HMAC signature to prevent tampering
        signature = hmac.new(
            self._secret,
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        # Combine payload and signature
        token = f"{payload}:{signature}"

        # Calculate expiration
        expires_at = datetime.now(timezone.utc) + timedelta(hours=expiry_hours)

        return token, expires_at

    def validate_token(
        self,
        token: str,
        notification_id: UUID,
        engineer_id: UUID,
        expires_at: datetime,
    ) -> tuple[bool, Optional[str]]:
        """
        Validate a token for notification acknowledgement.

        Args:
            token: The token to validate
            notification_id: Expected notification ID
            engineer_id: Expected engineer ID
            expires_at: Token expiration time

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            # Check expiration
            if datetime.now(timezone.utc) > expires_at:
                return False, "Token has expired"

            # Parse token
            parts = token.split(":")
            if len(parts) != 4:
                return False, "Invalid token format"

            random_part, token_notification_id, token_engineer_id, signature = parts

            # Verify notification and engineer IDs match
            if str(notification_id) != token_notification_id:
                return False, "Token notification ID mismatch"

            if str(engineer_id) != token_engineer_id:
                return False, "Token engineer ID mismatch"

            # Reconstruct payload and verify signature
            payload = f"{random_part}:{token_notification_id}:{token_engineer_id}"
            expected_signature = hmac.new(
                self._secret,
                payload.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()

            # Constant-time comparison to prevent timing attacks
            if not secrets.compare_digest(signature, expected_signature):
                return False, "Invalid token signature"

            return True, None

        except Exception as e:
            return False, f"Token validation error: {str(e)}"

    def generate_admin_panel_url(
        self,
        notification_id: UUID,
        engineer_id: UUID,
        base_url: str = "http://localhost:3000",
    ) -> tuple[str, datetime]:
        """
        Generate a secure URL for the admin panel with embedded token.

        Args:
            notification_id: The notification being acknowledged
            engineer_id: The engineer who should access
            base_url: Base URL of the frontend

        Returns:
            Tuple of (url, expiration_datetime)
        """
        token, expires_at = self.generate_token(notification_id, engineer_id)

        # Build URL with token as query parameter
        url = f"{base_url}/admin/incident/{notification_id}?token={token}"

        return url, expires_at


# Global instance
token_service = TokenService()
