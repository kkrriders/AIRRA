"""
Redis-backed sliding window rate limiter for expensive endpoints.

Replaces the in-memory token bucket, which gave each API replica its own
independent bucket. With N replicas, clients could make N × limit requests
per window. The Redis sliding window is shared across all replicas.

Algorithm: per-client sorted set keyed by (limiter_name, client_ip).
  - Score = timestamp (float seconds, used for range eviction)
  - Members = unique timestamp strings per request

The check-and-record is executed as a single atomic Lua script, which
eliminates two bugs present in the pipeline approach:
  1. Race condition: concurrent requests at the boundary all pass because
     ZCARD is read before ZADD in non-atomic pipeline.
  2. Stale pollution: rejected requests were still ZADD'd, inflating counts
     for subsequent valid requests.

Falls back to in-memory token bucket if Redis is unavailable, so the API
keeps serving requests even during a Redis outage (degraded, not broken).
"""
import logging
import time
import uuid
from collections import defaultdict

import redis.asyncio as aioredis
from fastapi import HTTPException, Request, status

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared Redis connection pool
# Safe to lazily initialise here: FastAPI's event loop is single-threaded
# (asyncio), so there is no thread-safety concern with the module-level global.
# ---------------------------------------------------------------------------
_redis_client: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            str(settings.redis_url),
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _redis_client


# ---------------------------------------------------------------------------
# Lua script: atomic sliding window check-and-record
#
# KEYS[1]  = sorted-set key  e.g. "ratelimit:llm:1.2.3.4"
# ARGV[1]  = now (float seconds as string)        — used as the score
# ARGV[2]  = window_start = now - window_seconds  — eviction cutoff
# ARGV[3]  = max_requests (integer limit)
# ARGV[4]  = window_seconds (TTL for the key)
# ARGV[5]  = unique_id (UUID string)              — used as the member
#
# Score and member are intentionally separate:
#   Score = timestamp, used for ZREMRANGEBYSCORE eviction.
#   Member = UUID, ensures uniqueness within a microsecond so two concurrent
#   requests at the same timestamp are both recorded (IMP-4 fix).
#
# Returns: 1 = request allowed, 0 = rate limit exceeded
# ---------------------------------------------------------------------------
_SLIDING_WINDOW_LUA = """
local key          = KEYS[1]
local now          = ARGV[1]
local window_start = ARGV[2]
local max_requests = tonumber(ARGV[3])
local window_ttl   = tonumber(ARGV[4])
local unique_id    = ARGV[5]

-- Evict entries outside the current window
redis.call('ZREMRANGEBYSCORE', key, 0, window_start)

-- Count requests still in the window
local count = redis.call('ZCARD', key)

if count < max_requests then
    -- Record this request only if it is within the limit.
    -- Member is unique_id (not 'now') to prevent collision when two requests
    -- arrive in the same microsecond and produce an identical timestamp string.
    redis.call('ZADD', key, now, unique_id)
    redis.call('EXPIRE', key, window_ttl)
    return 1
else
    return 0
end
"""


# ---------------------------------------------------------------------------
# Fallback: in-memory token bucket (used when Redis is unreachable)
# ---------------------------------------------------------------------------

class _TokenBucket:
    __slots__ = ("tokens", "last_refill", "max_tokens", "refill_rate")

    def __init__(self, max_tokens: float, refill_rate: float):
        self.tokens = max_tokens
        self.last_refill = time.monotonic()
        self.max_tokens = max_tokens
        self.refill_rate = refill_rate

    def consume(self) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


# ---------------------------------------------------------------------------
# Redis sliding window rate limiter
# ---------------------------------------------------------------------------

class RateLimiter:
    """
    Per-IP sliding window rate limiter backed by Redis sorted sets.

    Args:
        max_requests: Maximum requests allowed within window_seconds.
        window_seconds: Sliding window size in seconds.
        name: Unique name to namespace Redis keys per limiter instance.
    """

    def __init__(
        self,
        max_requests: int = 10,
        window_seconds: int = 60,
        name: str = "default",
    ):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.name = name
        # Fallback buckets — only used if Redis is unreachable
        self._fallback_buckets: dict[str, _TokenBucket] = defaultdict(
            lambda: _TokenBucket(float(max_requests), max_requests / window_seconds)
        )

    def _get_client_ip(self, request: Request) -> str:
        # NOTE: X-Forwarded-For is taken at face value here. Any client behind
        # a non-trusted proxy can spoof this header and appear as a different IP
        # on every request, bypassing per-IP rate limits. In production, strip or
        # validate this header at the ingress layer (nginx/Envoy trusted-proxy config)
        # before it reaches the application.
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def __call__(self, request: Request) -> None:
        client_ip = self._get_client_ip(request)

        try:
            allowed = await self._check_redis(client_ip)
        except Exception as exc:
            logger.warning(
                f"Redis rate limiter unavailable, falling back to in-memory: {exc}"
            )
            allowed = self._fallback_buckets[client_ip].consume()

        if not allowed:
            logger.warning(
                f"Rate limit exceeded for {client_ip} on limiter '{self.name}': "
                f"{request.url.path}"
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please try again later.",
                headers={"Retry-After": str(self.window_seconds)},
            )

    async def _check_redis(self, client_ip: str) -> bool:
        """
        Atomic sliding window check via Lua script.

        The Lua script runs as a single Redis command — no other client
        can interleave between the eviction, count, and conditional ZADD.
        Returns True if the request is within the allowed rate.
        """
        redis_client = _get_redis()
        key = f"ratelimit:{self.name}:{client_ip}"
        now = time.time()
        window_start = now - self.window_seconds

        result = await redis_client.eval(
            _SLIDING_WINDOW_LUA,
            1,                          # number of KEYS
            key,                        # KEYS[1]
            str(now),                   # ARGV[1] — score (timestamp for eviction)
            str(window_start),          # ARGV[2] — eviction cutoff
            str(self.max_requests),     # ARGV[3] — limit
            str(self.window_seconds),   # ARGV[4] — TTL
            str(uuid.uuid4()),          # ARGV[5] — unique member (prevents collision)
        )
        return result == 1


# Pre-configured limiters for different endpoint tiers
# LLM endpoints: 5 requests per minute (expensive API calls)
llm_rate_limit = RateLimiter(max_requests=5, window_seconds=60, name="llm")

# Standard write endpoints: 30 requests per minute
write_rate_limit = RateLimiter(max_requests=30, window_seconds=60, name="write")
