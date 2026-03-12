"""
Additional unit tests for app/services/learning_engine.py

Focuses on DB-backed paths not covered by test_learning_engine.py:
- get_pattern: DB hit → PatternSignature cached in L1
- load_patterns_from_db: warms L1 cache from DB rows
- generate_insights: returns summary dict from DB queries
"""
import pytest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.learning_engine import LearningEngine, PatternSignature, _SEED_PATTERNS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db_pattern(
    pattern_id="payment-service:memory_leak",
    name="Payment memory_leak",
    category="memory_leak",
    signal_indicators=None,
    confidence_adjustment=0.1,
    occurrence_count=5,
    success_rate=0.8,
):
    p = MagicMock()
    p.pattern_id = pattern_id
    p.name = name
    p.category = category
    p.signal_indicators = signal_indicators or ["mem_rss", "mem_heap"]
    p.confidence_adjustment = confidence_adjustment
    p.occurrence_count = occurrence_count
    p.success_rate = success_rate
    return p


def _make_db_ctx(scalar_one_or_none_value=None, scalars_all_value=None):
    """Return a mock async context manager that yields a DB-like object."""
    db = AsyncMock()

    # For scalar_one_or_none queries
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = scalar_one_or_none_value
    mock_result.scalar_one.return_value = scalar_one_or_none_value

    # For scalars().all() queries
    mock_result.scalars.return_value.all.return_value = (
        scalars_all_value if scalars_all_value is not None else []
    )

    db.execute = AsyncMock(return_value=mock_result)

    @asynccontextmanager
    async def _ctx():
        yield db

    return _ctx()


# ---------------------------------------------------------------------------
# get_pattern — DB hit path (lines 382-392)
# ---------------------------------------------------------------------------

class TestGetPatternDbHit:
    async def test_db_hit_creates_pattern_and_caches(self):
        engine = LearningEngine()
        db_pattern = _mock_db_pattern()

        @asynccontextmanager
        async def _ctx():
            db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = db_pattern
            db.execute = AsyncMock(return_value=mock_result)
            yield db

        with patch("app.services.learning_engine.get_db_context", return_value=_ctx()):
            result = await engine.get_pattern("payment-service", "memory_leak")

        assert result is not None
        assert isinstance(result, PatternSignature)
        assert result.pattern_id == "payment-service:memory_leak"
        assert result.confidence_adjustment == 0.1
        assert result.occurrence_count == 5
        # Should be cached in L1
        assert "payment-service:memory_leak" in engine.patterns

    async def test_db_hit_with_none_signal_indicators_defaults_to_empty_list(self):
        engine = LearningEngine()
        db_pattern = _mock_db_pattern(signal_indicators=None)
        db_pattern.signal_indicators = None  # Explicitly None

        @asynccontextmanager
        async def _ctx():
            db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = db_pattern
            db.execute = AsyncMock(return_value=mock_result)
            yield db

        with patch("app.services.learning_engine.get_db_context", return_value=_ctx()):
            result = await engine.get_pattern("payment-service", "memory_leak")

        assert result is not None
        assert result.signal_indicators == []


# ---------------------------------------------------------------------------
# load_patterns_from_db (lines 420-434)
# ---------------------------------------------------------------------------

class TestLoadPatternsFromDb:
    async def test_loads_patterns_into_cache(self):
        engine = LearningEngine()
        p1 = _mock_db_pattern("svc-a:memory_leak", "SvcA memleak", "memory_leak")
        p2 = _mock_db_pattern("svc-b:cpu_spike", "SvcB cpu", "cpu_spike",
                               confidence_adjustment=0.05, occurrence_count=3)

        @asynccontextmanager
        async def _ctx():
            db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [p1, p2]
            db.execute = AsyncMock(return_value=mock_result)
            yield db

        with patch("app.services.learning_engine.get_db_context", return_value=_ctx()):
            await engine.load_patterns_from_db()

        assert "svc-a:memory_leak" in engine.patterns
        assert "svc-b:cpu_spike" in engine.patterns
        assert engine.patterns["svc-a:memory_leak"].category == "memory_leak"
        assert engine.patterns["svc-b:cpu_spike"].confidence_adjustment == 0.05

    async def test_load_empty_db_leaves_cache_empty(self):
        engine = LearningEngine()

        @asynccontextmanager
        async def _ctx():
            db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            db.execute = AsyncMock(return_value=mock_result)
            yield db

        with patch("app.services.learning_engine.get_db_context", return_value=_ctx()):
            await engine.load_patterns_from_db()

        assert engine.patterns == {}

    async def test_load_patterns_exception_is_swallowed(self):
        engine = LearningEngine()

        with patch("app.services.learning_engine.get_db_context") as mock_ctx:
            mock_ctx.side_effect = Exception("DB unavailable")
            # Should not raise
            await engine.load_patterns_from_db()

        assert engine.patterns == {}

    async def test_load_patterns_with_none_signal_indicators(self):
        engine = LearningEngine()
        p = _mock_db_pattern()
        p.signal_indicators = None

        @asynccontextmanager
        async def _ctx():
            db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [p]
            db.execute = AsyncMock(return_value=mock_result)
            yield db

        with patch("app.services.learning_engine.get_db_context", return_value=_ctx()):
            await engine.load_patterns_from_db()

        key = "payment-service:memory_leak"
        assert engine.patterns[key].signal_indicators == []


# ---------------------------------------------------------------------------
# generate_insights (lines 465-606)
# ---------------------------------------------------------------------------

class TestGenerateInsights:
    async def _make_multi_scalar_db(self, values: list):
        """DB that returns different scalar_one() values for successive execute calls."""
        db = AsyncMock()
        results = []
        for v in values:
            r = MagicMock()
            r.scalar_one.return_value = v
            r.scalar_one_or_none.return_value = v
            results.append(r)
        db.execute = AsyncMock(side_effect=results)
        return db

    async def test_generate_insights_returns_dict(self):
        engine = LearningEngine()
        # 8 queries in generate_insights: total_incidents, resolved, avg_resolution,
        # correct_hyps, total_hyps, successful_actions, top1_correct, top1_validated, similarity_reuse
        values = [10, 7, 300, 5, 8, 6, 4, 8, 2]

        @asynccontextmanager
        async def _ctx():
            db = await self._make_multi_scalar_db(values)
            yield db

        with patch("app.services.learning_engine.get_db_context", return_value=_ctx()):
            result = await engine.generate_insights(days=30)

        assert isinstance(result, dict)
        assert result["total_incidents"] == 10
        assert result["resolved_incidents"] == 7
        assert result["period_days"] == 30
        assert "resolution_rate" in result
        assert "hypothesis_accuracy" in result
        assert "patterns_learned" in result
        assert "seed_patterns_available" in result

    async def test_generate_insights_zero_incidents(self):
        engine = LearningEngine()
        values = [0, 0, 0, 0, 0, 0, 0, 0, 0]

        @asynccontextmanager
        async def _ctx():
            db = await self._make_multi_scalar_db(values)
            yield db

        with patch("app.services.learning_engine.get_db_context", return_value=_ctx()):
            result = await engine.generate_insights()

        assert result["resolution_rate"] == 0.0
        assert result["hypothesis_accuracy"] == 0.0

    async def test_generate_insights_exception_returns_empty_dict(self):
        engine = LearningEngine()

        with patch("app.services.learning_engine.get_db_context") as mock_ctx:
            mock_ctx.side_effect = Exception("connection error")
            result = await engine.generate_insights()

        assert result == {}

    async def test_generate_insights_patterns_learned_reflects_cache(self):
        engine = LearningEngine()
        engine.patterns["svc:cat"] = MagicMock()
        values = [5, 3, 120, 2, 4, 3, 1, 4, 0]

        @asynccontextmanager
        async def _ctx():
            db = await self._make_multi_scalar_db(values)
            yield db

        with patch("app.services.learning_engine.get_db_context", return_value=_ctx()):
            result = await engine.generate_insights()

        assert result["patterns_learned"] == 1

    async def test_generate_insights_seed_patterns_count(self):
        engine = LearningEngine()
        values = [1, 1, 60, 1, 1, 1, 1, 1, 0]

        @asynccontextmanager
        async def _ctx():
            db = await self._make_multi_scalar_db(values)
            yield db

        with patch("app.services.learning_engine.get_db_context", return_value=_ctx()):
            result = await engine.generate_insights()

        assert result["seed_patterns_available"] == len(_SEED_PATTERNS)

    async def test_generate_insights_avg_resolution_time(self):
        engine = LearningEngine()
        # avg resolution time = 600 seconds = 10 minutes
        values = [5, 5, 600, 3, 5, 4, 2, 5, 0]

        @asynccontextmanager
        async def _ctx():
            db = await self._make_multi_scalar_db(values)
            yield db

        with patch("app.services.learning_engine.get_db_context", return_value=_ctx()):
            result = await engine.generate_insights()

        assert result["avg_resolution_time_seconds"] == 600
        assert result["avg_resolution_time_minutes"] == 10

    async def test_generate_insights_top1_accuracy_none_when_no_validated(self):
        engine = LearningEngine()
        # top1_validated_total = 0, so top1_accuracy should be None
        values = [5, 3, 300, 2, 4, 3, 0, 0, 1]

        @asynccontextmanager
        async def _ctx():
            db = await self._make_multi_scalar_db(values)
            yield db

        with patch("app.services.learning_engine.get_db_context", return_value=_ctx()):
            result = await engine.generate_insights()

        assert result["top1_accuracy"] is None

    async def test_generate_insights_custom_days(self):
        engine = LearningEngine()
        values = [2, 1, 180, 1, 2, 1, 1, 2, 0]

        @asynccontextmanager
        async def _ctx():
            db = await self._make_multi_scalar_db(values)
            yield db

        with patch("app.services.learning_engine.get_db_context", return_value=_ctx()):
            result = await engine.generate_insights(days=7)

        assert result["period_days"] == 7
