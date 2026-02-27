"""
Demo Metrics Endpoint.

Exposes synthetic Prometheus Gauge metrics for the 5 demo services so the
anomaly monitor has real time-series data to analyse — without needing
actual services running.

How spikes work:
  - Each service has a 600-second (10-min) cycle.
  - At a service-specific offset within that cycle, one metric spikes for 45 s.
  - The spike magnitude is 12–18× normal → z-score of 50–340 → guaranteed detection.
  - Prometheus scrapes every 15s, so the 45s spike window is captured 3 times.
  - The AnomalyDetector uses all-but-the-last data point as the baseline, so it
    only needs ONE spike sample in the final position to fire an alert.

Prometheus scrape job (prometheus.yml): 'airra-demo-services'
  → backend:8000/demo/metrics
"""
import math
import random
import time

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

router = APIRouter()

# ─── Service definitions ─────────────────────────────────────────────────────

_SERVICES: dict[str, dict] = {
    "payment-service": {
        "request_rate":  45.0,                # req/s
        "error_rate":     0.5,                # req/s
        "latency_p95":    0.12,               # seconds
        "cpu_usage":      0.35,               # 0–1 ratio
        "memory_bytes":   512 * 1024 * 1024,  # bytes
        "spike_offset":   0,                  # fires at t % 600 in [0, 45)
        "spike_metric":   "error_rate",
        "spike_multiplier": 18.0,             # 18× baseline
    },
    "order-service": {
        "request_rate":  30.0,
        "error_rate":     0.3,
        "latency_p95":    0.08,
        "cpu_usage":      0.25,
        "memory_bytes":   384 * 1024 * 1024,
        "spike_offset":   120,
        "spike_metric":   "latency_p95",
        "spike_multiplier": 15.0,
    },
    "user-service": {
        "request_rate":  60.0,
        "error_rate":     0.2,
        "latency_p95":    0.05,
        "cpu_usage":      0.20,
        "memory_bytes":   256 * 1024 * 1024,
        "spike_offset":   240,
        "spike_metric":   "cpu_usage",
        "spike_multiplier": 4.0,   # 4× → 0.80 CPU (clamped to 1.0 max)
    },
    "inventory-service": {
        "request_rate":  15.0,
        "error_rate":     0.1,
        "latency_p95":    0.15,
        "cpu_usage":      0.15,
        "memory_bytes":   192 * 1024 * 1024,
        "spike_offset":   360,
        "spike_metric":   "memory_bytes",
        "spike_multiplier": 3.5,
    },
    "notification-service": {
        "request_rate":   8.0,
        "error_rate":     0.05,
        "latency_p95":    0.20,
        "cpu_usage":      0.10,
        "memory_bytes":   128 * 1024 * 1024,
        "spike_offset":   480,
        "spike_metric":   "request_rate",
        "spike_multiplier": 12.0,
    },
}

_SPIKE_PERIOD: int = 600   # seconds  (one cycle = 10 minutes)
_SPIKE_DURATION: int = 45  # seconds  (spike window per cycle)

# ─── Value generation ─────────────────────────────────────────────────────────


def _current_value(service: str, metric: str, t: float) -> float:
    """
    Compute the metric value for a service at unix time t.

    Normal regime: baseline ± 5 % Gaussian noise ± 3 % sine oscillation.
    Spike regime:  baseline × spike_multiplier for 45 s within each 10-min cycle.
    """
    cfg = _SERVICES[service]
    base = float(cfg[metric])

    # Sine wave with period ~5 min creates realistic drift between scrapes.
    # The per-service/metric hash shifts the phase so services don't peak together.
    phase_shift = abs(hash(f"{service}{metric}")) % 10
    oscillation = math.sin(t / 300.0 + phase_shift) * 0.03 * base

    # Gaussian noise (~5 % std-dev) ensures stdev > 0 so z-score works correctly.
    noise = random.gauss(0.0, 0.05 * base)

    value = base + oscillation + noise

    # Inject the spike if we're inside this service's spike window.
    phase = t % _SPIKE_PERIOD
    if cfg["spike_offset"] <= phase < cfg["spike_offset"] + _SPIKE_DURATION:
        if metric == cfg["spike_metric"]:
            value = base * cfg["spike_multiplier"]

    # Domain clamping
    if metric == "cpu_usage":
        value = min(1.0, max(0.0, value))
    else:
        value = max(0.0, value)

    return value


# ─── Prometheus text format ───────────────────────────────────────────────────

_METRIC_DEFS = [
    ("airra_demo_request_rate",  "Current request rate (requests per second)", "request_rate"),
    ("airra_demo_error_rate",    "Current error rate (errors per second)",      "error_rate"),
    ("airra_demo_latency_p95",   "P95 request latency (seconds)",               "latency_p95"),
    ("airra_demo_cpu_usage",     "CPU usage ratio (0 to 1)",                    "cpu_usage"),
    ("airra_demo_memory_bytes",  "Resident memory usage (bytes)",               "memory_bytes"),
]


def _build_metrics_text() -> str:
    """Generate a full Prometheus text-format exposition for all demo services."""
    t = time.time()
    lines: list[str] = []

    for prom_name, help_text, metric_key in _METRIC_DEFS:
        lines.append(f"# HELP {prom_name} {help_text}")
        lines.append(f"# TYPE {prom_name} gauge")
        for service in _SERVICES:
            v = _current_value(service, metric_key, t)
            lines.append(f'{prom_name}{{service="{service}"}} {v:.6f}')

    return "\n".join(lines) + "\n"


# ─── Route ───────────────────────────────────────────────────────────────────


@router.get("/demo/metrics", include_in_schema=False)
async def demo_metrics_endpoint():
    """
    Prometheus scrape target for demo services.

    Scraped by the 'airra-demo-services' job in prometheus.yml every 15 s.
    No API-key auth — Prometheus does not send auth headers by default.
    """
    return PlainTextResponse(
        content=_build_metrics_text(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
