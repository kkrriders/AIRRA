"""Measure whether verified incident outcomes improve subsequent diagnosis ranking.

The corpus is split deterministically into a 120-incident learning period and
a disjoint 120-incident held-out period. The warm condition only receives the
verified (service, root-cause) outcome from the first half, the same feedback
that ``LearningEngine`` persists as an IncidentPattern in production.

    python -m tests.evals.learning_experiment

This evaluates the deterministic feedback confidence adjustment. It does not
pretend to measure live LLM quality or an embedding model's semantic recall;
those remain separately measured by ``tests.evals.benchmark``.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).parent.parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AIRRA_API_KEY", "eval-harness-key")
os.environ.setdefault("AIRRA_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("AIRRA_REDIS_URL", "redis://localhost:6379/0")

from app.core.perception.anomaly_detector import AnomalyDetection  # noqa: E402
from app.core.reasoning.hypothesis_generator import (  # noqa: E402
    Evidence,
    HypothesisItemLLM,
    calculate_hypothesis_confidence,
)

DATASET = Path(__file__).parent / "dataset" / "incidents.jsonl"
DISTRACTORS = ("error_spike", "deployment_issue", "traffic_spike")


@dataclass
class LearningReport:
    train_incidents: int
    held_out_incidents: int
    cold_top1_accuracy: float
    cold_top3_accuracy: float
    learned_top1_accuracy: float
    learned_top3_accuracy: float
    learned_patterns: int


def _load() -> list[dict]:
    return [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]


def _anomaly(row: dict) -> AnomalyDetection:
    values = row["metric_window"]["values"]
    return AnomalyDetection(
        metric_name=row["metric_window"]["metric_name"],
        is_anomaly=True,
        confidence=0.85,
        current_value=values[-1],
        expected_value=sum(values[:-1]) / (len(values) - 1),
        deviation_sigma=4.0,
        timestamp=datetime.now(timezone.utc),
        context={"labels": {"service": row["service"]}},
    )


def _rank(row: dict, adjustments: dict[tuple[str, str], float]) -> list[str]:
    truth = row["ground_truth"]["root_cause_category"]
    categories = [truth, *[d for d in DISTRACTORS if d != truth]]
    candidates = []
    for category in categories:
        # Candidates are intentionally close: a high-prior category can beat
        # the true category when evidence is incomplete. Learning has a genuine
        # opportunity to change the rank, rather than being guaranteed a win.
        relevance = 0.72 if category == truth else 0.78
        candidate = HypothesisItemLLM(
            description=f"{category}: {row['description']}",
            category=category,
            evidence=[Evidence(signal_type="metric", signal_name=row["metric_window"]["metric_name"], observation="deviated", relevance=relevance)],
            reasoning="eval candidate",
        )
        score = calculate_hypothesis_confidence(
            candidate,
            [_anomaly(row)],
            affected_service=row["service"],
            pattern_adjustment=adjustments.get((row["service"], category), 0.0),
        )
        candidates.append((category, score))
    return [category for category, _ in sorted(candidates, key=lambda item: item[1], reverse=True)]


def _accuracy(rows: list[dict], adjustments: dict[tuple[str, str], float]) -> tuple[float, float]:
    top1 = top3 = 0
    for row in rows:
        truth = row["ground_truth"]["root_cause_category"]
        ranked = _rank(row, adjustments)
        top1 += ranked[0] == truth
        top3 += truth in ranked[:3]
    return top1 / len(rows), top3 / len(rows)


def run() -> LearningReport:
    rows = _load()
    midpoint = len(rows) // 2
    train, held_out = rows[:midpoint], rows[midpoint:]

    # Equivalent to a verified correct outcome for each training incident:
    # after repeated successful outcomes, LearningEngine assigns +0.10 to the
    # matching service/category pattern. No held-out root cause is consulted.
    observed = {(row["service"], row["ground_truth"]["root_cause_category"]) for row in train}
    adjustments = {pattern: 0.10 for pattern in observed}
    cold_top1, cold_top3 = _accuracy(held_out, {})
    learned_top1, learned_top3 = _accuracy(held_out, adjustments)
    return LearningReport(
        train_incidents=len(train),
        held_out_incidents=len(held_out),
        cold_top1_accuracy=cold_top1,
        cold_top3_accuracy=cold_top3,
        learned_top1_accuracy=learned_top1,
        learned_top3_accuracy=learned_top3,
        learned_patterns=len(adjustments),
    )


def main() -> int:
    report = run()
    print("AIRRA Feedback Learning Experiment")
    print(f"cold top-1/top-3:    {report.cold_top1_accuracy:.1%} / {report.cold_top3_accuracy:.1%}")
    print(f"learned top-1/top-3: {report.learned_top1_accuracy:.1%} / {report.learned_top3_accuracy:.1%}")
    print(f"verified patterns:    {report.learned_patterns} from {report.train_incidents} training incidents")
    print(f"held-out incidents:   {report.held_out_incidents}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
