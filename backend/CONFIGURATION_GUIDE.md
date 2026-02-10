# AIRRA Configuration Guide

This guide explains how to configure AIRRA's new deterministic systems.

## Configuration Files Overview

AIRRA uses two primary configuration files for deterministic decision-making:

1. **`config/service_dependencies.yaml`** - Service topology and dependencies
2. **`config/runbooks.yaml`** - Approved remediation actions

These files are automatically created with examples on first run. Customize them for your organization.

## Service Dependencies Configuration

### Purpose
- Define service topology
- Enable topology-aware root cause analysis
- Boost hypothesis confidence for upstream failures

### File Location
`config/service_dependencies.yaml`

### Example Structure
```yaml
services:
  frontend:
    depends_on:
      - api-gateway
    tier: tier-1
    team: frontend
    criticality: high

  api-gateway:
    depends_on:
      - auth-service
      - payment-service
      - order-service
    tier: tier-1
    team: platform
    criticality: critical

  payment-service:
    depends_on:
      - database
      - redis
      - payment-gateway
    tier: tier-1
    team: payments
    criticality: critical

  database:
    depends_on: []
    tier: tier-0
    team: infrastructure
    criticality: critical
```

### Fields Explained

- **`depends_on`**: List of upstream dependencies
  - Services this service calls
  - Used for hypothesis boosting
  - Empty list for infrastructure components

- **`tier`**: Service tier classification
  - `tier-0`: Infrastructure (database, cache, message queue)
  - `tier-1`: Critical business services (payments, auth)
  - `tier-2`: Important but not critical
  - `tier-3`: Non-critical services

- **`team`**: Owning team
  - Used for escalation routing
  - Appears in incident notifications

- **`criticality`**: Business impact
  - `critical`: Revenue-impacting, immediate escalation
  - `high`: Important services, escalate quickly
  - `medium`: Standard priority
  - `low`: Best-effort support

### Dependency Boost Formula

When analyzing incidents, AIRRA boosts hypothesis confidence based on dependencies:

- **Direct upstream dependency failing**: +15% confidence
  - Example: If `database` is failing and `payment-service` depends on it
- **Transitive upstream dependency**: +8% confidence
  - Example: If `database` → `payment-service` → `api-gateway` chain
- **Downstream dependency failing**: -5% confidence
  - Example: If `frontend` is failing but `api-gateway` is the root cause (unlikely)

### Best Practices

1. **Start with infrastructure**
   - Define databases, caches, message queues first
   - These are tier-0 with no dependencies

2. **Build up the stack**
   - Add services layer by layer
   - Verify dependency direction (calls flow down tiers)

3. **Be specific about criticality**
   - Reserve `critical` for revenue-impacting services
   - Use `high` for important but not revenue-critical
   - Most services should be `medium`

4. **Keep it current**
   - Update when services are added/removed
   - Review quarterly
   - Version control this file

## Runbooks Configuration

### Purpose
- Constrain allowed remediation actions
- Prevent LLM from inventing unauthorized actions
- Define approval requirements and prerequisites
- Set rate limits for automated actions

### File Location
`config/runbooks.yaml`

### Example Structure
```yaml
runbooks:
  - id: memory-leak-restart
    name: "Memory Leak - Pod Restart"
    symptom: "Memory usage steadily increasing beyond normal bounds"
    category: memory_leak
    service: null  # Applies to all services

    allowed_actions:
      - action_type: restart_pod
        description: "Restart pod to clear memory leak"
        approval_required: true
        risk_level: medium
        parameters:
          namespace: production
          graceful_shutdown: true
        prerequisites:
          - "Multiple replicas available"
          - "Memory usage > 80%"
        max_auto_executions_per_day: 5

    diagnostic_queries:
      memory_usage: 'container_memory_usage_bytes{pod=~"{{service}}.*"}'
      memory_limit: 'container_spec_memory_limit_bytes{pod=~"{{service}}.*"}'

    escalation_criteria:
      - "Memory leak persists after restart"
      - "Multiple restarts within 1 hour"
      - "Affects tier-1 service"

  - id: cpu-spike-scale-up
    name: "CPU Spike - Scale Up"
    symptom: "CPU usage sustained above threshold"
    category: cpu_spike

    allowed_actions:
      - action_type: scale_up
        description: "Scale up replicas to handle CPU load"
        approval_required: false
        risk_level: low
        parameters:
          namespace: production
          min_replicas: 1
          max_replicas: 10
        prerequisites:
          - "Current replicas < max_replicas"
          - "CPU usage > 70%"
        max_auto_executions_per_day: 10

    diagnostic_queries:
      cpu_usage: 'rate(container_cpu_usage_seconds_total{pod=~"{{service}}.*"}[5m]) * 100'

    escalation_criteria:
      - "CPU remains high after scaling"
      - "Already at max replicas"
```

### Fields Explained

#### Runbook Level

- **`id`**: Unique identifier
  - Use kebab-case
  - Should describe category and action
  - Example: `memory-leak-restart`, `error-spike-rollback`

- **`name`**: Human-readable name
  - Appears in UI and notifications
  - Should be clear and descriptive

- **`symptom`**: Problem description
  - What operators would observe
  - Used for documentation and training

- **`category`**: Problem category
  - Must match hypothesis categories
  - Options: `memory_leak`, `cpu_spike`, `error_spike`, `database_issue`, `network_issue`, etc.
  - AIRRA matches hypotheses to runbooks by category

- **`service`**: Service-specific runbook (optional)
  - `null` or omit: Applies to all services
  - `payment-service`: Only for specific service
  - Use for service-specific procedures

#### Action Level

- **`action_type`**: Type of action
  - Must be valid ActionType enum value
  - Options: `restart_pod`, `scale_up`, `scale_down`, `rollback_deployment`, `clear_cache`, `drain_node`

- **`description`**: Action description
  - What this action does
  - Appears in approval requests

- **`approval_required`**: Human approval needed?
  - `true`: Action requires human approval
  - `false`: Can execute automatically (if confidence high enough)
  - Recommendation: `true` for all destructive actions

- **`risk_level`**: Risk assessment
  - `low`: Scaling up, cache clear
  - `medium`: Pod restart
  - `high`: Rollback, scaling down
  - `critical`: Production database changes

- **`parameters`**: Default parameters
  - Template for action execution
  - Can include variable substitution (`{{service}}`)
  - Merged with incident-specific parameters

- **`prerequisites`**: Conditions to check before execution
  - List of human-readable checks
  - Currently documentation only
  - Future: Automated validation

- **`max_auto_executions_per_day`**: Rate limit
  - Maximum automatic executions in 24 hours
  - Prevents runaway automation
  - `null` = unlimited (not recommended)

#### Diagnostic Queries

- **`diagnostic_queries`**: Prometheus queries
  - Used for verification
  - Template variables: `{{service}}`, `{{namespace}}`
  - Helps operators investigate

#### Escalation Criteria

- **`escalation_criteria`**: When to escalate to humans
  - List of conditions
  - Currently documentation only
  - Future: Automated escalation

### Action Types Reference

| Action Type | Risk | Typical Use | Approval? |
|-------------|------|-------------|-----------|
| `scale_up` | Low | Handle load spikes | No |
| `scale_down` | Low-Medium | Reduce over-provisioning | Yes |
| `restart_pod` | Medium | Clear memory leaks, hung processes | Yes |
| `rollback_deployment` | High | Revert bad deployment | Yes |
| `clear_cache` | Low | Clear corrupted cache | No |
| `drain_node` | High | Remove unhealthy node | Yes |
| `toggle_feature_flag` | Medium | Disable problematic feature | Yes |

### Best Practices

1. **Start conservative**
   - Require approval for most actions initially
   - Gradually enable auto-execution as confidence builds
   - Monitor outcomes before expanding automation

2. **Set appropriate rate limits**
   - Prevent runaway automation
   - Balance responsiveness vs safety
   - Lower limits for high-risk actions

3. **Document prerequisites clearly**
   - Even if not automated, helps operators
   - Ensures consistent execution
   - Basis for future automation

4. **Match diagnostic queries to symptoms**
   - Include queries operators would run manually
   - Use templates for flexibility
   - Test queries in Prometheus UI first

5. **Define escalation criteria**
   - When should this NOT be automated?
   - When should humans take over?
   - What indicates action failed?

## Post-Action Verification

### Configuration

Verification is configured in code but uses these settings:

```python
PostActionVerifier(
    prometheus_client=prometheus_client,
    stabilization_window_seconds=120,  # 2 minutes
    improvement_threshold=0.20,  # 20% improvement required
)
```

### Metrics Checked

After every action, AIRRA waits for stabilization then checks:

1. **Error Rate**: `rate(http_requests_total{status=~"5.."}[1m]) * 60`
2. **Latency P95**: `histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))`
3. **Latency P99**: `histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))`
4. **Availability**: `up{service="..."}`
5. **Request Rate**: `rate(http_requests_total[1m])`

### Verification Outcomes

- **SUCCESS**: ≥20% improvement → Continue monitoring
- **PARTIAL_SUCCESS**: 10-20% improvement → Keep watching
- **NO_CHANGE**: No improvement → Escalate to human
- **DEGRADED**: Metrics worse → Rollback immediately
- **UNSTABLE**: Fluctuating → Escalate to human

## Environment Variables

### Required

```bash
# LLM Provider (required)
AIRRA_LLM_PROVIDER=anthropic  # or openai, openrouter, groq
AIRRA_ANTHROPIC_API_KEY=sk-ant-...  # if using anthropic
AIRRA_OPENAI_API_KEY=sk-...  # if using openai

# Database (required)
AIRRA_DATABASE_URL=postgresql+asyncpg://user:pass@localhost/airra

# Redis (optional, recommended)
AIRRA_REDIS_URL=redis://localhost:6379/0
```

### Optional

```bash
# Configuration paths
AIRRA_DEPENDENCY_CONFIG=config/service_dependencies.yaml
AIRRA_RUNBOOKS_CONFIG=config/runbooks.yaml

# Verification settings
AIRRA_VERIFICATION_WINDOW=120  # seconds
AIRRA_IMPROVEMENT_THRESHOLD=0.20  # 20%

# Deduplication
AIRRA_DEDUP_WINDOW=300  # seconds (5 minutes)
```

## Testing Configuration

### Validate Service Dependencies

```python
from app.services.dependency_graph import get_dependency_graph

# Load graph
graph = get_dependency_graph()

# Check dependencies
print(graph.get_upstream_dependencies("payment-service"))
# Output: ['database', 'redis', 'payment-gateway']

print(graph.is_upstream_of("database", "payment-service"))
# Output: True

print(graph.calculate_dependency_boost("api-gateway", "database"))
# Output: 0.15 (direct dependency boost)
```

### Validate Runbooks

```python
from app.services.runbook_registry import get_runbook_registry

# Load runbooks
registry = get_runbook_registry()

# Get runbook for category
runbook = registry.get_runbook_for_category("memory_leak")
print(runbook.name)
# Output: "Memory Leak - Pod Restart"

# Check allowed actions
actions = registry.get_allowed_actions("cpu_spike")
for action in actions:
    print(f"{action.action_type}: {action.description}")
# Output: scale_up: Scale up replicas to handle CPU load

# Verify action is allowed
is_allowed = registry.is_action_allowed(
    action_type=ActionType.RESTART_POD,
    category="memory_leak",
)
print(is_allowed)
# Output: True
```

## Troubleshooting

### Configuration Not Loading

**Symptom**: "Dependency config not found" or "Runbooks config not found" warnings

**Solution**:
1. Check file paths in environment variables
2. Ensure YAML/JSON syntax is valid
3. Check file permissions
4. Look for example configs created automatically

### Invalid Dependencies

**Symptom**: Circular dependencies or undefined services

**Solution**:
1. Draw dependency graph on paper first
2. Ensure no service depends on itself
3. Verify all referenced services are defined
4. Check for typos in service names

### Runbook Not Matching

**Symptom**: Actions not being recommended for incidents

**Solution**:
1. Verify `category` in runbook matches hypothesis category
2. Check if service-specific runbook is too restrictive
3. Ensure action type exists in ActionType enum
4. Review logs for "No runbook found" warnings

## Further Reading

- [IMPROVEMENTS.md](./IMPROVEMENTS.md) - Detailed architectural improvements
- [README.md](./README.md) - Overall system documentation
- Code comments in:
  - `app/services/dependency_graph.py`
  - `app/services/runbook_registry.py`
  - `app/core/execution/verification.py`
