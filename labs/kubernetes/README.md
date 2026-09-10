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

Prometheus is available at `http://localhost:9090`. Wait two minutes so the
detector has a baseline, then run AIRRA with these environment variables:

```powershell
$env:AIRRA_PROMETHEUS_URL = "http://host.docker.internal:9090"
$env:AIRRA_PROMETHEUS_METRIC_PROFILE = "kubernetes"
$env:AIRRA_KUBERNETES_NAMESPACE = "airra-lab"
$env:AIRRA_MONITORED_SERVICES = '["api-service","order-service","payment-service"]'
docker compose up --build
```

`host.docker.internal` is for the Docker Compose backend. If AIRRA itself runs
in Kubernetes, set `AIRRA_PROMETHEUS_URL=http://prometheus.airra-lab.svc:9090`.
Keep the normal Compose demo profile set to `demo`; it remains explicitly
synthetic.

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
