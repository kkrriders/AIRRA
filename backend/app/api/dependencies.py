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
) -> str | None:
    """
    Verify the API key from the X-API-Key header.

    In development with no key configured, authentication is skipped.
    In production, a valid API key is always required.
    """
    configured_key = settings.api_key.get_secret_value()

    # If no API key is configured, skip auth (development only)
    if not configured_key:
        if settings.environment == "production":
            logger.error("No API key configured in production — rejecting all requests")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Server misconfiguration: authentication not set up",
            )
        return None

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Provide X-API-Key header.",
        )

    # Constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(api_key, configured_key):
        logger.warning("Invalid API key attempt")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )

    return api_key
