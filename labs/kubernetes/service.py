"""Small, dependency-backed workload used only by the local Kubernetes lab.

It is intentionally not part of AIRRA.  It emits conventional Prometheus
metrics while making real HTTP, Redis and PostgreSQL calls, so faults originate
in a running cluster rather than AIRRA's synthetic metric generator.
"""
import os
import sys
import time

import psycopg
import redis
import requests
from flask import Flask, Response, jsonify
from prometheus_client import Counter, Histogram, generate_latest

app = Flask(__name__)
SERVICE = os.getenv("SERVICE_NAME", "unknown-service")
PORT = int(os.getenv("PORT", "8080"))
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://lab:lab@postgres:5432/lab")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

REQUESTS = Counter(
    "http_requests_total", "HTTP requests", ["service", "endpoint", "status"]
)
LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request duration", ["service", "endpoint"]
)
DEPENDENCY_FAILURES = Counter(
    "service_dependency_failures_total", "Dependency failures", ["service", "dependency"]
)
DATABASE_LATENCY = Histogram(
    "database_query_duration_seconds", "PostgreSQL query duration", ["service"]
)


def _record(endpoint: str, status: int, started: float) -> None:
    REQUESTS.labels(SERVICE, endpoint, str(status)).inc()
    LATENCY.labels(SERVICE, endpoint).observe(time.monotonic() - started)


def _postgres_check() -> None:
    delay_ms = int(os.getenv("DATABASE_DELAY_MS", "0"))
    started = time.monotonic()
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                # pg_sleep is injected by a deployment environment change in
                # the lab, making latency observable through the API call path.
                cur.execute("SELECT pg_sleep(%s)", (delay_ms / 1000,))
    except Exception:
        DEPENDENCY_FAILURES.labels(SERVICE, "postgres").inc()
        raise
    finally:
        DATABASE_LATENCY.labels(SERVICE).observe(time.monotonic() - started)


def _redis_check() -> None:
    try:
        redis.from_url(REDIS_URL, socket_connect_timeout=1, socket_timeout=1).ping()
    except Exception:
        DEPENDENCY_FAILURES.labels(SERVICE, "redis").inc()
        raise


def _call(service: str, path: str = "/work") -> None:
    try:
        response = requests.get(f"http://{service}:8080{path}", timeout=3)
        response.raise_for_status()
    except Exception:
        DEPENDENCY_FAILURES.labels(SERVICE, service).inc()
        raise


@app.get("/healthz")
def healthz():
    return jsonify(service=SERVICE, status="ok")


@app.get("/work")
def work():
    started = time.monotonic()
    try:
        _postgres_check()
        _redis_check()
    except Exception as exc:
        _record("/work", 503, started)
        return jsonify(service=SERVICE, error=type(exc).__name__), 503
    _record("/work", 200, started)
    return jsonify(service=SERVICE, status="ok")


@app.get("/checkout")
def checkout():
    started = time.monotonic()
    try:
        _call("order-service")
        _call("payment-service")
    except Exception as exc:
        _record("/checkout", 502, started)
        return jsonify(service=SERVICE, error=type(exc).__name__), 502
    _record("/checkout", 200, started)
    return jsonify(service=SERVICE, status="checkout complete")


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), mimetype="text/plain; version=0.0.4")


if __name__ == "__main__":
    # A bad config causes an actual Kubernetes CrashLoopBackOff; no synthetic
    # metric is generated for this scenario.
    if os.getenv("CRASH_LOOP", "false").lower() == "true":
        sys.exit("CRASH_LOOP=true: simulated invalid production configuration")
    app.run(host="0.0.0.0", port=PORT)
