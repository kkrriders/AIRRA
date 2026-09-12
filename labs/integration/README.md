# AIRRA ↔ AI Engineering Platform — integration harness (Phase A3)

Drives a real fault into the *Multi Agent Intelligence Platform* stack so AIRRA
detects it end-to-end: detect → RAG → reason → approve → (execute/verify).

Design: `../../docs/superpowers/specs/2026-09-10-airra-ai-platform-integration-design.md`

## Prereqs

Both stacks up on the shared `airra-mesh` network (see the design doc §4):

```powershell
docker network create airra-mesh   # once
docker compose -f ../../docker-compose.yml up -d --build
docker compose -f "$HOME/Multi Agent Intelligence Platform/docker-compose.yml" up -d --build
```

AIRRA `.env` needs the `kubernetes` metric profile and a reachable LLM:

```
AIRRA_PROMETHEUS_METRIC_PROFILE=kubernetes
AIRRA_KUBERNETES_NAMESPACE=ai-platform
AIRRA_MONITORED_SERVICES=["api","orchestrator","researcher","tool_runner","executor","verifier"]
AIRRA_LLM_MODEL=openai/gpt-oss-20b        # a model your AIRRA_OPENAI_API_KEY (Groq) can actually list
```

Seed AIRRA's RAG store once so hypotheses have prior art:

```powershell
docker exec airra-backend python scripts/seed_ai_platform_patterns.py
docker exec airra-backend python scripts/seed_ai_platform_patterns.py --verify
```

## Scripts

| Script | What it does |
|---|---|
| `traffic.ps1` | Light steady `GET /health` load so `api` has a non-degenerate metric baseline. `-Forever` or `-DurationSec`. Does **not** execute the graph. |
| `run-traffic.ps1` | Mints a real Supabase session JWT, creates a project+conversation, and loops real `POST /runs` calls so the 5 LangGraph node metrics (`orchestrator`/`researcher`/`tool_runner`/`executor`/`verifier`) actually populate. Required for `node-crash` to show anything. `-Forever` or `-DurationSec`. |
| `chaos.ps1`   | Fault injection. `-Scenario api-traffic-surge\|node-crash\|qdrant-down`, `-Action inject\|clear\|status`. Pass `-AirraApiKey` (or set `$env:AIRRA_API_KEY`) for the incident list in `-Action status`. |
| `benchmark-run.ps1` | End-to-end resume-metrics run: sends 5 real, uniquely-nonced tasks, injects a `node-crash` on `orchestrator` (the unconditional graph entrypoint -- see note below) after task 2, holds it live through task 5 plus a 30s buffer so a full monitor cycle sees it, then drives AIRRA through detect -> analyze -> approve -> execute and writes both sides' metrics to `results/<timestamp>-benchmark.{json,md}`. `-FailNode` to target a different node. |

**Why `orchestrator` and not `researcher`/`executor`/`verifier` for the benchmark:** those three are only visited when the orchestrator's own LLM call decides a query needs them. Well-formed, directly-answerable Q&A prompts (the benchmark's realistic task list) can silently route around a crashed `researcher` and succeed anyway -- confirmed live 2026-09-12, where the same crashed node let 2 of 3 "during-failure" tasks through untouched. Generic filler text (`run-traffic.ps1`'s default) reliably triggers research and doesn't have this problem, but isn't representative of real tasks. `orchestrator` is the first node on every run regardless of routing, so it's the only deterministic target for a benchmark that also wants realistic prompts.

**Remediation availability varies by hypothesis category:** AIRRA's `action_selector` maps to Kubernetes executors (restart pod, scale, drain node) -- the AI platform runs in plain Docker Compose in this phase (no k8s executor yet, that's Phase C), so whether an incident's top-ranked hypothesis category has a mapped action is not guaranteed. Observed both outcomes live on `orchestrator` crashes with near-identical anomaly signals and top confidence (0.693): one run produced zero actions (analysis-only), the next produced a full approve -> execute -> `succeeded` cycle. `benchmark-run.ps1` handles both gracefully -- it only attempts approve/execute when `incident.actions` is non-empty.

### Scenarios

- **`api-traffic-surge`** (reliable): floods `:8010/health`, spikes `api`
  `request_rate` ~300× baseline. AIRRA's 60 s monitor opens a `critical`
  incident on `api`. This is the demo path.
- **`node-crash`**: sets `CHAOS_FAIL_NODE=<node>` on the platform backend so one
  LangGraph node 500s on every run. Needs run traffic to show (see limitation 2).
- **`qdrant-down`**: `docker stop` the platform's qdrant container → `researcher`
  `service_dependency_failures_total{dependency="qdrant"}`.
- **`llm-failure`**: builds+starts `mock-llm` (compose profile `chaos`, not
  started by a plain `up`), points the platform's `GROQ_BASE_URL` at it, and
  flips it to 500s (`-Kind 5xx`, default) or 429s (`-Kind rate_limit`) →
  `llm_gateway_errors_total{kind=...}` across every node that calls the LLM.
  Needs run traffic to show (see limitation 2).

## End-to-end demo (api-traffic-surge)

```powershell
# 1. quiet the baseline first — repeated surges inflate the EWMA expectation and
#    drop detection confidence below the 0.75 gate. Wait until this is < 0.2:
./chaos.ps1 -Scenario api-traffic-surge -Action status

# 2. (optional) clear the 10-min per-service dedup if you just ran one:
docker exec airra-redis redis-cli DEL airra:anomaly_dedup:api

# 3. surge
./chaos.ps1 -Scenario api-traffic-surge -DurationSec 200

# 4. within ~1 min AIRRA opens an incident. Trigger analysis, then approve:
$k = (Select-String ../../.env '^AIRRA_API_KEY=(.+)$').Matches.Groups[1].Value
$id = (curl -s -H "X-API-Key: $k" "http://localhost:8000/api/v1/incidents?page=1" | ConvertFrom-Json).data[0].id
curl -s -X POST -H "X-API-Key: $k" "http://localhost:8000/api/v1/incidents/$id/analyze"
# ...poll until status = pending_approval, 4 hypotheses, one recommended action...
$aid = (curl -s -H "X-API-Key: $k" "http://localhost:8000/api/v1/incidents/$id" | ConvertFrom-Json).actions[0].id
curl -s -X POST -H "X-API-Key: $k" -H "Content-Type: application/json" -d '{"approved_by":"you"}' "http://localhost:8000/api/v1/approvals/$aid/approve"
```

## Known limitations

1. **The 5 graph nodes only emit metrics when a real run executes.** Runs need a
   Supabase ES256 JWT (platform `auth.py`, no dev bypass) plus, for every node
   past the entrypoint, a working Groq key. `run-traffic.ps1` mints the JWT
   (password-grant against the real hosted Supabase project, fixed test user,
   auto-signup on first use) and drives real runs.
2. **`node-crash` and `llm-failure` need `run-traffic.ps1` running concurrently**
   — `chaos.ps1` only flips an env var / the mock gateway's mode; something has
   to make the graph reach the affected node.
3. **`redis-outage` / `postgres-latency` / `cascade` from the design doc §3.5 are
   not runnable in Phase A** — the platform has no redis/postgres containers
   (Supabase-hosted). They land in Phase C (kind).
4. **Baseline pollution**: back-to-back surges raise the EWMA baseline; give it
   ~6 quiet minutes between runs or detection confidence dips under the 0.75 gate.
5. **`APPROVED → EXECUTING → RESOLVED`** is an AIRRA Beat timer (~30 min) / real
   k8s executor, not driven by this harness.

## Cascade + correlation (Phase A4)

The design doc's redis-outage cascade doesn't apply (no local redis/postgres on
the platform side). The real mechanism, verified against
`correlation_service.py`: `get_upstream_dependencies()` returns only *direct*
`depends_on` entries (not transitive), so correlation only fires when 3+
services that **directly** list a common dependency each get their own
incident within `CORRELATION_WINDOW_SECONDS` (300s). In
`backend/config/service_dependencies.yaml`, `researcher`/`tool_runner`/
`executor`/`verifier` all directly depend on `groq` — `orchestrator` and `api`
don't (their `depends_on` lists are service names, not shared resources), so
they can never join a group under this logic even when they also fail.

`llm-failure` cannot itself produce this: the platform's graph is fail-fast —
the first node whose Groq call errors aborts the whole run, so orchestrator's
deterministic first hop (`researcher`) is the only node that ever accumulates
errors under a sustained outage; `tool_runner`/`executor`/`verifier` are never
reached. `tool_runner` additionally never receives synthetic traffic at all —
routing there is an LLM decision that a generic input string never triggers.

**What works**: run `node-crash` sequentially against 3 of
`{researcher, executor, verifier}` (not `tool_runner`, per above), each with
`run-traffic.ps1` for real traffic, all inside 5 minutes:

```powershell
./chaos.ps1 -Scenario node-crash -Node verifier; ./run-traffic.ps1 -DurationSec 30 -DelaySec 6
./chaos.ps1 -Scenario node-crash -Node executor;  ./run-traffic.ps1 -DurationSec 30 -DelaySec 6
./chaos.ps1 -Scenario node-crash -Node researcher; ./run-traffic.ps1 -DurationSec 30 -DelaySec 6
./chaos.ps1 -Scenario node-crash -Action clear
```

Verified live 2026-09-11: `researcher` and `executor` each got their own
incident and correctly share `groq` as upstream. The third (`verifier`)
didn't fire — originally chalked up to "weak signal, needs more soak time."
That diagnosis was wrong. Root cause (found 2026-09-12): `AnomalyMonitor`'s
query semaphore (`MAX_CONCURRENT_QUERIES = 5`) is a loop-bound
`asyncio.Semaphore` on a module-level singleton that survives across Celery
tasks, while each task runs in a fresh event loop. A semaphore only binds to
a loop the first time a caller has to *wait* — with the original 5-service
demo default nobody ever waits, so this was invisible for the project's
whole life. Configuring 6 services (this integration) means one service per
cycle always waits; it binds the semaphore to cycle 1's loop, then every
later cycle raises `RuntimeError: ... bound to a different event loop` —
inside `async with`, before `_check_service`'s own try/except, swallowed
silently by `asyncio.gather(..., return_exceptions=True)`. Net effect: the
last service in `AIRRA_MONITORED_SERVICES` (`verifier`) got checked exactly
once, ever, with zero error trace. Fixed in
`backend/app/worker/async_run.py` by resetting the `AnomalyMonitor`
singleton per task, same pattern already used there for the Prometheus/Redis
clients. `verifier` now gets checked and incidents on every cycle.

With the bug fixed, `researcher`+`executor`+`verifier` still haven't landed a
clean 3-way `correlation_group_id` live — now blocked by test-repetition
artifacts, not the bug: back-to-back runs leave 10-min dedup keys and 5-min
detection-window residue from the *previous* run, so a same-day retry often
detects on stale carryover data instead of the fresh crash, or gets deduped
entirely. Give it a real ~10 min idle gap (past both the dedup TTL and the
detection window) before the next attempt, run all 3 node-crashes+traffic
back to back inside 5 minutes, then check:
`curl -s -H "X-API-Key: $k" http://localhost:8000/api/v1/incidents | ConvertFrom-Json`
for 3 incidents sharing one `correlation_group_id`.

## Deferred (not built)

- Live confirmation of a full 3-way `correlation_group_id` (mechanism verified,
  see above — blocked on soak time, not a bug).
- The full agent/RAG/cost/reliability metrics framework requested on top of Phase
  A3/A4 (task success rate, RCA accuracy, MTTD/MTTR, retrieval Recall@K, token
  cost per task, etc.) — large enough to need its own design pass, not scoped here.
