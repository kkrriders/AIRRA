# Incident Simulator

The Incident Simulator provides pre-packaged realistic incident scenarios for demonstrations, testing, and training. It automatically injects metrics, creates incidents, and runs LLM analysis to show AIRRA's capabilities.

## Features

- **5 Realistic Scenarios**: Memory leaks, CPU spikes, latency issues, pod crashes, and dependency failures
- **Automated Metric Injection**: Simulates realistic metrics via mock service
- **LLM Analysis**: Automatically generates hypotheses and action recommendations
- **Beautiful CLI Demos**: Rich terminal output perfect for presentations
- **REST API**: Programmatic access for automation and testing

---

## Available Scenarios

### 1. Memory Leak (Gradual)
**ID**: `memory_leak_gradual`
**Difficulty**: Beginner
**Severity**: Critical

A gradual memory leak exhausts memory over time, triggering OOM kills. Demonstrates AIRRA's ability to correlate memory metrics with recent deployments.

**Key Metrics**:
- Memory usage: 8 GB (5.2σ from baseline 2 GB)
- Heap allocations: 15M (4.8σ from baseline 2M)
- Garbage collections: 5000 (4.5σ from baseline 500)

**Expected Outcomes**: Memory leak hypothesis, restart/rollback actions

---

### 2. CPU Spike (Traffic Surge)
**ID**: `cpu_spike_traffic_surge`
**Difficulty**: Beginner
**Severity**: High

Sudden traffic surge causes CPU saturation and request queueing. Shows AIRRA's capacity planning recommendations.

**Key Metrics**:
- CPU usage: 98.5% (6.0σ from baseline 45%)
- Request rate: 3500 req/s (5.5σ from baseline 800)
- P95 latency: 4.2s (5.0σ from baseline 0.3s)

**Expected Outcomes**: Capacity/scaling hypothesis, horizontal scaling actions

---

### 3. Latency Spike (Database)
**ID**: `latency_spike_database`
**Difficulty**: Intermediate
**Severity**: High

Database queries slow down due to missing index or lock contention. Demonstrates AIRRA's multi-layer dependency analysis.

**Key Metrics**:
- P95 API latency: 8.5s (6.5σ from baseline 0.4s)
- Database query duration: 7.2s (7.0σ from baseline 0.05s)
- DB connections active: 98/100 (5.5σ from baseline 15)

**Expected Outcomes**: Database performance hypothesis, index/optimization actions

---

### 4. Pod Crash Loop
**ID**: `pod_crash_loop`
**Difficulty**: Intermediate
**Severity**: Critical

Pods crash repeatedly after a bad deployment. Shows AIRRA's deployment correlation and rollback recommendations.

**Key Metrics**:
- Pod restarts: 45 (8.0σ from baseline 0)
- Pod ready count: 1 (down from 3)
- Request rate: 50 req/s (down from 800)

**Expected Outcomes**: Deployment issue hypothesis, rollback actions

---

### 5. Dependency Failure (External Service)
**ID**: `dependency_failure_timeout`
**Difficulty**: Advanced
**Severity**: High

External payment gateway times out, causing cascading failures. Demonstrates AIRRA's dependency analysis and circuit breaker recommendations.

**Key Metrics**:
- External API call duration: 30s (8.0σ from baseline 0.5s)
- HTTP 500 errors: 850 (7.5σ from baseline 5)
- Circuit breaker: Open

**Expected Outcomes**: External dependency hypothesis, circuit breaker/fallback actions

---

## Quick Start

### Prerequisites

1. **Start the backend server**:
   ```bash
   cd backend
   uvicorn app.main:app --reload
   ```

2. **Start the mock payment service** (optional, for metric injection):
   ```bash
   python mock-services/payment-service.py
   ```

3. **Install dependencies**:
   ```bash
   pip install rich>=13.0.0
   ```

---

## Usage

### CLI Demo Scripts

#### List Available Scenarios
```bash
python scripts/demo/run_demo.py --list
```

Output shows a beautiful table with all scenarios, their difficulty, severity, and tags.

#### Run a Specific Scenario
```bash
python scripts/demo/run_demo.py memory_leak_gradual
```

This will:
1. Display scenario details
2. Start the simulation
3. Show real-time progress (injecting metrics, creating incident, analyzing with LLM)
4. Display generated hypotheses and actions
5. Provide link to view in UI

#### Interactive Mode
```bash
python scripts/demo/run_demo.py --interactive
```

Presents a menu to select from available scenarios.

#### Scenario-Specific Demos (with Narrative)
```bash
python scripts/demo/demo_memory_leak.py
python scripts/demo/demo_cpu_spike.py
python scripts/demo/demo_latency_spike.py
```

These include storytelling context perfect for presentations.

---

### REST API

#### List Scenarios
```bash
curl http://localhost:8000/api/v1/simulator/scenarios \
  -H "X-API-Key: test-api-key"
```

**Response**:
```json
[
  {
    "id": "memory_leak_gradual",
    "name": "Gradual Memory Leak",
    "description": "A memory leak in the payment service...",
    "service": "payment-service",
    "severity": "critical",
    "difficulty": "beginner",
    "tags": ["resource", "availability"],
    "duration_seconds": 300,
    "metric_count": 4
  }
]
```

#### Get Scenario Details
```bash
curl http://localhost:8000/api/v1/simulator/scenarios/memory_leak_gradual \
  -H "X-API-Key: test-api-key"
```

**Response**: Detailed scenario info including all metrics, context, and expected outcomes.

#### Start Simulation
```bash
curl -X POST http://localhost:8000/api/v1/simulator/scenarios/memory_leak_gradual/start \
  -H "X-API-Key: test-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "auto_analyze": true,
    "execution_mode": "demo"
  }'
```

**Response**:
```json
{
  "simulation_id": "sim_a1b2c3d4",
  "scenario_id": "memory_leak_gradual",
  "incident_id": 42,
  "status": "completed",
  "started_at": "2024-01-15T10:30:00Z",
  "hypotheses_count": 3,
  "actions_count": 2,
  "metrics_injected": true
}
```

#### Get Simulation Status
```bash
curl http://localhost:8000/api/v1/simulator/simulations/sim_a1b2c3d4 \
  -H "X-API-Key: test-api-key"
```

#### Stop Simulation
```bash
curl -X POST http://localhost:8000/api/v1/simulator/simulations/sim_a1b2c3d4/stop \
  -H "X-API-Key: test-api-key"
```

---

## Architecture

### Components

```
┌─────────────────────────────────────────────────────────┐
│                  Scenario Definitions                    │
│                 (scenario_definitions.py)                │
│  • 5 pre-defined scenarios with metrics and context     │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│                   Scenario Runner                        │
│                  (scenario_runner.py)                    │
│  • Orchestrates simulation flow                         │
│  • Calls metric injector and quick_incident API         │
└─────────────┬──────────────────────┬────────────────────┘
              │                      │
              ▼                      ▼
┌─────────────────────┐    ┌─────────────────────────────┐
│  Metric Injector    │    │   Quick Incident API        │
│ (metric_injector.py)│    │  (quick_incident.py)        │
│                     │    │                             │
│ • Injects metrics   │    │ • Creates incident          │
│ • Calls mock service│    │ • LLM hypothesis generation │
└─────────────────────┘    │ • Action recommendations    │
                           └─────────────────────────────┘
```

### Design Principles

1. **Reuse Existing APIs**: The simulator calls the existing `quick_incident` API rather than duplicating LLM logic
2. **Declarative Scenarios**: Scenarios are defined as dataclasses, making it easy to add new ones
3. **Graceful Degradation**: Works even if mock service is unavailable (uses simulated metrics)
4. **Singleton Pattern**: Scenario runner and metric injector use singletons for resource efficiency

---

## Adding Custom Scenarios

To add a new scenario, edit `backend/app/core/simulation/scenario_definitions.py`:

```python
SCENARIO_CUSTOM = IncidentScenario(
    scenario_id="custom_scenario",
    name="My Custom Scenario",
    description="Description of what goes wrong...",
    service_name="my-service",
    metrics=[
        MetricPattern(
            metric_name="error_rate",
            value=0.15,  # 15% errors
            baseline=0.01,  # Expected 1%
            deviation_sigma=5.0,  # 5 standard deviations
            pattern_type=MetricPatternType.SPIKE,
            unit="%",
        ),
        # Add more metrics...
    ],
    expected_severity="high",
    expected_root_cause="custom_issue",
    expected_action_types=["restart", "investigate"],
    context={
        "recent_deployments": [...],
        # Add context...
    },
    tags=[ScenarioTag.PERFORMANCE],
    difficulty=ScenarioDifficulty.INTERMEDIATE,
    duration_seconds=180,
)

# Register it
SCENARIO_REGISTRY["custom_scenario"] = SCENARIO_CUSTOM
```

---

## Testing

Run integration tests:
```bash
cd backend
pytest tests/integration/test_simulator_api.py -v
```

Tests cover:
- Listing scenarios with filters
- Getting scenario details
- Starting simulations (with mocked LLM)
- Stopping simulations
- Error handling

---

## Troubleshooting

### Mock Service Not Running

**Symptom**: `metrics_injected: false` in simulation response

**Solution**: The simulator still works! It uses simulated metrics instead. To enable real metric injection:
```bash
python mock-services/payment-service.py
```

### LLM Rate Limits

**Symptom**: 429 errors when running many simulations

**Solution**: Adjust rate limits in `app/config.py` or space out simulations:
```bash
python scripts/demo/run_demo.py memory_leak_gradual
sleep 60  # Wait between simulations
python scripts/demo/run_demo.py cpu_spike_traffic_surge
```

### Database Connection Issues

**Symptom**: Cannot create incidents

**Solution**: Ensure PostgreSQL is running and DATABASE_URL is configured:
```bash
docker-compose up -d postgres
```

---

## Demo Best Practices

### For Presentations

1. **Pre-warm the system**: Run a simulation once before your demo to ensure everything is loaded
2. **Use scenario-specific demos**: The narrative scripts (`demo_memory_leak.py`) are more engaging
3. **Show the UI**: After CLI demo, open `http://localhost:3000/incidents/{id}` to show the web interface
4. **Explain the AI**: Pause to explain hypothesis confidence scores and action risk levels

### For Training

1. **Start with beginner scenarios**: Memory leak and CPU spike are easiest to understand
2. **Progress to advanced**: Dependency failure requires understanding of distributed systems
3. **Compare hypotheses**: Discuss why the LLM ranked hypotheses in a particular order
4. **Explore actions**: Show how AIRRA considers risk and blast radius

### For Testing

1. **Use API directly**: CLI is for humans, API is for automation
2. **Validate expected outcomes**: Check that scenarios generate the expected hypothesis categories
3. **Test edge cases**: Try simulations without mock service, with database issues, etc.

---

## Future Enhancements

- **Multi-phase scenarios**: Incidents that evolve over time (e.g., memory leak that becomes OOM)
- **Custom scenario builder**: UI for creating scenarios without editing code
- **Scenario validation**: Automated testing of LLM output quality against expected outcomes
- **Recording/playback**: Save simulation sessions for later review
- **Web UI**: Scenario buttons in the frontend for one-click demos

---

## Related Documentation

- [Quick Incident API](../backend/app/api/v1/quick_incident.py) - The API used for incident creation
- [What-If Simulator](../backend/app/core/simulation/what_if_simulator.py) - Compare remediation actions
- [LLM Integration](./llm-integration.md) - How hypothesis generation works
