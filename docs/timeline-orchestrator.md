# Timeline Orchestrator - Automated Incident Streams

The Timeline Orchestrator automatically creates multiple incidents at scheduled times, simulating realistic incident streams for demos and testing. It supports both **pre-defined scenarios** and **LLM-generated variations**.

---

## 🎯 Why Hybrid Architecture?

| Approach | When to Use | Pros | Cons |
|----------|------------|------|------|
| **Python Scripts** | Demos, testing, reliability | ✅ Deterministic<br>✅ Fast<br>✅ Type-safe | ❌ Fixed scenarios<br>❌ Requires code changes |
| **JSON + LLM** | Variety, realism, exploration | ✅ Infinite variations<br>✅ No coding needed<br>✅ Realistic unknowns | ❌ Non-deterministic<br>❌ Slower (LLM calls)<br>❌ API costs |
| **Hybrid (Our Choice)** | Best of both worlds | ✅ Reliable when needed<br>✅ Creative when wanted<br>✅ Flexible | ⚠️ More complex |

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│            Timeline Configuration (JSON)              │
│  • Schedule: delays, order                           │
│  • Mix of predefined + LLM-generated                 │
└────────────────┬─────────────────────────────────────┘
                 │
         ┌───────┴────────┐
         │                │
         ▼                ▼
┌────────────────┐  ┌─────────────────────┐
│   Predefined   │  │  LLM Generator      │
│   Scenarios    │  │  (GeneratedScenario)│
│   (Python)     │  │  (Dynamic JSON)     │
└────────┬───────┘  └──────────┬──────────┘
         │                     │
         └──────────┬──────────┘
                    ▼
            Incident Simulator
                    │
                    ▼
          Quick Incident API
                    │
                    ▼
         LLM Analysis + Actions
```

---

## Quick Start

### 1. List Available Timelines

```bash
python scripts/demo/run_timeline.py --list
```

**Output:**
```
╭─────────────────────────────────────────────────────╮
│         Available Timeline Configurations            │
│        Pre-packaged incident timelines for demos     │
╰─────────────────────────────────────────────────────╯

                 📅 Timelines
╭──────────────┬────────────────┬──────────┬───────────╮
│ ID           │ Name           │ Duration │ Incidents │
├──────────────┼────────────────┼──────────┼───────────┤
│ busy_day     │ Busy Day       │ 30 min   │ 4         │
│ incident_sto │ Incident Storm │ 20 min   │ 5         │
│ rm           │                │          │           │
│ gradual_esca │ Gradual        │ 25 min   │ 5         │
│ lation       │ Escalation     │          │           │
╰──────────────┴────────────────┴──────────┴───────────╯
```

### 2. Run a Timeline

```bash
python scripts/demo/run_timeline.py --timeline busy_day
```

**What happens:**
1. Shows schedule of all incidents
2. Waits for you to press Enter
3. Triggers incidents at scheduled times
4. Shows real-time progress
5. Displays summary with all created incidents

---

## Pre-Configured Timelines

### 1. Busy Day (`busy_day.json`)

**Duration:** 30 minutes
**Incidents:** 4 predefined scenarios
**Use case:** General demo of multiple incidents

**Schedule:**
- T+0:00 - Memory leak (overnight batch job issue)
- T+5:00 - CPU spike (morning login surge)
- T+10:00 - Database latency (query accumulation)
- T+15:00 - External dependency timeout

### 2. Incident Storm (`incident_storm.json`)

**Duration:** 20 minutes
**Incidents:** 5 (mix of predefined and LLM-generated)
**Use case:** Chaotic scenario with variety

**Schedule:**
- T+0:00 - Pod crash loop (predefined)
- T+1:00 - Network connectivity issue (LLM-generated)
- T+3:00 - CPU spike (predefined)
- T+4:00 - Disk space exhaustion (LLM-generated)
- T+6:00 - Security/auth failures (LLM-generated)

### 3. Gradual Escalation (`gradual_escalation.json`)

**Duration:** 25 minutes
**Incidents:** 5 (escalating severity)
**Use case:** Show how minor issues can escalate

**Schedule:**
- T+0:00 - Minor slowness (LLM: low severity)
- T+5:00 - Worsening performance (LLM: medium severity)
- T+10:00 - Database bottleneck identified (predefined)
- T+15:00 - Memory leak from connection pool (predefined)
- T+20:00 - Critical: OOM pod crashes (predefined)

---

## Creating Custom Timelines

### JSON Schema

```json
{
  "name": "My Custom Timeline",
  "description": "Description of what this timeline simulates",
  "duration_minutes": 20,
  "incidents": [
    {
      "delay_seconds": 0,
      "type": "predefined",
      "scenario_id": "memory_leak_gradual",
      "comment": "Optional description"
    },
    {
      "delay_seconds": 300,
      "type": "llm_generated",
      "llm_prompt": "Generate a Redis cache failure with cascading effects",
      "service_name": "payment-service",
      "expected_severity": "high",
      "comment": "LLM creates custom scenario"
    }
  ]
}
```

### Incident Types

#### Type 1: Predefined Scenarios

```json
{
  "delay_seconds": 60,
  "type": "predefined",
  "scenario_id": "cpu_spike_traffic_surge",
  "comment": "Uses pre-written scenario"
}
```

**Available scenario_ids:**
- `memory_leak_gradual`
- `cpu_spike_traffic_surge`
- `latency_spike_database`
- `pod_crash_loop`
- `dependency_failure_timeout`

#### Type 2: LLM-Generated Scenarios

```json
{
  "delay_seconds": 120,
  "type": "llm_generated",
  "llm_prompt": "Generate a disk I/O bottleneck incident affecting transaction processing. Include high disk wait times and slow database writes.",
  "service_name": "payment-service",
  "expected_severity": "high",
  "comment": "LLM creates on-the-fly"
}
```

**LLM Prompt Guidelines:**
- Be specific about the incident type
- Mention relevant metrics (CPU, memory, disk, network, etc.)
- Specify severity implications
- Include context (what's affected, why it matters)

**Example prompts:**
```
"Generate a Kubernetes pod scheduling failure incident where pods cannot be scheduled due to resource constraints"

"Create a Redis connection pool exhaustion scenario with cascading failures to dependent services"

"Generate a DNS resolution timeout incident affecting external API calls with increasing error rates"

"Create a TLS certificate expiration incident causing authentication failures"
```

---

## Running Timelines

### Basic Usage

```bash
# Run predefined timeline
python scripts/demo/run_timeline.py --timeline incident_storm

# Run custom timeline from file
python scripts/demo/run_timeline.py --file my_custom_timeline.json
```

### Example Session

```bash
$ python scripts/demo/run_timeline.py --timeline busy_day

╭─────────────────────────────────────────────────────╮
│              🎬 Timeline Starting                    │
│                                                      │
│              Busy Day Timeline                       │
│   Simulates a busy day with multiple incidents      │
│                                                      │
│  Duration: 30 minutes                               │
│  Incidents: 4 scenarios                             │
╰─────────────────────────────────────────────────────╯

              📅 Incident Schedule
Time    Type            Description
+00:00  📦 Pre-defined  Morning memory leak from batch job
+05:00  📦 Pre-defined  Mid-morning traffic surge
+10:00  📦 Pre-defined  Database slows down
+15:00  📦 Pre-defined  External payment gateway timeout

Press Enter to start timeline...

⠋ Timeline Progress (0/4 incidents) ━━━━━━━━━━━━ 00:00

▶ Starting predefined scenario: memory_leak_gradual
  → Incident ID: 42, Hypotheses: 3, Actions: 2

⠋ Waiting 300s until next incident... ━━━━━━━━━━━━ 02:15

▶ Starting predefined scenario: cpu_spike_traffic_surge
  → Incident ID: 43, Hypotheses: 2, Actions: 1

...

╭─────────────────────────────────────────────────────╮
│        ✓ Timeline Execution Complete                 │
│                                                      │
│  Total Incidents Created: 4                         │
│  Execution Time: 902.3 seconds                      │
╰─────────────────────────────────────────────────────╯

           📊 Timeline Execution Summary
╭───┬─────────┬────────────────┬──────────────┬────────╮
│ # │ Time    │ Type           │ Comment      │ Inc ID │
├───┼─────────┼────────────────┼──────────────┼────────┤
│ 1 │ +00:00  │ 📦 Pre-defined │ Morning memo │ 42     │
│ 2 │ +05:00  │ 📦 Pre-defined │ Mid-morning  │ 43     │
│ 3 │ +10:00  │ 📦 Pre-defined │ Database slo │ 44     │
│ 4 │ +15:00  │ 📦 Pre-defined │ External pay │ 45     │
╰───┴─────────┴────────────────┴──────────────┴────────╯
```

---

## LLM Scenario Generation

### How It Works

1. **Timeline defines prompt**: JSON config includes natural language description
2. **LLM generates schema**: Creates incident with metrics, context, root cause
3. **Converts to scenario**: Transforms LLM output to `IncidentScenario` format
4. **Runs simulation**: Feeds into normal incident simulator flow

### Generated Scenario Example

**Input prompt:**
```
"Generate a Redis connection pool exhaustion incident with cascading failures"
```

**LLM Output (structured):**
```json
{
  "name": "Redis Connection Pool Exhaustion",
  "description": "Connection pool to Redis cache has been exhausted...",
  "root_cause": "connection_pool_exhaustion",
  "severity": "high",
  "metrics": [
    {
      "metric_name": "redis_connections_active",
      "value": 500,
      "baseline": 50,
      "deviation_sigma": 6.2,
      "unit": "connections"
    },
    {
      "metric_name": "http_request_duration_seconds_p95",
      "value": 5.8,
      "baseline": 0.4,
      "deviation_sigma": 5.5,
      "unit": "seconds"
    }
    ...
  ],
  "context": {
    "recent_deployments": [...]
  },
  "expected_action_types": ["restart", "scale_connection_pool"]
}
```

### Advantages of LLM Generation

✅ **Unlimited Variety**: Never see the same incident twice
✅ **Realistic Unknowns**: Mimics production unpredictability
✅ **Educational**: Each incident teaches something new
✅ **No Coding**: Non-engineers can create scenarios via prompts
✅ **Dynamic Adaptation**: Can reference current events or trends

### Limitations

⚠️ **Non-deterministic**: Output varies between runs
⚠️ **Slower**: Adds 2-5 seconds per incident (LLM API call)
⚠️ **API Costs**: Each incident costs ~$0.01-0.05 in LLM tokens
⚠️ **Quality Variance**: Occasional suboptimal scenarios
⚠️ **Validation Needed**: Must handle edge cases in LLM output

---

## Use Cases

### 1. Live Demos

**Best Timeline:** `busy_day` (predictable, reliable)

Use predefined scenarios for consistent demos:
```bash
python scripts/demo/run_timeline.py --timeline busy_day
```

### 2. Stress Testing

**Best Timeline:** Custom with many concurrent incidents

Create JSON with short delays to test system load:
```json
{
  "incidents": [
    {"delay_seconds": 0, "type": "predefined", ...},
    {"delay_seconds": 5, "type": "predefined", ...},
    {"delay_seconds": 10, "type": "predefined", ...}
  ]
}
```

### 3. Training Sessions

**Best Timeline:** `gradual_escalation` (educational progression)

Shows how incidents compound and escalate:
```bash
python scripts/demo/run_timeline.py --timeline gradual_escalation
```

### 4. Exploratory Testing

**Best Timeline:** `incident_storm` (variety via LLM)

Test AIRRA against novel, unseen incidents:
```bash
python scripts/demo/run_timeline.py --timeline incident_storm
```

---

## Advanced Features

### Parallel Incident Injection

Set same `delay_seconds` for concurrent incidents:

```json
{
  "incidents": [
    {"delay_seconds": 60, "type": "predefined", "scenario_id": "memory_leak_gradual"},
    {"delay_seconds": 60, "type": "predefined", "scenario_id": "cpu_spike_traffic_surge"},
    {"delay_seconds": 60, "type": "llm_generated", "llm_prompt": "Database timeout"}
  ]
}
```

This creates 3 incidents simultaneously to test AIRRA's multi-incident handling.

### Variable Timing

Use realistic delays based on typical incident patterns:

```json
{
  "incidents": [
    {"delay_seconds": 0, ...},        // Start immediately
    {"delay_seconds": 300, ...},      // 5 minutes later
    {"delay_seconds": 420, ...},      // 7 minutes (2 min after previous)
    {"delay_seconds": 1200, ...}      // 20 minutes (major delay)
  ]
}
```

### LLM Prompt Variations

Create themed incident streams:

**Database Issues Day:**
```json
[
  {"llm_prompt": "Slow query due to missing index"},
  {"llm_prompt": "Connection pool exhaustion"},
  {"llm_prompt": "Deadlock causing transaction failures"},
  {"llm_prompt": "Replication lag affecting reads"}
]
```

**Infrastructure Failures:**
```json
[
  {"llm_prompt": "Kubernetes node failure"},
  {"llm_prompt": "Network partition between services"},
  {"llm_prompt": "Load balancer misconfiguration"},
  {"llm_prompt": "DNS resolution timeouts"}
]
```

---

## Troubleshooting

### LLM Generation Fails

**Symptom:** Error during LLM-generated incident

**Causes:**
- LLM API key not configured
- LLM rate limits hit
- Invalid prompt structure

**Solution:**
```bash
# Check LLM client configuration
cat backend/.env | grep LLM

# Reduce LLM-generated incidents in timeline
# OR use predefined scenarios only
```

### Backend Not Running

**Symptom:** Connection refused errors

**Solution:**
```bash
cd backend
uvicorn app.main:app --reload
```

### Timeline Too Long

**Symptom:** Demo takes too long

**Solution:** Edit JSON and reduce delays:
```json
{
  "incidents": [
    {"delay_seconds": 0, ...},
    {"delay_seconds": 30, ...},   // Reduced from 300
    {"delay_seconds": 60, ...}    // Reduced from 600
  ]
}
```

---

## Best Practices

### For Reliable Demos

1. ✅ Use **predefined scenarios** only
2. ✅ Test timeline once before presenting
3. ✅ Keep total duration under 10 minutes
4. ✅ Use meaningful comments for narration

### For Exploration

1. ✅ Mix predefined + LLM-generated
2. ✅ Use diverse, specific LLM prompts
3. ✅ Include delays between incidents (60-300s)
4. ✅ Review generated metrics for quality

### For Training

1. ✅ Use `gradual_escalation` pattern
2. ✅ Add comments explaining each step
3. ✅ Start simple, end complex
4. ✅ Pause timeline to discuss each incident

---

## Comparison: Single vs. Timeline

| Feature | Single Scenario | Timeline |
|---------|----------------|----------|
| **Use Case** | Quick demo of one issue | Realistic incident stream |
| **Complexity** | Simple | Complex |
| **Time** | 30 seconds | 5-30 minutes |
| **Incidents** | 1 | 3-10 |
| **Variety** | Fixed | Predefined + LLM |
| **Best For** | Feature demos | System capability demos |

---

## Future Enhancements

- [ ] Web UI for timeline creation
- [ ] Timeline templates based on real production patterns
- [ ] Incident correlation visualization
- [ ] Real-time metrics dashboard during timeline
- [ ] Timeline recording/playback
- [ ] Multi-service timelines (not just payment-service)
- [ ] Scenario difficulty progression (tutorial mode)

---

## Related Documentation

- [Incident Simulator](./simulator.md) - Base simulator system
- [Quick Incident API](../backend/app/api/v1/quick_incident.py) - Incident creation
- [LLM Scenario Generator](../backend/app/core/simulation/llm_scenario_generator.py) - Dynamic generation
