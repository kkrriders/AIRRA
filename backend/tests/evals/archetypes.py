"""
Incident archetypes for the AIRRA eval dataset.

Each archetype knows how to synthesise ONE realistic incident:
  - a metric window (baseline noise + an injected fault pattern) that is fed to
    the *real* AnomalyDetector, and a matching clean window with no fault (the
    negative sample used to measure the false-positive rate);
  - ground truth: root-cause category, correct remediation action, severity,
    and the blast-radius service set;
  - a natural-language description used as the retrieval query.

Everything is driven by a seeded `random.Random`, so `generate_dataset.py`
produces the same corpus on every run and in CI. No LLM calls, no I/O.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable

# Canonical categories understood by calculate_hypothesis_confidence + ActionSelector.
CATEGORIES = (
    "memory_leak",
    "cpu_spike",
    "traffic_spike",
    "latency_spike",
    "error_spike",
    "database_issue",
    "network_issue",
    "deployment_issue",
)

# Correct remediation per category (mirrors ActionSelector.action_rules; where the
# selector has no rule we still record what a human would do, so the benchmark can
# report the coverage gap instead of hiding it).
REMEDIATION = {
    "memory_leak": "restart_pod",
    "cpu_spike": "scale_up",
    "traffic_spike": "scale_up",
    "latency_spike": "restart_pod",
    "error_spike": "rollback_deployment",
    "database_issue": "restart_pod",
    "network_issue": "restart_pod",
    "deployment_issue": "rollback_deployment",
}

SERVICES = (
    "api-gateway",
    "order-service",
    "checkout-service",
    "payment-service",
    "inventory-service",
    "user-service",
    "notification-service",
    "search-service",
)

# Minimal dependency map so blast radius is not just "the service itself".
DOWNSTREAM = {
    "api-gateway": ["order-service", "search-service", "user-service"],
    "order-service": ["checkout-service", "notification-service"],
    "checkout-service": ["payment-service"],
    "payment-service": [],
    "inventory-service": ["order-service"],
    "user-service": [],
    "notification-service": [],
    "search-service": [],
    "postgres": ["order-service", "checkout-service", "user-service", "inventory-service"],
    "redis": ["api-gateway", "order-service", "search-service", "checkout-service"],
}

WINDOW = 30  # data points per metric window (~5 min at 10s scrape)


@dataclass
class IncidentSpec:
    archetype: str
    service: str
    metric_name: str
    values: list[float]
    clean_values: list[float]
    category: str
    severity: str
    blast_radius: list[str]
    description: str
    distractors: list[str] = field(default_factory=list)


def _noise(rng: random.Random, level: float, n: int = WINDOW) -> list[float]:
    return [rng.gauss(0.0, level) for _ in range(n)]


def _flat(base: float, rng: random.Random, noise: float, n: int = WINDOW) -> list[float]:
    return [base + e for e in _noise(rng, noise, n)]


def _ramp(base: float, end: float, rng: random.Random, noise: float) -> list[float]:
    step = (end - base) / (WINDOW - 1)
    return [base + step * i + rng.gauss(0.0, noise) for i in range(WINDOW)]


def _step(base: float, jump_to: float, at: int, rng: random.Random, noise: float) -> list[float]:
    out = []
    for i in range(WINDOW):
        level = base if i < at else jump_to
        out.append(level + rng.gauss(0.0, noise))
    return out


def _spike(base: float, peak: float, at: int, width: int, rng: random.Random, noise: float) -> list[float]:
    out = []
    for i in range(WINDOW):
        level = peak if at <= i < at + width else base
        out.append(level + rng.gauss(0.0, noise))
    return out


def _blast(service: str, extra: list[str] | None = None) -> list[str]:
    seen = [service, *DOWNSTREAM.get(service, [])]
    for s in extra or []:
        if s not in seen:
            seen.append(s)
    return seen


# --- archetype builders -------------------------------------------------------
# Each returns an IncidentSpec. Signature: (rng) -> IncidentSpec


def memory_leak_gradual(rng: random.Random) -> IncidentSpec:
    svc = rng.choice(SERVICES)
    base = rng.uniform(300e6, 500e6)
    end = base * rng.uniform(1.6, 2.4)  # 60-140% growth over the window
    return IncidentSpec(
        archetype="memory_leak_gradual",
        service=svc,
        metric_name="process_resident_memory_bytes",
        values=_ramp(base, end, rng, base * 0.01),
        clean_values=_flat(base, rng, base * 0.01),
        category="memory_leak",
        severity="high",
        blast_radius=_blast(svc),
        description=(
            f"{svc} resident memory climbing steadily from {base/1e6:.0f}MB toward "
            f"{end/1e6:.0f}MB with no plateau; GC pauses lengthening, no traffic change."
        ),
        distractors=["cpu_spike", "latency_spike"],
    )


def memory_leak_sudden(rng: random.Random) -> IncidentSpec:
    svc = rng.choice(SERVICES)
    base = rng.uniform(300e6, 450e6)
    to = base * rng.uniform(1.8, 2.6)
    return IncidentSpec(
        archetype="memory_leak_sudden",
        service=svc,
        metric_name="process_resident_memory_bytes",
        values=_step(base, to, rng.randint(8, 16), rng, base * 0.01),
        clean_values=_flat(base, rng, base * 0.01),
        category="memory_leak",
        severity="high",
        blast_radius=_blast(svc),
        description=(
            f"{svc} heap jumped from {base/1e6:.0f}MB to {to/1e6:.0f}MB after a cache "
            f"warm-up and stayed there; suspected unbounded in-memory collection."
        ),
        distractors=["deployment_issue", "traffic_spike"],
    )


def cpu_spike_busyloop(rng: random.Random) -> IncidentSpec:
    svc = rng.choice(SERVICES)
    base = rng.uniform(25.0, 45.0)
    peak = rng.uniform(92.0, 99.0)
    return IncidentSpec(
        archetype="cpu_spike_busyloop",
        service=svc,
        metric_name="cpu_usage_percent",
        values=_step(base, peak, rng.randint(10, 18), rng, 2.0),
        clean_values=_flat(base, rng, 2.0),
        category="cpu_spike",
        severity="medium",
        blast_radius=_blast(svc),
        description=(
            f"{svc} CPU pinned near {peak:.0f}% (baseline {base:.0f}%); thread pool "
            f"saturated, request handler appears stuck in a busy loop."
        ),
        distractors=["traffic_spike", "memory_leak"],
    )


def traffic_spike_flash(rng: random.Random) -> IncidentSpec:
    svc = rng.choice(("api-gateway", "search-service", "order-service"))
    base = rng.uniform(200.0, 600.0)
    peak = base * rng.uniform(5.0, 11.0)
    return IncidentSpec(
        archetype="traffic_spike_flash",
        service=svc,
        metric_name="http_requests_per_second",
        values=_spike(base, peak, rng.randint(8, 14), rng.randint(8, 14), rng, base * 0.05),
        clean_values=_flat(base, rng, base * 0.05),
        category="traffic_spike",
        severity="medium",
        blast_radius=_blast(svc),
        description=(
            f"{svc} request rate surged from {base:.0f} to {peak:.0f} req/s within a "
            f"minute; likely a marketing push or bot flood, latency still nominal."
        ),
        distractors=["cpu_spike", "latency_spike"],
    )


def latency_spike_p99(rng: random.Random) -> IncidentSpec:
    svc = rng.choice(SERVICES)
    base = rng.uniform(0.08, 0.25)
    end = base * rng.uniform(3.5, 8.0)
    return IncidentSpec(
        archetype="latency_spike_p99",
        service=svc,
        metric_name="http_request_duration_p99_seconds",
        values=_ramp(base, end, rng, base * 0.04),
        clean_values=_flat(base, rng, base * 0.04),
        category="latency_spike",
        severity="high",
        blast_radius=_blast(svc),
        description=(
            f"{svc} p99 latency rose from {base*1000:.0f}ms to {end*1000:.0f}ms over "
            f"five minutes; error rate flat, downstream calls slow."
        ),
        distractors=["database_issue", "network_issue"],
    )


def error_spike_bad_deploy(rng: random.Random) -> IncidentSpec:
    svc = rng.choice(SERVICES)
    base = rng.uniform(0.1, 1.0)
    to = rng.uniform(25.0, 90.0)
    return IncidentSpec(
        archetype="error_spike_bad_deploy",
        service=svc,
        metric_name="http_5xx_rate_percent",
        values=_step(base, to, rng.randint(6, 12), rng, 1.0),
        clean_values=_flat(base, rng, 0.5),
        category="error_spike",
        severity="critical",
        blast_radius=_blast(svc),
        description=(
            f"{svc} 5xx rate jumped from {base:.1f}% to {to:.0f}% immediately after a "
            f"rollout; stack traces point at a null deref in the new handler."
        ),
        distractors=["deployment_issue", "database_issue"],
    )


def database_issue_slow_query(rng: random.Random) -> IncidentSpec:
    svc = rng.choice(("order-service", "checkout-service", "user-service", "inventory-service"))
    base = rng.uniform(0.01, 0.05)
    end = base * rng.uniform(6.0, 15.0)
    return IncidentSpec(
        archetype="database_issue_slow_query",
        service=svc,
        metric_name="db_query_duration_p95_seconds",
        values=_ramp(base, end, rng, base * 0.05),
        clean_values=_flat(base, rng, base * 0.05),
        category="database_issue",
        severity="high",
        blast_radius=_blast(svc, extra=DOWNSTREAM["postgres"]),
        description=(
            f"{svc} DB query p95 climbed from {base*1000:.0f}ms to {end*1000:.0f}ms; "
            f"connection pool near exhaustion, a missing index suspected after a data grow."
        ),
        distractors=["latency_spike", "network_issue"],
    )


def network_issue_packet_loss(rng: random.Random) -> IncidentSpec:
    svc = rng.choice(SERVICES)
    base = rng.uniform(0.0, 0.2)
    peak = rng.uniform(4.0, 12.0)
    # intermittent: alternating good/bad points
    vals = []
    for i in range(WINDOW):
        bad = i > 8 and (i % 2 == 0)
        vals.append((peak if bad else base) + rng.gauss(0.0, 0.15))
    return IncidentSpec(
        archetype="network_issue_packet_loss",
        service=svc,
        metric_name="tcp_retransmit_rate_percent",
        values=vals,
        clean_values=_flat(base, rng, 0.15),
        category="network_issue",
        severity="medium",
        blast_radius=_blast(svc),
        description=(
            f"{svc} seeing intermittent TCP retransmits up to {peak:.0f}%; sporadic "
            f"timeouts to downstream services, one AZ link looks flaky."
        ),
        distractors=["latency_spike", "database_issue"],
    )


def deployment_issue_crashloop(rng: random.Random) -> IncidentSpec:
    svc = rng.choice(SERVICES)
    base = 0.0
    end = rng.uniform(6.0, 20.0)
    return IncidentSpec(
        archetype="deployment_issue_crashloop",
        service=svc,
        metric_name="pod_restart_count",
        values=_ramp(base, end, rng, 0.3),
        clean_values=_flat(base, rng, 0.2),
        category="deployment_issue",
        severity="critical",
        blast_radius=_blast(svc),
        description=(
            f"{svc} pods in CrashLoopBackOff, restart count up to {end:.0f} in five "
            f"minutes since the last deploy; readiness probe failing on a bad config key."
        ),
        distractors=["error_spike", "memory_leak"],
    )


def redis_outage_cascade(rng: random.Random) -> IncidentSpec:
    svc = "api-gateway"
    base = rng.uniform(88.0, 97.0)  # cache hit rate %
    return IncidentSpec(
        archetype="redis_outage_cascade",
        service=svc,
        metric_name="cache_hit_rate_percent",
        values=_step(base, rng.uniform(0.0, 6.0), rng.randint(7, 13), rng, 1.5),
        clean_values=_flat(base, rng, 1.5),
        category="latency_spike",  # observed symptom at the gateway
        severity="critical",
        blast_radius=_blast(svc, extra=DOWNSTREAM["redis"]),
        description=(
            f"{svc} cache hit rate collapsed from {base:.0f}% to near zero; multiple "
            f"services slow simultaneously, all sharing the same Redis cluster."
        ),
        distractors=["database_issue", "network_issue", "traffic_spike"],
    )


ARCHETYPES: tuple[Callable[[random.Random], IncidentSpec], ...] = (
    memory_leak_gradual,
    memory_leak_sudden,
    cpu_spike_busyloop,
    traffic_spike_flash,
    latency_spike_p99,
    error_spike_bad_deploy,
    database_issue_slow_query,
    network_issue_packet_loss,
    deployment_issue_crashloop,
    redis_outage_cascade,
)
