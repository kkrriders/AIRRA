"""
Pytest wrapper for the eval harness golden fixtures.

Each fixture becomes a separate parametrized test, so pytest --tb=short shows
exactly which scenario failed and why. The score.py script provides the
human-readable summary; this file provides CI integration via pytest.
"""
import json
import os
from pathlib import Path

import pytest

from tests.evals.score import build_anomalies, build_hypothesis_llm, run_fixture

FIXTURES_DIR = Path(__file__).parent / "fixtures"

_fixtures = [
    pytest.param(json.loads(p.read_text()), id=p.stem)
    for p in sorted(FIXTURES_DIR.glob("*.json"))
]


@pytest.mark.parametrize("fixture", _fixtures)
def test_expected_category_ranks_first(fixture: dict) -> None:
    """Top-scored hypothesis must match expected_top_category for each golden scenario."""
    result = run_fixture(fixture)

    assert result.actual_top_category == result.expected_category, (
        f"[{fixture['id']}] Expected top category '{result.expected_category}' "
        f"but got '{result.actual_top_category}' "
        f"(confidence={result.actual_confidence:.3f}). "
        f"Description: {fixture['description']}"
    )


@pytest.mark.parametrize("fixture", _fixtures)
def test_confidence_within_expected_range(fixture: dict) -> None:
    """Winner confidence score must be within the expected calibrated range."""
    result = run_fixture(fixture)

    assert result.confidence_in_range, (
        f"[{fixture['id']}] Confidence {result.actual_confidence:.3f} is outside "
        f"expected range [{result.expected_min:.2f}, {result.expected_max:.2f}]. "
        f"Category: {result.actual_top_category}"
    )
