"""
AIRRA end-to-end eval benchmark.

Runs the real perception / reasoning / decision components over the synthetic
incident corpus (tests/evals/dataset/incidents.jsonl) and reports how well each
stage performs against ground truth.

    python -m tests.evals.benchmark
    python -m tests.evals.benchmark --limit 40 --json out.json
    python -m tests.evals.benchmark --min-detection-recall 0.85 --min-diagnosis-top1 0.70

Stages measured:
  Detection    precision / recall / false-positive-rate  (real AnomalyDetector)
  Retrieval    Recall@3 / MRR                             (all-MiniLM-L6-v2 + composite re-rank)
  Diagnosis    top-1 / top-3 root-cause accuracy          (real calculate_hypothesis_confidence)
  Remediation  correct-action / unsafe-action / policy-rejection / no-rule rates
                                                          (real ActionSelector + PolicyEngine)
  System       detection compute p50/p95, projected LLM calls & cost per incident

No live LLM calls — every number here is reproducible in CI. "Detection compute"
is the detector's own runtime, NOT the ~90-120s end-to-end pipeline floor
(Beat cycle + Prometheus scrape), which this harness does not exercise.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_ROOT = Path(__file__).parent.parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AIRRA_API_KEY", "eval-harness-key")
os.environ.setdefault("AIRRA_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("AIRRA_REDIS_URL", "redis://localhost:6379/0")

from app.core.decision.action_selector import ActionSelector  # noqa: E402
from app.core.perception.anomaly_detector import AnomalyDetector  # noqa: E402
from app.core.reasoning.hypothesis_generator import (  # noqa: E402
    Evidence,
    HypothesisItem,
    HypothesisItemLLM,
    calculate_hypothesis_confidence,
)
from app.services.prometheus_client import MetricDataPoint, MetricResult  # noqa: E402
from tests.evals.archetypes import CATEGORIES  # noqa: E402

DATASET_PATH = Path(__file__).parent / "dataset" / "incidents.jsonl"

# Action types that mutate state — used to flag "unsafe action on protected service".
DESTRUCTIVE_ACTIONS = {"restart_pod", "rollback_deployment", "scale_down", "drain_node"}
PROTECTED_HINTS = ("postgres", "redis", "payment", "database", "auth")

# Projected LLM economics per incident (analysis prompt + RAG context + response).
# One Sonnet analysis call per incident; sizes are template estimates, not measured.
PROJECTED_LLM_CALLS_PER_INCIDENT = 1
PROJECTED_PROMPT_TOKENS = 2200
PROJECTED_COMPLETION_TOKENS = 700
# claude-sonnet class list price, USD per 1M tokens
PRICE_IN_PER_MTOK = 3.0
PRICE_OUT_PER_MTOK = 15.0


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _load(limit: int | None) -> list[dict]:
    if not DATASET_PATH.exists():
        raise SystemExit(
            f"missing {DATASET_PATH} — run `python -m tests.evals.generate_dataset` first"
        )
    rows = [json.loads(line) for line in DATASET_PATH.read_text().splitlines() if line.strip()]
    return rows[:limit] if limit else rows


def _metric_result(window: dict) -> MetricResult:
    return MetricResult(
        metric_name=window["metric_name"],
        labels={"service": "eval"},
        values=[MetricDataPoint(timestamp=float(i), value=v) for i, v in enumerate(window["values"])],
    )


def _pct(n: int, d: int) -> float:
    return n / d if d else 0.0


def _p(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(q * len(s)))]


# --------------------------------------------------------------------------- #
# stage: detection
# --------------------------------------------------------------------------- #
@dataclass
class DetectionReport:
    precision: float
    recall: float
    false_positive_rate: float
    tp: int
    fn: int
    fp: int
    tn: int
    compute_ms_p50: float
    compute_ms_p95: float


def run_detection(rows: list[dict]) -> DetectionReport:
    detector = AnomalyDetector()
    tp = fn = fp = tn = 0
    timings: list[float] = []

    for row in rows:
        fault = _metric_result(row["metric_window"])
        clean = _metric_result(row["clean_window"])

        t0 = time.perf_counter()
        fault_hit = bool(detector.detect_multiple([fault]))
        timings.append((time.perf_counter() - t0) * 1000)

        clean_hit = bool(detector.detect_multiple([clean]))

        tp += fault_hit
        fn += not fault_hit
        fp += clean_hit
        tn += not clean_hit

    return DetectionReport(
        precision=_pct(tp, tp + fp),
        recall=_pct(tp, tp + fn),
        false_positive_rate=_pct(fp, fp + tn),
        tp=tp,
        fn=fn,
        fp=fp,
        tn=tn,
        compute_ms_p50=_p(timings, 0.50),
        compute_ms_p95=_p(timings, 0.95),
    )


# --------------------------------------------------------------------------- #
# stage: diagnosis
# --------------------------------------------------------------------------- #
# Truth and distractors get the SAME evidence count and a relevance draw from
# the SAME tight band (0.60-0.85), seeded per-incident so a distractor's draw
# beats the truth's roughly as often as it doesn't -- no artificial evidence-
# quality tell for the ranker to key off. What decides top-1/top-3 now is
# whatever the real deterministic confidence formula actually weighs besides
# evidence: category priors (error_spike 0.85 vs. network_issue 0.55) and
# anomaly strength. A high-prior distractor beating a low-prior truth on a
# close evidence roll is a real failure mode, not a harness bug -- that's
# what this metric is now built to surface instead of hide.
_RELEVANCE_LOW, _RELEVANCE_HIGH = 0.60, 0.85
_EVIDENCE_COUNT = 2


def _candidates(row: dict) -> tuple[list[HypothesisItemLLM], str]:
    truth = row["ground_truth"]["root_cause_category"]
    metric = row["metric_window"]["metric_name"]
    cats = [truth, *[c for c in row["distractor_categories"] if c != truth]]
    rng = random.Random(row["id"])  # reproducible per incident, varies across the corpus

    out: list[HypothesisItemLLM] = []
    for cat in cats:
        relevance = rng.uniform(_RELEVANCE_LOW, _RELEVANCE_HIGH)
        out.append(
            HypothesisItemLLM(
                description=f"{cat} in service — {row['description'][:80]}",
                category=cat,
                evidence=[
                    Evidence(
                        signal_type="metric",
                        signal_name=metric,
                        observation=f"{metric} deviated from baseline",
                        relevance=round(relevance - 0.03 * j, 3),
                    )
                    for j in range(_EVIDENCE_COUNT)
                ],
                reasoning=f"Observed {metric} pattern is consistent with {cat}.",
            )
        )
    return out, truth


@dataclass
class DiagnosisReport:
    top1_accuracy: float
    top3_accuracy: float
    n: int


def run_diagnosis(rows: list[dict]) -> DiagnosisReport:
    detector = AnomalyDetector()
    top1 = top3 = 0

    for row in rows:
        anomalies = detector.detect_multiple([_metric_result(row["metric_window"])])
        candidates, truth = _candidates(row)
        scored = sorted(
            ((h, calculate_hypothesis_confidence(h, anomalies)) for h in candidates),
            key=lambda x: x[1],
            reverse=True,
        )
        ranked = [h.category for h, _ in scored]
        top1 += ranked[0] == truth
        top3 += truth in ranked[:3]

    return DiagnosisReport(
        top1_accuracy=_pct(top1, len(rows)),
        top3_accuracy=_pct(top3, len(rows)),
        n=len(rows),
    )


# --------------------------------------------------------------------------- #
# stage: remediation
# --------------------------------------------------------------------------- #
@dataclass
class RemediationReport:
    correct_action_rate: float
    unsafe_action_rate: float
    policy_rejection_rate: float
    no_rule_rate: float
    n: int


def run_remediation(rows: list[dict]) -> RemediationReport:
    selector = ActionSelector()
    correct = unsafe = policy_rej = no_rule = 0

    for row in rows:
        gt = row["ground_truth"]
        truth_cat = gt["root_cause_category"]
        service = row["service"]
        hypothesis = HypothesisItem(
            description=row["description"][:120],
            category=truth_cat,
            confidence_score=0.75,
            evidence=[
                Evidence(
                    signal_type="metric",
                    signal_name=row["metric_window"]["metric_name"],
                    observation="deviated",
                    relevance=0.85,
                )
            ],
            reasoning="eval",
        )
        rec = selector.select(hypothesis, service)

        if rec is None:
            if selector.last_policy_veto:
                policy_rej += 1
            else:
                no_rule += 1
            continue

        if rec.action_type.value == gt["remediation_action"]:
            correct += 1
        if (
            rec.action_type.value in DESTRUCTIVE_ACTIONS
            and any(h in rec.target_service.lower() for h in PROTECTED_HINTS)
            and not rec.requires_approval
        ):
            unsafe += 1

    n = len(rows)
    return RemediationReport(
        correct_action_rate=_pct(correct, n),
        unsafe_action_rate=_pct(unsafe, n),
        policy_rejection_rate=_pct(policy_rej, n),
        no_rule_rate=_pct(no_rule, n),
        n=n,
    )


# --------------------------------------------------------------------------- #
# stage: retrieval  (optional — needs sentence-transformers + model weights)
# --------------------------------------------------------------------------- #
@dataclass
class RetrievalReport:
    skipped: bool
    reason: str = ""
    recall_at_3: float = 0.0
    mrr: float = 0.0
    vector_only_recall_at_3: float = 0.0
    vector_only_mrr: float = 0.0
    n: int = 0


_CANONICAL_PATTERNS = {
    "memory_leak_gradual": ("order-service", "process_resident_memory_bytes",
        "Resident memory grows steadily with no plateau, GC pauses lengthen, traffic flat — classic unbounded allocation leak."),
    "memory_leak_sudden": ("order-service", "process_resident_memory_bytes",
        "Heap steps up after a warm-up and stays elevated — unbounded in-memory cache or collection."),
    "cpu_spike_busyloop": ("api-gateway", "cpu_usage_percent",
        "CPU pinned near 100%, thread pool saturated, handler stuck in a busy loop or hot path."),
    "traffic_spike_flash": ("api-gateway", "http_requests_per_second",
        "Request rate surges several-fold within a minute, latency still nominal — flash crowd or bot flood."),
    "latency_spike_p99": ("checkout-service", "http_request_duration_p99_seconds",
        "p99 latency climbs over minutes while error rate stays flat, downstream calls slow."),
    "error_spike_bad_deploy": ("payment-service", "http_5xx_rate_percent",
        "5xx rate jumps immediately after a rollout, stack traces in the new code path — bad deploy."),
    "database_issue_slow_query": ("order-service", "db_query_duration_p95_seconds",
        "DB query p95 climbs, connection pool near exhaustion, missing index after data growth."),
    "network_issue_packet_loss": ("search-service", "tcp_retransmit_rate_percent",
        "Intermittent TCP retransmits and sporadic timeouts to downstream, one link flaky."),
    "deployment_issue_crashloop": ("user-service", "pod_restart_count",
        "Pods in CrashLoopBackOff, restart count rising since last deploy, readiness probe failing on bad config."),
    "redis_outage_cascade": ("api-gateway", "cache_hit_rate_percent",
        "Cache hit rate collapses to near zero, many services slow at once, shared Redis cluster down."),
}


def run_retrieval(rows: list[dict]) -> RetrievalReport:
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as e:  # noqa: BLE001
        return RetrievalReport(skipped=True, reason=f"sentence-transformers unavailable: {e}")

    try:
        model = SentenceTransformer("all-MiniLM-L6-v2")
    except Exception as e:  # noqa: BLE001
        return RetrievalReport(skipped=True, reason=f"model load failed: {e}")

    keys = list(_CANONICAL_PATTERNS)
    pat_services = [_CANONICAL_PATTERNS[k][0] for k in keys]
    pat_metrics = [_CANONICAL_PATTERNS[k][1] for k in keys]
    pat_vecs = model.encode([_CANONICAL_PATTERNS[k][2] for k in keys], normalize_embeddings=True)

    inc_vecs = model.encode([r["description"] for r in rows], normalize_embeddings=True)

    hits_at_3 = 0
    rr_total = 0.0
    vec_hits_at_3 = 0
    vec_rr_total = 0.0
    for row, vec in zip(rows, inc_vecs):
        cosines = [float((vec * pat_vecs[i]).sum()) for i in range(len(keys))]

        # composite re-rank per CLAUDE.md: 0.5*vector + 0.3*service + 0.2*metric
        scores = []
        for i, k in enumerate(keys):
            svc = 1.0 if pat_services[i] == row["service"] else 0.0
            met = 1.0 if pat_metrics[i] == row["metric_window"]["metric_name"] else 0.0
            scores.append((k, 0.5 * cosines[i] + 0.3 * svc + 0.2 * met))
        scores.sort(key=lambda x: x[1], reverse=True)
        ranked = [k for k, _ in scores]
        rank = ranked.index(row["archetype"]) + 1
        hits_at_3 += rank <= 3
        rr_total += 1.0 / rank

        # vector-only: isolates what the embedding model itself contributes,
        # since service+metric are deterministic per archetype in this synthetic
        # corpus and can otherwise carry the composite score on their own.
        vec_scores = sorted(zip(keys, cosines), key=lambda x: x[1], reverse=True)
        vec_ranked = [k for k, _ in vec_scores]
        vec_rank = vec_ranked.index(row["archetype"]) + 1
        vec_hits_at_3 += vec_rank <= 3
        vec_rr_total += 1.0 / vec_rank

    n = len(rows)
    return RetrievalReport(
        skipped=False,
        recall_at_3=_pct(hits_at_3, n),
        mrr=rr_total / n if n else 0.0,
        vector_only_recall_at_3=_pct(vec_hits_at_3, n),
        vector_only_mrr=vec_rr_total / n if n else 0.0,
        n=n,
    )


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #
@dataclass
class Benchmark:
    detection: DetectionReport
    diagnosis: DiagnosisReport
    remediation: RemediationReport
    retrieval: RetrievalReport
    system: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "detection": self.detection.__dict__,
            "diagnosis": self.diagnosis.__dict__,
            "remediation": self.remediation.__dict__,
            "retrieval": self.retrieval.__dict__,
            "system": self.system,
        }


def run(rows: list[dict], with_retrieval: bool) -> Benchmark:
    detection = run_detection(rows)
    diagnosis = run_diagnosis(rows)
    remediation = run_remediation(rows)
    retrieval = (
        run_retrieval(rows)
        if with_retrieval
        else RetrievalReport(skipped=True, reason="disabled via --no-retrieval")
    )

    proj_cost = (
        PROJECTED_PROMPT_TOKENS / 1e6 * PRICE_IN_PER_MTOK
        + PROJECTED_COMPLETION_TOKENS / 1e6 * PRICE_OUT_PER_MTOK
    )
    system = {
        "incidents": len(rows),
        "detection_compute_ms_p50": round(detection.compute_ms_p50, 3),
        "detection_compute_ms_p95": round(detection.compute_ms_p95, 3),
        "projected_llm_calls_per_incident": PROJECTED_LLM_CALLS_PER_INCIDENT,
        "projected_cost_per_incident_usd": round(proj_cost, 5),
        "note": "compute time is the detector algorithm only; end-to-end detection "
        "latency floor is ~90-120s (Beat cycle + scrape). Cost is projected from "
        "prompt-template sizes, not measured calls.",
    }
    return Benchmark(detection, diagnosis, remediation, retrieval, system)


def _print(bm: Benchmark) -> None:
    d, dg, rm, rt = bm.detection, bm.diagnosis, bm.remediation, bm.retrieval
    print("\nAIRRA Benchmark")
    print("=" * 60)
    print(f"corpus: {bm.system['incidents']} incidents\n")

    print("DETECTION   (real AnomalyDetector: z-score + EWMA + MAD)")
    print(f"  precision            {d.precision:.3f}")
    print(f"  recall              {d.recall:.3f}   (tp={d.tp} fn={d.fn})")
    print(f"  false-positive rate  {d.false_positive_rate:.3f}   (fp={d.fp} tn={d.tn})")
    print(f"  compute p50 / p95    {d.compute_ms_p50:.2f}ms / {d.compute_ms_p95:.2f}ms\n")

    print("RETRIEVAL   (all-MiniLM-L6-v2 + composite re-rank)")
    if rt.skipped:
        print(f"  SKIPPED — {rt.reason}\n")
    else:
        print(f"  Recall@3 (composite)     {rt.recall_at_3:.3f}")
        print(f"  MRR (composite)          {rt.mrr:.3f}")
        print(f"  Recall@3 (vector only)   {rt.vector_only_recall_at_3:.3f}   "
              f"<- isolates the embedding model; service+metric match is a")
        print(f"  MRR (vector only)        {rt.vector_only_mrr:.3f}      "
              f"deterministic tell in this synthetic corpus, so composite alone overstates it\n")

    print("DIAGNOSIS   (real calculate_hypothesis_confidence)")
    print(f"  top-1 accuracy      {dg.top1_accuracy:.3f}")
    print(f"  top-3 accuracy      {dg.top3_accuracy:.3f}\n")

    print("REMEDIATION (real ActionSelector + PolicyEngine)")
    print(f"  correct action      {rm.correct_action_rate:.3f}")
    print(f"  unsafe action       {rm.unsafe_action_rate:.3f}   (want ~0)")
    print(f"  policy rejection    {rm.policy_rejection_rate:.3f}")
    print(f"  no-rule (map gap)   {rm.no_rule_rate:.3f}\n")

    print("SYSTEM")
    print(f"  detection compute p50/p95   {bm.system['detection_compute_ms_p50']}ms / "
          f"{bm.system['detection_compute_ms_p95']}ms")
    print(f"  projected LLM calls/incident {bm.system['projected_llm_calls_per_incident']}")
    print(f"  projected cost/incident      ${bm.system['projected_cost_per_incident_usd']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=None, help="cap incidents (default: all)")
    ap.add_argument("--no-retrieval", action="store_true", help="skip the embedding stage")
    ap.add_argument("--json", type=str, default=None, help="write full report to this path")
    ap.add_argument("--min-detection-recall", type=float, default=None)
    ap.add_argument("--min-detection-precision", type=float, default=None)
    ap.add_argument("--max-false-positive-rate", type=float, default=None)
    ap.add_argument("--min-diagnosis-top1", type=float, default=None)
    ap.add_argument("--min-diagnosis-top3", type=float, default=None)
    ap.add_argument("--min-remediation-correct", type=float, default=None)
    ap.add_argument("--max-unsafe-action-rate", type=float, default=None)
    args = ap.parse_args()

    rows = _load(args.limit)
    bm = run(rows, with_retrieval=not args.no_retrieval)
    _print(bm)

    if args.json:
        Path(args.json).write_text(json.dumps(bm.to_json(), indent=2))
        print(f"\nreport -> {args.json}")
    else:
        default_out = Path(__file__).parent / "dataset" / "report.json"
        default_out.write_text(json.dumps(bm.to_json(), indent=2))

    checks = [
        ("detection recall", args.min_detection_recall, bm.detection.recall, "min"),
        ("detection precision", args.min_detection_precision, bm.detection.precision, "min"),
        ("false-positive rate", args.max_false_positive_rate, bm.detection.false_positive_rate, "max"),
        ("diagnosis top-1", args.min_diagnosis_top1, bm.diagnosis.top1_accuracy, "min"),
        ("diagnosis top-3", args.min_diagnosis_top3, bm.diagnosis.top3_accuracy, "min"),
        ("remediation correct", args.min_remediation_correct, bm.remediation.correct_action_rate, "min"),
        ("unsafe action rate", args.max_unsafe_action_rate, bm.remediation.unsafe_action_rate, "max"),
    ]
    failed = []
    for name, threshold, actual, kind in checks:
        if threshold is None:
            continue
        ok = actual >= threshold if kind == "min" else actual <= threshold
        if not ok:
            failed.append(f"{name}={actual:.3f} fails {kind}={threshold:.3f}")

    if failed:
        print("\nGATE FAILED:")
        for f in failed:
            print(f"  - {f}")
        return 1
    if any(t is not None for _, t, _, _ in checks):
        print("\nGATE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
