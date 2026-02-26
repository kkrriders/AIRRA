"""
Shared API dependencies for authentication and authorization.
"""
import logging
import secrets

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.config import settings

logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    api_key: str | None = Security(api_key_header),
) -> str:
    """
    Verify the API key from the X-API-Key header.

    API key is always required for security. If you need to disable
    authentication for development/testing, set a development key in .env
    rather than leaving it empty.
    """
    configured_key = settings.api_key.get_secret_value()

    # Always require API key to be configured
    if not configured_key:
        logger.error(
            "API key not configured. Set AIRRA_API_KEY in environment. "
            "For development, use a test key like 'dev-test-key-12345'"
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server misconfiguration: API key not configured",
        )

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Provide X-API-Key header.",
        )

    # Constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(api_key, configured_key):
        print(f"DEBUG: api_key='{api_key}', configured_key='{configured_key}'")
        logger.warning("Invalid API key attempt", extra={"provided_key_prefix": api_key[:8]})
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )

    return api_key
