"""
Lightweight in-memory rate limiter for expensive endpoints.

Uses a token bucket algorithm per client IP.
For multi-instance deployments, replace with Redis-backed rate limiting.
"""
import logging
import time
from collections import defaultdict

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)


class _TokenBucket:
    """Token bucket for a single client."""

    __slots__ = ("tokens", "last_refill", "max_tokens", "refill_rate")

    def __init__(self, max_tokens: float, refill_rate: float):
        self.tokens = max_tokens
        self.last_refill = time.monotonic()
        self.max_tokens = max_tokens
        self.refill_rate = refill_rate  # tokens per second

    def consume(self) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


class RateLimiter:
    """
    Per-IP rate limiter using token bucket algorithm.

    Args:
        max_requests: Maximum burst size (bucket capacity).
        window_seconds: Time window to fully refill the bucket.
    """

    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_tokens = float(max_requests)
        self.refill_rate = max_requests / window_seconds
        self._buckets: dict[str, _TokenBucket] = defaultdict(
            lambda: _TokenBucket(self.max_tokens, self.refill_rate)
        )

    def _get_client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def __call__(self, request: Request) -> None:
        client_ip = self._get_client_ip(request)
        bucket = self._buckets[client_ip]

        if not bucket.consume():
            logger.warning(f"Rate limit exceeded for {client_ip}: {request.url.path}")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please try again later.",
                headers={"Retry-After": str(int(1.0 / self.refill_rate))},
            )


# Pre-configured limiters for different endpoint tiers
# LLM endpoints: 5 requests per minute (expensive API calls)
llm_rate_limit = RateLimiter(max_requests=5, window_seconds=60)

# Standard write endpoints: 30 requests per minute
write_rate_limit = RateLimiter(max_requests=30, window_seconds=60)
