# AIRRA Kubernetes Incident Lab

This is a local, disposable Kubernetes environment for demonstrating that AIRRA
can observe failures which originate in running infrastructure. It is not a
claim that AIRRA has been connected to a production cluster.

The request path is `load-generator -> api-service -> order-service +
payment-service -> PostgreSQL + Redis`. Each application emits Prometheus
metrics; Prometheus also collects `kube_pod_container_status_restarts_total`
from kube-state-metrics.

## Start it

Prerequisites: Docker Desktop, `kind`, and `kubectl`.

```powershell
kind create cluster --name airra-lab --config labs/kubernetes/kind-config.yaml
docker build -t airra-lab-service:local labs/kubernetes
kind load docker-image airra-lab-service:local --name airra-lab
kubectl apply -f labs/kubernetes/manifests/workloads.yaml
kubectl apply -f labs/kubernetes/manifests/observability.yaml
kubectl -n airra-lab rollout status deployment/api-service
```

Prometheus is available at `http://localhost:9091` (not 9090 — AIRRA's own
bundled Prometheus in `docker-compose.yml` already owns host port 9090, and
`backend` has a hard `depends_on: prometheus: condition: service_healthy`, so
the two can't share a port). Wait two minutes so the detector has a baseline,
then run AIRRA with these environment variables:

```powershell
$env:AIRRA_PROMETHEUS_URL = "http://host.docker.internal:9091"
$env:AIRRA_PROMETHEUS_METRIC_PROFILE = "kubernetes"
$env:AIRRA_KUBERNETES_NAMESPACE = "airra-lab"
$env:AIRRA_MONITORED_SERVICES = '["api-service","order-service","payment-service"]'
docker compose up --build
```

`host.docker.internal` is for the Docker Compose backend. If AIRRA itself runs
in Kubernetes, set `AIRRA_PROMETHEUS_URL=http://prometheus.airra-lab.svc:9090`
(in-cluster, so the NodePort/host-port clash above doesn't apply). Keep the
normal Compose demo profile set to `demo`; it remains explicitly synthetic.

## Run and verify a fault

```powershell
.\labs\kubernetes\chaos.ps1 crashloop
kubectl -n airra-lab get pods -w
```

The payment pod should show `CrashLoopBackOff`; after scrape and monitor cycles,
AIRRA should create an incident whose evidence includes `pod_restart_count`.
Verify the metric independently in Prometheus:

```promql
sum(kube_pod_container_status_restarts_total{namespace="airra-lab",pod=~"payment-service-.*"})
```

Other reproducible failure modes:

| Command | Origin and expected evidence |
| --- | --- |
| `chaos.ps1 database-latency` | Real `pg_sleep` in PostgreSQL makes API request latency rise. |
| `chaos.ps1 redis-outage` | Redis is scaled to zero; all workload services return dependency failures/503s. |
| `chaos.ps1 recover` | Removes all injected configuration and restores Redis. |

Do not run the fault script against any cluster except the disposable local
`airra-lab` cluster. Clean up with `kind delete cluster --name airra-lab`.

## Verified live (2026-09-13)

Ran end-to-end against a real `kind` cluster (not just reviewed as code):

- **`crashloop`**: injected on `payment-service`. Real `CrashLoopBackOff`
  observed via `kubectl get pods`. `kube_pod_container_status_restarts_total`
  climbed (confirmed independently via the Prometheus HTTP API, not just
  AIRRA's own read of it). AIRRA's ensemble detector fired all three methods
  (zscore/ewma/mad) in agreement, confidence 0.99 — the strongest signal type
  in the whole test, because a restart count going 0→1 against a near-zero
  baseline is unambiguous in a way rate-based metrics rarely are. Incident
  auto-created → auto-analyzed → 4 ranked LLM hypotheses (top: `traffic_spike`,
  0.817 confidence) → 1 `scale_up` action generated → approved via the API.
  **Caveat**: the top hypothesis was plausible-sounding but not the actual
  root cause (`CRASH_LOOP=true` forcing `sys.exit`) — the analyzer only had
  two metrics to reason from (no pod events, no exit code, no logs), so it
  reached for the closest metric-shaped story. Worth stating in interviews
  as a known limitation of metrics-only RCA, not overclaiming accuracy.
- **`redis-outage`**: `error_rate` hit 1.00 (100%) and `latency_p95` spiked
  ~70-80σ on all three services within one detection cycle, correctly
  cascading from a single dependency failure through `/checkout` →
  `order-service`/`payment-service` → `/work` → Redis. 3 incidents created,
  one per affected service.
- Cold-start caveat reproduced live: the load-generator's ramp from 0 → ~4
  req/s reads as sustained EWMA drift for the first several detection cycles
  (confidence 0.73, `request_rate`) — exactly the "wait two minutes" warning
  above, not a new bug. Each of the 3 services picked up its own 10-minute
  Redis dedup key from this, which then legitimately no-ops later chaos
  scenarios until the window clears — clear it early with
  `docker exec airra-redis redis-cli DEL airra:anomaly_dedup:<service>` if
  you don't want to wait.

**Two real bugs found and fixed by actually running this (not by review):**

1. **Port conflict**: `docker-compose.yml` hardcoded
   `AIRRA_PROMETHEUS_URL: http://prometheus:9090` — not overridable via
   `.env` despite this README instructing you to override it. AIRRA's own
   bundled Prometheus has a hard `depends_on: service_healthy` gate on
   `backend`, so it can't just be skipped, and it already owns host port
   9090 — colliding with this lab's original NodePort mapping. Fixed by
   templating the compose var (`${AIRRA_PROMETHEUS_URL:-http://prometheus:9090}`,
   matching every other kind-lab override already in that file) and moving
   this lab's Prometheus to host port **9091** (`kind-config.yaml`).
2. **Stale event-loop bug, different singleton**: `embed_incident_task` and
   `backfill_missing_embeddings_task` (`app/worker/tasks/embedding.py`) called
   bare `asyncio.run()` instead of the project's `run_async()` helper — the
   only thing that disposes the shared SQLAlchemy engine pool between
   `asyncio.run()` calls on the same Celery worker fork. Left unfixed, the
   *next* task on that fork (even a `run_async`-wrapped one) inherited
   connections bound to the dead loop and crashed with `RuntimeError: Event
   loop is closed` / `... attached to a different loop` — same failure class
   already fixed once for `AnomalyMonitor` (see
   `labs/integration/README.md`), just a different singleton this time.
   Fixed by switching both call sites to `run_async()`; added
   `backend/tests/unit/test_async_run_usage.py`, which statically fails if
   any file under `app/worker/tasks/` calls bare `asyncio.run()` outside the
   one documented exception. Confirmed zero recurrences in 10+ minutes of
   live traffic after the fix (previously: 6 occurrences in 5 minutes).
