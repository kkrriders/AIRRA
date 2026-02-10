# AIRRA Demo Scripts

Beautiful CLI demos for the Incident Simulator with rich terminal output.

## Quick Setup

### 1. Install Dependencies

```bash
# From the AIRRA root directory
pip install -r scripts/requirements.txt
```

This installs:
- `rich` - Beautiful terminal output
- `httpx` - HTTP client for API calls

### 2. Start the Backend

```bash
cd backend
uvicorn app.main:app --reload
```

### 3. (Optional) Start Mock Service

For realistic metric injection:
```bash
python mock-services/payment-service.py
```

Note: Demo works without mock service - it will use simulated metrics instead.

---

## Usage

### List Available Scenarios

```bash
python scripts/demo/run_demo.py --list
```

**Output**: Beautiful table showing all 5 scenarios with difficulty, severity, and tags.

---

### Run a Specific Scenario

```bash
python scripts/demo/run_demo.py memory_leak_gradual
```

This will:
1. 📋 Display scenario details
2. ⏸️  Wait for you to press Enter
3. 🚀 Start the simulation with progress indicators
4. 🧠 Show LLM-generated hypotheses
5. 🔧 Display recommended actions
6. ✅ Provide incident link

**Demo time**: ~30 seconds

---

### Interactive Mode

```bash
python scripts/demo/run_demo.py --interactive
```

Presents a menu to select from available scenarios.

---

### Scenario-Specific Demos (With Storytelling)

These include narrative context perfect for presentations:

```bash
# Memory leak with deployment context
python scripts/demo/demo_memory_leak.py

# Traffic surge with Black Friday context
python scripts/demo/demo_cpu_spike.py

# Database performance with missing index context
python scripts/demo/demo_latency_spike.py
```

Each includes:
- 📖 Background story
- 🔍 What happened and why
- 📊 Symptom details
- 🤖 What AIRRA will do
- 📚 Learning points

---

## Available Scenarios

| Scenario ID | Name | Difficulty | Severity |
|------------|------|------------|----------|
| `memory_leak_gradual` | Gradual Memory Leak | ●○○ Beginner | 🔴 Critical |
| `cpu_spike_traffic_surge` | CPU Spike from Traffic | ●○○ Beginner | 🟠 High |
| `latency_spike_database` | Database Latency Spike | ●●○ Intermediate | 🟠 High |
| `pod_crash_loop` | Pod Crash Loop | ●●○ Intermediate | 🔴 Critical |
| `dependency_failure_timeout` | External Service Timeout | ●●● Advanced | 🟠 High |

---

## Command-Line Options

### run_demo.py

```bash
python scripts/demo/run_demo.py [OPTIONS] [SCENARIO_ID]

Options:
  -l, --list          List all available scenarios
  -i, --interactive   Interactive mode for selecting scenarios
  --no-details        Skip showing scenario details before running

Arguments:
  SCENARIO_ID         ID of scenario to run (e.g., memory_leak_gradual)

Examples:
  python scripts/demo/run_demo.py --list
  python scripts/demo/run_demo.py memory_leak_gradual
  python scripts/demo/run_demo.py --interactive
  python scripts/demo/run_demo.py cpu_spike_traffic_surge --no-details
```

---

## Troubleshooting

### Import Error: "rich.console could not be resolved"

**Solution**: Install dependencies
```bash
pip install -r scripts/requirements.txt
```

### Connection Error: "API Error: Could not connect"

**Solution**: Make sure the backend is running
```bash
cd backend
uvicorn app.main:app --reload
```

### Mock Service Warning

**Message**: `metrics_injected: false (mock service offline)`

**Impact**: Demo still works! Uses simulated metrics instead of real injection.

**To Fix** (optional):
```bash
python mock-services/payment-service.py
```

---

## Demo Tips

### For Presentations

1. **Pre-run once**: Run a scenario before your demo to warm up the system
2. **Use full screen**: Terminal output looks best in fullscreen
3. **Pause at key moments**: Let audience read hypothesis confidence scores
4. **Show the UI**: After CLI demo, open the web UI to show the incident

### For Training

1. **Start simple**: Begin with `memory_leak_gradual` or `cpu_spike_traffic_surge`
2. **Add narrative**: Use the scenario-specific demos (`demo_*.py`) for context
3. **Discuss decisions**: Pause to explain why AIRRA chose certain hypotheses
4. **Compare actions**: Show how risk levels and blast radius affect recommendations

### For Testing

1. **Use --no-details**: Skip the intro when running multiple scenarios
2. **Chain commands**: Run all scenarios in sequence for comprehensive testing
   ```bash
   for scenario in memory_leak_gradual cpu_spike_traffic_surge latency_spike_database; do
       python scripts/demo/run_demo.py $scenario --no-details
       sleep 5
   done
   ```

---

## Sample Output

### List View
```
╭─────────────────────────────────────────────────────────╮
│           AIRRA Incident Simulator                      │
│   Pre-packaged realistic incident scenarios for demos   │
╰─────────────────────────────────────────────────────────╯

              📋 Available Scenarios
╭──────────────────────┬─────────────────┬──────────┬───────────┬────────╮
│ ID                   │ Name            │ Severity │ Difficulty│ Tags   │
├──────────────────────┼─────────────────┼──────────┼───────────┼────────┤
│ memory_leak_gradual  │ Gradual Memory  │ CRITICAL │   ●○○     │ resour │
│                      │ Leak            │          │           │ ce...  │
╰──────────────────────┴─────────────────┴──────────┴───────────┴────────╯
```

### Running Demo
```
╭─────────────────────────────────────────────────────────╮
│              🚀 Starting Simulation                      │
╰─────────────────────────────────────────────────────────╯

⠋ Injecting metrics into mock service...     ━━━━━━━━━━━━━━━━━━ 00:01
✓ Creating incident in database...           ━━━━━━━━━━━━━━━━━━ 00:02
⠋ Analyzing with LLM (generating hypotheses) ━━━━━━━━━━━━━━━━━━ 00:05
✓ Generating remediation actions...          ━━━━━━━━━━━━━━━━━━ 00:06

╭─────────────────────────────────────────────────────────╮
│         ✓ Simulation Started Successfully                │
│                                                          │
│  Simulation ID:  sim_a1b2c3d4                           │
│  Incident ID:    42                                     │
│  Hypotheses:     3                                      │
│  Actions:        2                                      │
│  Metrics:        ✓                                      │
╰─────────────────────────────────────────────────────────╯
```

---

## Python API

You can also use the demo functions programmatically:

```python
import asyncio
from run_demo import run_scenario_demo, list_scenarios

# List scenarios
scenarios = await list_scenarios()
for scenario in scenarios:
    print(f"{scenario['id']}: {scenario['name']}")

# Run a scenario
await run_scenario_demo("memory_leak_gradual", show_details=True)
```

---

## Related Documentation

- [Simulator Documentation](../../docs/simulator.md) - Complete API reference
- [Quick Incident API](../../backend/app/api/v1/quick_incident.py) - Backend API
- [Scenario Definitions](../../backend/app/core/simulation/scenario_definitions.py) - Scenario source code
