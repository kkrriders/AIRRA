"""
Admin: daily token usage endpoint.

GET /api/v1/admin/usage  → daily token burn by model for the past 7 days.

Redis keys written by LLMClient.generate():
    budget:daily:{model}:{YYYY-MM-DD}   → total tokens (int, auto-expires in 24h)
"""
import logging
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, status

from app.core.redis import get_redis

logger = logging.getLogger(__name__)
router = APIRouter()

_DAYS_BACK = 7


@router.get("/usage")
async def get_token_usage():
    """Return daily token spend per model for the past 7 days."""
    try:
        redis = get_redis()
        keys = await redis.keys("budget:daily:*")

        # Build date window for filtering
        today = date.today()
        valid_dates = {
            (today - timedelta(days=i)).isoformat() for i in range(_DAYS_BACK + 1)
        }

        usage: dict[str, dict[str, int]] = {}
        for key in keys:
            # Key format: budget:daily:{model}:{YYYY-MM-DD}
            parts = key.split(":")
            if len(parts) < 4:
                continue
            model = parts[2]
            day = parts[3]
            if day not in valid_dates:
                continue
            value = await redis.get(key)
            usage.setdefault(model, {})[day] = int(value or 0)

        # Compute per-model totals
        totals = {model: sum(days.values()) for model, days in usage.items()}

        return {
            "window_days": _DAYS_BACK,
            "usage_by_model": usage,
            "totals_by_model": totals,
            "grand_total_tokens": sum(totals.values()),
        }

    except Exception as exc:
        logger.error("Failed to read token usage from Redis: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not read token usage — Redis unavailable",
        )
