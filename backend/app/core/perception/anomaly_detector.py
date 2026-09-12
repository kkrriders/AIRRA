"""
Anomaly detection using an ensemble of statistical methods.

Why an ensemble instead of a single z-score:
- **Z-score** reacts fast to sudden spikes but is fragile: a single outlier in
  the baseline inflates the stdev, and a slow drift moves the mean with it so
  the spike is never >Nσ.
- **EWMA drift** (exponentially weighted moving average) tracks the *trend* of
  the series. A gradual ramp accumulates in the smoothed statistic and crosses
  the control limit even when no individual point is a 3σ jump.
- **MAD** (median absolute deviation) is a robust z-score. The median and MAD
  ignore a handful of historical outliers, so a real anomaly is still visible
  when a prior spike has polluted the baseline window.

Each method votes. A point is an anomaly when `min_votes` methods agree, or when
any single method's score is extreme (unambiguous spike). This keeps recall high
without the false-positive rate of an OR of three independent tests.

No ML model here on purpose — robust statistics + correlation + RAG reasoning is
a better engineering story than a black-box detector nobody can debug at 3am.
"""
import logging
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import NamedTuple

from app.config import settings
from app.services.prometheus_client import MetricResult

logger = logging.getLogger(__name__)

# A method that clears (this * threshold_sigma) is trusted to flag on its own.
# Between 1x and 1.5x threshold a second method must agree (min_votes); past
# 1.5x the signal is unambiguous enough to stand alone. This is what lets a
# single method cover the others' blind spots (EWMA for drift, MAD for a
# baseline polluted by an old spike) instead of being out-voted.
STRONG_SINGLE_METHOD_SIGMA_MULTIPLIER = 1.5

# MAD -> stdev scale factor for a normal distribution (so MAD scores are
# comparable to z-scores).
_MAD_TO_SIGMA = 0.6745

# EWMA drift: relative movement -> sigma-equivalent. ~20% sustained drift reads
# as ~3 sigma. Heuristic — re-tune against the eval fixtures once they exist.
_EWMA_DRIFT_SCALE = 15.0
# Fraction of total EWMA movement that must be net-directional for it to count
# as drift rather than a spike-and-recover.
_EWMA_DIRECTION_RATIO = 0.6


@dataclass
class AnomalyDetection:
    """Result of anomaly detection."""

    metric_name: str
    is_anomaly: bool
    confidence: float  # 0.0 to 1.0
    current_value: float
    expected_value: float
    deviation_sigma: float
    timestamp: datetime
    context: dict
    methods_triggered: list[str] = field(default_factory=list)


class _MethodResult(NamedTuple):
    """Per-method verdict for a single point."""

    name: str
    is_anomaly: bool
    score: float  # deviation in sigma-equivalent units (>= 0)
    detail: dict


def _relative_deviation_sigma(current: float, reference: float) -> float:
    """
    Fallback "sigma-equivalent" score when there is no usable spread estimate
    (stdev or MAD is zero). Scale-free: divide the gap by the larger magnitude
    so the score stays bounded regardless of sign or units, then ×10 so a 30%
    jump reads as ~3 sigma.
    """
    if current == reference:
        return 0.0
    base = max(abs(reference), abs(current), 1.0)
    return (abs(current - reference) / base) * 10.0


def _spread_floor(reference: float) -> float:
    """
    Practical noise floor for a baseline's stdev/MAD. Below this, floating-point
    jitter on a flat, near-idle metric (e.g. a health-check endpoint sitting at
    ~0.05 req/s) produces a spread estimate too tiny to be a real signal --
    dividing by it blows the z-score/MAD-sigma up into a false-positive
    "critical" reading even for noise-level movement. Same class of bug the
    Prometheus alert rules guard against with clamp_min() (see
    monitoring/prometheus/alerts/ai-platform-anomaly.yml).

    0.1% of the baseline's own magnitude, floored at 0.01 absolute -- the
    relative term alone is too coarse for a small-magnitude metric (0.01
    matches the request_rate clamp_min already used in the YAML rules), and
    an absolute-only floor would swallow genuine tight-but-real spread on a
    large-magnitude metric (e.g. stdev ~0.3 on a ~100-unit baseline).
    """
    return max(abs(reference) * 0.001, 0.01)


def _ewma_series(values: list[float], alpha: float) -> list[float]:
    """Exponentially weighted moving average, seeded with the first value."""
    smoothed = values[0]
    out = [smoothed]
    for v in values[1:]:
        smoothed = alpha * v + (1 - alpha) * smoothed
        out.append(smoothed)
    return out


def _zscore_method(baseline: list[float], current: float, threshold: float) -> _MethodResult:
    mean = statistics.mean(baseline)
    try:
        stdev = statistics.stdev(baseline)
    except statistics.StatisticsError:
        stdev = 0.0

    if stdev < _spread_floor(mean):
        score = _relative_deviation_sigma(current, mean)
    else:
        score = abs(current - mean) / stdev

    return _MethodResult(
        name="zscore",
        is_anomaly=score > threshold,
        score=score,
        detail={"mean": mean, "stdev": stdev},
    )


def _ewma_method(
    all_values: list[float], threshold: float, alpha: float
) -> _MethodResult:
    """
    Flag sustained directional drift — the failure mode z-score and MAD both
    miss, because a slow ramp drags the mean/median along with it.

    We smooth the series, then check two things:
      1. net travel (start -> end of the smoothed line) as a fraction of the
         starting level, scaled to sigma-equivalent units;
      2. that the movement is mostly one-directional, not a spike that recovered
         (which MAD/z already handle).
    Mean-reverting noise nets out near zero on both counts.
    """
    series = _ewma_series(all_values, alpha)
    net = series[-1] - series[0]
    total_variation = sum(
        abs(series[i] - series[i - 1]) for i in range(1, len(series))
    )
    directional = total_variation > 0 and abs(net) / total_variation >= _EWMA_DIRECTION_RATIO

    if directional:
        base = max(abs(series[0]), 1.0)
        score = (abs(net) / base) * _EWMA_DRIFT_SCALE
    else:
        score = 0.0

    return _MethodResult(
        name="ewma",
        is_anomaly=score > threshold,
        score=score,
        detail={
            "ewma_current": series[-1],
            "ewma_start": series[0],
            "drift": net,
            "directional": directional,
        },
    )


def _mad_method(baseline: list[float], current: float, threshold: float) -> _MethodResult:
    median = statistics.median(baseline)
    mad = statistics.median([abs(x - median) for x in baseline])

    if mad < _spread_floor(median):
        score = _relative_deviation_sigma(current, median)
    else:
        score = _MAD_TO_SIGMA * abs(current - median) / mad

    return _MethodResult(
        name="mad",
        is_anomaly=score > threshold,
        score=score,
        detail={"median": median, "mad": mad},
    )


class AnomalyDetector:
    """
    Ensemble statistical anomaly detector for time-series metrics.

    Runs z-score, EWMA-drift and MAD detection over the metric window and
    combines their votes. Defaults come from settings so sensitivity can be
    tuned without a code change.
    """

    _ALL_METHODS = ("zscore", "ewma", "mad")

    def __init__(
        self,
        threshold_sigma: float | None = None,
        methods: list[str] | tuple[str, ...] | None = None,
        min_votes: int | None = None,
        ewma_alpha: float | None = None,
    ):
        self.threshold_sigma = (
            threshold_sigma
            if threshold_sigma is not None
            else settings.anomaly_threshold_sigma
        )
        if methods is None:
            methods = [
                m.strip()
                for m in settings.anomaly_methods.split(",")
                if m.strip() in self._ALL_METHODS
            ]
        # Empty / all-invalid -> fall back to the full ensemble rather than
        # silently disabling detection.
        valid = [m for m in methods if m in self._ALL_METHODS]
        self.methods = tuple(valid) or self._ALL_METHODS
        self.min_votes = (
            min_votes if min_votes is not None else settings.anomaly_min_votes
        )
        self.ewma_alpha = (
            ewma_alpha if ewma_alpha is not None else settings.anomaly_ewma_alpha
        )
        self.strong_single_sigma = (
            self.threshold_sigma * STRONG_SINGLE_METHOD_SIGMA_MULTIPLIER
        )

    def detect(
        self,
        metric_result: MetricResult,
        window_size: int | None = None,
    ) -> list[AnomalyDetection]:
        """
        Detect an anomaly on the most recent point of a metric window.

        Returns a single-element list when the ensemble flags the point,
        otherwise an empty list (keeps the original contract).
        """
        if not metric_result.values:
            return []

        # Prometheus can return NaN/Inf for a sparse series (e.g.
        # histogram_quantile over an empty bucket) - non-finite values break
        # statistics.mean/stdev downstream (a float sum can't produce the
        # exact-Fraction result statistics.stdev expects, raising a raw
        # AttributeError instead of a clean StatisticsError).
        finite_points = [dp for dp in metric_result.values if math.isfinite(dp.value)]

        all_values = [dp.value for dp in finite_points]
        if len(all_values) < 3:
            logger.warning(f"Insufficient data points for {metric_result.metric_name}")
            return []

        baseline_values = all_values[:-1]
        current_point = finite_points[-1]
        current_value = current_point.value

        results: list[_MethodResult] = []
        for method in self.methods:
            if method == "zscore":
                results.append(
                    _zscore_method(baseline_values, current_value, self.threshold_sigma)
                )
            elif method == "ewma":
                results.append(
                    _ewma_method(all_values, self.threshold_sigma, self.ewma_alpha)
                )
            elif method == "mad":
                results.append(
                    _mad_method(baseline_values, current_value, self.threshold_sigma)
                )

        votes = [r for r in results if r.is_anomaly]
        max_score = max((r.score for r in results), default=0.0)
        strong_single = any(r.score >= self.strong_single_sigma for r in results)
        is_anomaly = len(votes) >= self.min_votes or strong_single

        mean = statistics.mean(baseline_values)

        if is_anomaly:
            # Confidence rises with agreement (how many methods voted) and with
            # how far past threshold the strongest method reached.
            agreement = len(votes) / max(len(results), 1)
            excess = max(0.0, max_score - self.threshold_sigma)
            confidence = min(0.99, 0.4 * agreement + 0.6 * min(1.0, 0.5 + excess / 10.0))
        else:
            confidence = max(0.0, max_score / self.threshold_sigma) * 0.4

        methods_triggered = [r.name for r in votes]

        anomaly = AnomalyDetection(
            metric_name=metric_result.metric_name,
            is_anomaly=is_anomaly,
            confidence=confidence,
            current_value=current_value,
            expected_value=mean,
            deviation_sigma=max_score,
            timestamp=datetime.fromtimestamp(current_point.timestamp),
            context={
                "labels": metric_result.labels,
                "baseline_mean": mean,
                "threshold_sigma": self.threshold_sigma,
                "sample_size": len(baseline_values),
                "votes": len(votes),
                "min_votes": self.min_votes,
                "strong_single": strong_single,
                "methods": {r.name: {"score": r.score, **r.detail} for r in results},
            },
            methods_triggered=methods_triggered,
        )

        if is_anomaly:
            logger.info(
                f"Anomaly detected in {metric_result.metric_name}: "
                f"value={current_value:.2f}, expected={mean:.2f}, "
                f"max_sigma={max_score:.2f}, votes={methods_triggered}, "
                f"confidence={confidence:.2f}"
            )
            return [anomaly]

        return []

    def detect_multiple(
        self,
        metric_results: list[MetricResult],
    ) -> list[AnomalyDetection]:
        """Detect anomalies across multiple metrics, sorted by confidence."""
        all_anomalies: list[AnomalyDetection] = []
        for metric_result in metric_results:
            all_anomalies.extend(self.detect(metric_result))
        all_anomalies.sort(key=lambda x: x.confidence, reverse=True)
        return all_anomalies


def categorize_anomaly(anomaly: AnomalyDetection) -> str:
    """
    Categorize anomaly based on metric name and direction.

    Simple heuristic — in production this would be pattern matching or an ML
    classifier.
    """
    metric_name = anomaly.metric_name.lower()
    increasing = anomaly.current_value > anomaly.expected_value

    if "error" in metric_name or "failure" in metric_name:
        return "error_spike" if increasing else "error_recovery"
    elif "latency" in metric_name or "duration" in metric_name:
        return "latency_spike" if increasing else "latency_improvement"
    elif "memory" in metric_name or "heap" in metric_name:
        return "memory_leak" if increasing else "memory_release"
    elif "cpu" in metric_name:
        return "cpu_spike" if increasing else "cpu_drop"
    elif "request" in metric_name or "throughput" in metric_name:
        return "traffic_spike" if increasing else "traffic_drop"
    else:
        return "metric_anomaly"
