"""
AIRRA Eval Harness — Hypothesis Confidence Scoring

Tests whether calculate_hypothesis_confidence correctly ranks the expected
category highest for each golden fixture. Runnable in CI without an LLM API key.

Usage:
    python -m tests.evals.score
    python -m tests.evals.score --min-accuracy 0.80
"""
import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# Add backend root to path when run directly
BACKEND_ROOT = Path(__file__).parent.parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Minimal env config so settings import succeeds without a real DB/Redis
os.environ.setdefault("AIRRA_API_KEY", "eval-harness-key")
os.environ.setdefault("AIRRA_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("AIRRA_REDIS_URL", "redis://localhost:6379/0")

from app.core.perception.anomaly_detector import AnomalyDetection  # noqa: E402
from app.core.reasoning.hypothesis_generator import (  # noqa: E402
    Evidence,
    HypothesisItemLLM,
    calculate_hypothesis_confidence,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@dataclass
class EvalResult:
    fixture_id: str
    passed: bool
    expected_category: str
    actual_top_category: str
    actual_confidence: float
    confidence_in_range: bool
    expected_min: float
    expected_max: float
    failure_reason: str = ""


def load_fixture(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def build_anomalies(raw: list[dict]) -> list[AnomalyDetection]:
    now = datetime.now(timezone.utc)
    return [
        AnomalyDetection(
            metric_name=a["metric_name"],
            is_anomaly=a["is_anomaly"],
            confidence=a["confidence"],
            current_value=a["current_value"],
            expected_value=a["expected_value"],
            deviation_sigma=a["deviation_sigma"],
            timestamp=now,
            context=a.get("context", {}),
        )
        for a in raw
    ]


def build_hypothesis_llm(raw: dict) -> HypothesisItemLLM:
    return HypothesisItemLLM(
        description=raw["description"],
        category=raw["category"],
        evidence=[
            Evidence(
                signal_type=e["signal_type"],
                signal_name=e["signal_name"],
                observation=e["observation"],
                relevance=e["relevance"],
            )
            for e in raw["evidence"]
        ],
        reasoning=raw["reasoning"],
    )


def run_fixture(fixture: dict) -> EvalResult:
    anomalies = build_anomalies(fixture["anomalies"])
    hypotheses_llm = [build_hypothesis_llm(h) for h in fixture["mocked_llm_hypotheses"]]
    expected_category = fixture["expected_top_category"]
    conf_min = fixture["expected_confidence_min"]
    conf_max = fixture["expected_confidence_max"]

    scored = [
        (h, calculate_hypothesis_confidence(h, anomalies))
        for h in hypotheses_llm
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    top_hypothesis, top_confidence = scored[0]
    actual_category = top_hypothesis.category
    confidence_in_range = conf_min <= top_confidence <= conf_max

    passed = (actual_category == expected_category) and confidence_in_range

    failure_reason = ""
    if actual_category != expected_category:
        failure_reason = f"category mismatch: got '{actual_category}'"
    elif not confidence_in_range:
        failure_reason = f"confidence {top_confidence:.3f} outside [{conf_min}, {conf_max}]"

    return EvalResult(
        fixture_id=fixture["id"],
        passed=passed,
        expected_category=expected_category,
        actual_top_category=actual_category,
        actual_confidence=top_confidence,
        confidence_in_range=confidence_in_range,
        expected_min=conf_min,
        expected_max=conf_max,
        failure_reason=failure_reason,
    )


def main(min_accuracy: float = 0.80) -> int:
    fixture_files = sorted(FIXTURES_DIR.glob("*.json"))
    if not fixture_files:
        print(f"ERROR: No fixture files found in {FIXTURES_DIR}")
        return 1

    print("AIRRA Hypothesis Generator — Eval Harness")
    print("==========================================")
    print(f"Running {len(fixture_files)} fixture(s)...\n")

    results: list[EvalResult] = []
    for i, path in enumerate(fixture_files, 1):
        fixture = load_fixture(path)
        result = run_fixture(fixture)
        results.append(result)

        status = "PASS" if result.passed else "FAIL"
        conf_range = f"[{result.expected_min:.2f}–{result.expected_max:.2f}]"
        detail = (
            f"top={result.actual_top_category:<20} conf={result.actual_confidence:.3f} {conf_range}"
        )
        if not result.passed:
            detail += f"  ← {result.failure_reason}"

        print(f"  {i:>2}/{len(fixture_files)}  {result.fixture_id:<25} {status}  {detail}")

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    accuracy = passed / total if total > 0 else 0.0

    print(f"\nScore: {passed}/{total} ({accuracy:.1%})", end="")

    if accuracy >= min_accuracy:
        print(f" -- PASSED [OK] (threshold: {min_accuracy:.0%})")
        return 0
    else:
        print(f" -- FAILED [FAIL] (threshold: {min_accuracy:.0%})")
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AIRRA eval harness")
    parser.add_argument(
        "--min-accuracy",
        type=float,
        default=0.80,
        help="Minimum fraction of fixtures that must pass (default: 0.80)",
    )
    args = parser.parse_args()
    sys.exit(main(min_accuracy=args.min_accuracy))
