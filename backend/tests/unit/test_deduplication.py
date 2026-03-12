"""
Unit tests for app/utils/deduplication.py

Pure functions tested without DB; async DB functions use AsyncMock.
"""
from unittest.mock import AsyncMock, MagicMock

from app.utils.deduplication import (
    SEVERITY_LOOKBACK_WINDOWS,
    calculate_token_similarity,
    create_or_update_incident,
    find_duplicate_incident,
    generate_incident_fingerprint,
    is_fuzzy_match,
    normalize_text,
)


class TestNormalizeText:
    def test_lowercase(self):
        assert normalize_text("HELLO WORLD") == "hello world"

    def test_strips_whitespace(self):
        assert normalize_text("  hello  ") == "hello"

    def test_removes_punctuation(self):
        result = normalize_text("error: connection refused!")
        assert ":" not in result
        assert "!" not in result

    def test_normalizes_multiple_spaces(self):
        result = normalize_text("hello   world")
        assert "  " not in result
        assert result == "hello world"

    def test_word_normalization_db(self):
        result = normalize_text("db connection")
        assert "database" in result

    def test_word_normalization_api(self):
        result = normalize_text("api error")
        assert "api" in result

    def test_word_normalization_svc(self):
        result = normalize_text("svc timeout")
        assert "service" in result

    def test_word_normalization_err(self):
        result = normalize_text("err code 500")
        assert "error" in result

    def test_word_normalization_auth(self):
        result = normalize_text("auth failed")
        assert "authentication" in result

    def test_empty_string(self):
        assert normalize_text("") == ""

    def test_unknown_word_preserved(self):
        result = normalize_text("kubernetes pod crash")
        assert "kubernetes" in result
        assert "pod" in result


class TestCalculateTokenSimilarity:
    def test_identical_texts_similarity_one(self):
        assert calculate_token_similarity("hello world", "hello world") == 1.0

    def test_completely_different_texts_similarity_zero(self):
        assert calculate_token_similarity("apple banana", "cat dog") == 0.0

    def test_partial_overlap(self):
        # "a b c" vs "a b d" → intersection={a,b}, union={a,b,c,d} = 2/4 = 0.5
        result = calculate_token_similarity("a b c", "a b d")
        assert abs(result - 0.5) < 1e-9

    def test_empty_text1_returns_zero(self):
        assert calculate_token_similarity("", "hello world") == 0.0

    def test_empty_text2_returns_zero(self):
        assert calculate_token_similarity("hello world", "") == 0.0

    def test_both_empty_returns_zero(self):
        assert calculate_token_similarity("", "") == 0.0

    def test_symmetric(self):
        t1 = "memory leak in service"
        t2 = "service memory leak detected"
        assert calculate_token_similarity(t1, t2) == calculate_token_similarity(t2, t1)

    def test_single_token_match(self):
        # "a" vs "a b" → intersection={a}, union={a,b} = 0.5
        result = calculate_token_similarity("a", "a b")
        assert abs(result - 0.5) < 1e-9


class TestGenerateIncidentFingerprint:
    def test_same_inputs_same_fingerprint(self):
        fp1 = generate_incident_fingerprint("svc", "desc", ["comp1"])
        fp2 = generate_incident_fingerprint("svc", "desc", ["comp1"])
        assert fp1 == fp2

    def test_different_service_different_fingerprint(self):
        fp1 = generate_incident_fingerprint("svc-a", "desc")
        fp2 = generate_incident_fingerprint("svc-b", "desc")
        assert fp1 != fp2

    def test_different_description_different_fingerprint(self):
        fp1 = generate_incident_fingerprint("svc", "desc a")
        fp2 = generate_incident_fingerprint("svc", "desc b")
        assert fp1 != fp2

    def test_case_insensitive_service(self):
        fp1 = generate_incident_fingerprint("SVC", "desc")
        fp2 = generate_incident_fingerprint("svc", "desc")
        assert fp1 == fp2

    def test_components_sorted(self):
        fp1 = generate_incident_fingerprint("svc", "desc", ["a", "b"])
        fp2 = generate_incident_fingerprint("svc", "desc", ["b", "a"])
        assert fp1 == fp2

    def test_no_components_vs_empty_list(self):
        fp1 = generate_incident_fingerprint("svc", "desc", None)
        fp2 = generate_incident_fingerprint("svc", "desc", [])
        assert fp1 == fp2

    def test_returns_32_char_hex(self):
        fp = generate_incident_fingerprint("svc", "desc")
        assert len(fp) == 32
        assert all(c in "0123456789abcdef" for c in fp)


class TestIsFuzzyMatch:
    def test_same_service_similar_desc_is_match(self):
        result = is_fuzzy_match(
            "payment-service", "database connection pool exhausted all connections",
            None,
            "payment-service", "database connection pool exhausted all connections today",
            None,
        )
        assert result is True

    def test_different_service_never_matches(self):
        result = is_fuzzy_match(
            "service-a", "memory leak detected in service",
            None,
            "service-b", "memory leak detected in service",
            None,
        )
        assert result is False

    def test_completely_different_desc_no_match(self):
        result = is_fuzzy_match(
            "svc", "memory leak in heap allocator",
            None,
            "svc", "cpu spike from runaway process thread",
            None,
        )
        assert result is False

    def test_case_insensitive_service_match(self):
        result = is_fuzzy_match(
            "Payment-Service", "connection refused database pool exhausted",
            None,
            "payment-service", "connection refused database pool exhausted",
            None,
        )
        assert result is True

    def test_identical_descriptions_match(self):
        desc = "high cpu usage on api gateway service thread"
        result = is_fuzzy_match("svc", desc, None, "svc", desc, None)
        assert result is True


class TestSeverityLookbackWindows:
    def test_critical_window_15(self):
        assert SEVERITY_LOOKBACK_WINDOWS["critical"] == 15

    def test_high_window_30(self):
        assert SEVERITY_LOOKBACK_WINDOWS["high"] == 30

    def test_medium_window_60(self):
        assert SEVERITY_LOOKBACK_WINDOWS["medium"] == 60

    def test_low_window_120(self):
        assert SEVERITY_LOOKBACK_WINDOWS["low"] == 120


class TestFindDuplicateIncident:
    async def test_returns_none_when_no_match(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        result = await find_duplicate_incident(
            db=db,
            service="payment-service",
            description="memory leak detected",
            severity="high",
        )
        assert result is None

    async def test_returns_existing_on_exact_fingerprint_match(self):
        from unittest.mock import MagicMock


        # Build a fake existing incident with matching fingerprint data
        service = "payment-service"
        description = "memory leak in cache layer"
        existing = MagicMock()
        existing.affected_service = service
        existing.description = description
        existing.affected_components = None

        db = AsyncMock()
        mock_result_exact = MagicMock()
        mock_result_exact.scalar_one_or_none.return_value = existing

        # First call (exact fingerprint query) returns existing
        # Second call (fuzzy) won't be hit since fingerprint matches
        db.execute = AsyncMock(return_value=mock_result_exact)

        result = await find_duplicate_incident(
            db=db,
            service=service,
            description=description,
            severity="high",
        )
        assert result is existing

    async def test_uses_severity_lookback_when_none_provided(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_scalars = MagicMock()
        mock_scalars.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[mock_result, mock_scalars])

        await find_duplicate_incident(
            db=db,
            service="svc",
            description="issue",
            severity="critical",
            lookback_minutes=None,
        )
        # Should have executed queries — just verifying no errors
        assert db.execute.called

    async def test_explicit_lookback_minutes_respected(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_fuzzy_result = MagicMock()
        mock_fuzzy_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[mock_result, mock_fuzzy_result])

        result = await find_duplicate_incident(
            db=db,
            service="svc",
            description="desc",
            lookback_minutes=45,
        )
        assert result is None


class TestCreateOrUpdateIncident:
    async def test_creates_new_incident_when_no_duplicate(self):

        db = AsyncMock()
        # No duplicate found
        mock_exact = MagicMock()
        mock_exact.scalar_one_or_none.return_value = None
        mock_fuzzy = MagicMock()
        mock_fuzzy.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[mock_exact, mock_fuzzy])
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        # Mock refresh to set a fake id
        async def fake_refresh(obj):
            pass
        db.refresh = fake_refresh

        incident, created = await create_or_update_incident(
            db=db,
            service="api",
            title="High Latency",
            description="Latency exceeded threshold",
            severity="high",
            auto_commit=True,
        )
        assert created is True
        db.add.assert_called_once()
        db.commit.assert_awaited_once()

    async def test_updates_existing_incident_on_duplicate(self):
        from unittest.mock import MagicMock


        service = "payment-service"
        description = "memory leak in cache"

        existing = MagicMock()
        existing.affected_service = service
        existing.description = description
        existing.affected_components = None
        existing.metrics_snapshot = {}
        existing.context = {}
        existing.severity = MagicMock()
        existing.severity.value = "medium"

        db = AsyncMock()
        mock_exact = MagicMock()
        mock_exact.scalar_one_or_none.return_value = existing
        db.execute = AsyncMock(return_value=mock_exact)
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        async def fake_refresh(obj):
            pass
        db.refresh = fake_refresh

        incident, created = await create_or_update_incident(
            db=db,
            service=service,
            title="Memory Leak",
            description=description,
            severity="high",
            metrics_snapshot={"cpu": 90},
            context={"source": "monitor"},
            auto_commit=True,
        )
        assert created is False
        assert incident is existing

    async def test_no_auto_commit_skips_commit(self):
        db = AsyncMock()
        mock_exact = MagicMock()
        mock_exact.scalar_one_or_none.return_value = None
        mock_fuzzy = MagicMock()
        mock_fuzzy.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[mock_exact, mock_fuzzy])
        db.flush = AsyncMock()

        incident, created = await create_or_update_incident(
            db=db,
            service="svc",
            title="Issue",
            description="Something happened",
            severity="low",
            auto_commit=False,
        )
        assert created is True
        db.commit.assert_not_awaited()
