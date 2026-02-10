# Phase 3: Production-Grade Enhancements

This document provides a quick reference for the Phase 3 production-grade enhancements added to AIRRA.

## Overview

Phase 3 adds production-grade decision making capabilities that go beyond the foundational P0-P2 improvements. These enhancements focus on impact-aware decision making, risk management, and continuous learning.

## Enhancement Summary

| # | Feature | Tier | Status | Module |
|---|---------|------|--------|--------|
| 1 | Blast-Radius Awareness | Tier-1 | ✅ Complete | `blast_radius.py` |
| 2 | Risk-Weighted Actions | Tier-1 | ✅ Complete | `risk_weighted_actions.py` |
| 3 | Before-After Comparison | Tier-1 | ✅ Complete | `verification.py` (enhanced) |
| 4 | Confidence Tracking | Tier-1 | ✅ Complete | `confidence_tracker.py` |
| 5 | What-If Simulation | Tier-2 | ✅ Complete | `what_if_simulator.py` |
| 6 | Operator Feedback | Tier-2 | ✅ Complete | `operator_feedback.py` |

## 1. Blast-Radius Awareness

### Purpose
Understand incident impact scope to make appropriate decisions. Small blast → wait and observe. Large blast → act aggressively.

### What It Does
- Calculates downstream service count from dependency graph
- Measures request volume (QPS) via Prometheus
- Determines error propagation percentage
- Estimates user impact and revenue cost
- Assigns urgency multiplier (1.0x - 5.0x)

### Blast Levels
- **MINIMAL** (score <0.2): Single service, low traffic → wait
- **LOW** (0.2-0.4): Few downstream services → monitor
- **MEDIUM** (0.4-0.6): Multiple services → prepare to act
- **HIGH** (0.6-0.8): Critical services → act with confidence
- **CRITICAL** (≥0.8): Cascading failure → act immediately

### Formula
```
blast_score = (downstream/10 × 0.30) +
              (volume/100 × 0.25) +
              (propagation × 0.25) +
              (criticality × 0.20)
```

### Example
```python
from app.core.decision.blast_radius import get_blast_radius_calculator

calculator = get_blast_radius_calculator(prometheus_client)
assessment = await calculator.calculate_blast_radius("payment-service")

print(f"Blast Level: {assessment.level}")  # HIGH
print(f"Affected Services: {assessment.affected_services_count}")  # 8
print(f"Users Impacted: {assessment.estimated_users_impacted}")  # 5000
print(f"Revenue Impact: ${assessment.revenue_impact_per_hour:.2f}/hr")  # $250/hr
print(f"Urgency: {assessment.urgency_multiplier}x")  # 3.5x
```

### Decision Logic
```python
should_act, reasoning = calculator.should_act_immediately(assessment, confidence=0.75)
# CRITICAL blast → act immediately regardless of confidence
# HIGH blast + high confidence → act immediately
# MEDIUM blast + high confidence → act soon
# LOW/MINIMAL blast → wait and observe
```

## 2. Risk-Weighted Action Selection

### Purpose
Not all actions are equal. Select the lowest risk action that can fix the problem.

### Risk Profiles
Each action type has:
- Risk score (0.0-1.0): Probability of making things worse
- Expected downtime (seconds)
- Worst-case downtime (seconds)
- Recovery time if failed (seconds)
- Reversibility (true/false)
- Blast radius impact (pod, deployment, cluster)
- Cost per minute ($/min)
- Prerequisites
- Side effects

### Risk Rankings (Lowest to Highest)
1. **Scale Up** (0.05): Very low risk, no downtime, easily reversible
2. **Clear Cache** (0.10): Low risk, temporary impact
3. **Toggle Feature Flag** (0.20): Low-medium risk, reversible
4. **Scale Down** (0.25): Medium risk, reduces capacity
5. **Restart Pod** (0.35): Medium-high risk, brief downtime
6. **Rollback Deployment** (0.50): High risk, significant impact
7. **Drain Node** (0.60): High risk, affects multiple services

### Selection Process
```python
from app.core.decision.risk_weighted_actions import get_action_risk_registry

registry = get_action_risk_registry()

# Rank actions by adjusted risk
ranked = registry.rank_actions_by_risk(
    action_types=[ActionType.RESTART_POD, ActionType.SCALE_UP],
    service_criticality="high",
    current_downtime_seconds=300,
)

# Select best action
best_action, reasoning = registry.select_best_action(
    candidate_actions=[ActionType.RESTART_POD, ActionType.SCALE_UP],
    service_criticality="high",
    blast_radius_multiplier=2.5,
    min_confidence=0.6,
)

print(reasoning)
# "Selected scale_up (risk: 0.04, expected cost: $15.00, worst case: $75.00)"
```

### Cost Calculation
```python
# Expected cost = expected_downtime × cost_per_minute × blast_multiplier
expected = registry.calculate_expected_cost(ActionType.RESTART_POD, blast_multiplier=2.0)
worst = registry.calculate_worst_case_cost(ActionType.RESTART_POD, blast_multiplier=2.0)

print(f"Expected: ${expected:.2f}")  # $200
print(f"Worst Case: ${worst:.2f}")  # $600
```

## 3. Before-After Metrics Comparison

### Purpose
Examiner-proof evidence that actions worked.

### Enhanced Verification
Previously: Verification calculated improvement percentages.
Now: Also shows detailed before-after comparison with deltas.

### Report Format
```
Post-action verification: success

=== Before-After Metrics Comparison ===

Error Rate:
  Before: 12.50 errors/min
  After:  1.20 errors/min
  Δ = -11.30 errors/min (-90.4%)

Latency P95:
  Before: 850.0ms
  After:  120.0ms
  Δ = -730.0ms (-85.9%)

Latency P99:
  Before: 1200.0ms
  After:  180.0ms
  Δ = -1020.0ms (-85.0%)

Availability:
  Before: 95.00%
  After:  99.50%
  Δ = +4.50% (+4.7%)

========================================

Overall improvement: +85.3%
```

### Verification Outcomes
- **SUCCESS**: ≥20% improvement → continue monitoring
- **PARTIAL_SUCCESS**: 10-20% improvement → keep watching
- **NO_CHANGE**: No improvement → escalate to human
- **DEGRADED**: Metrics worse → rollback immediately
- **UNSTABLE**: Fluctuating → escalate to human

### Usage
```python
from app.core.execution.verification import PostActionVerifier

verifier = PostActionVerifier(prometheus_client)
result = await verifier.verify_action(
    service_name="payment-service",
    execution_result=execution_result,
    before_metrics=before_metrics,
)

print(result.status)  # VerificationStatus.SUCCESS
print(result.message)  # Detailed before-after report
print(result.recommendation)  # "continue", "rollback", "escalate"
```

## 4. Confidence vs Outcome Tracking

### Purpose
Prove the confidence model is calibrated. Show: "70% confidence → 70% success rate"

### What Gets Tracked
Every action execution records:
- Confidence score when action was taken
- Whether the action succeeded (from verification)
- Outcome status (success, partial, no_change, degraded)
- Before-after metrics
- Time to resolution
- Hypothesis category
- Risk level and blast radius

### Calibration Analysis
Groups outcomes by confidence bins and calculates:
- **Expected Calibration Error (ECE)**: Weighted average of |predicted - actual|
- **Overall accuracy**: Total success rate
- **Success rate by confidence range**: 0-10%, 10-20%, ..., 90-100%
- **Performance by category**: memory_leak, cpu_spike, etc.

### Example Report
```
============================================================
CONFIDENCE CALIBRATION REPORT
============================================================

Total Records: 150
Overall Accuracy: 76.0%
Expected Calibration Error (ECE): 0.087
(Lower ECE = better calibrated. Perfect calibration = 0.0)

------------------------------------------------------------
CALIBRATION BY CONFIDENCE BIN:
------------------------------------------------------------
    Range        Predicted      Actual       Samples    Error
------------------------------------------------------------
   0.5-0.6         55.0%         52.0%          25       0.030
   0.6-0.7         65.0%         68.0%          32       0.030
   0.7-0.8         75.0%         78.0%          45       0.030
   0.8-0.9         85.0%         82.0%          38       0.030
   0.9-1.0         95.0%         92.0%          10       0.030

------------------------------------------------------------
PERFORMANCE BY CATEGORY:
------------------------------------------------------------
     Category        Count     Success    Avg Conf   Avg MTTR
------------------------------------------------------------
   memory_leak         42        73.8%      0.72       8.5m
     cpu_spike         35        80.0%      0.78       5.2m
   error_spike         28        85.7%      0.82       4.1m
 database_issue        25        68.0%      0.65      12.3m
```

### Usage
```python
from app.services.confidence_tracker import get_confidence_tracker

tracker = get_confidence_tracker()

# Record outcome after verification
record = ConfidenceOutcomeRecord(
    timestamp=datetime.utcnow(),
    incident_id="inc-123",
    service_name="payment-service",
    hypothesis_category="memory_leak",
    hypothesis_description="Memory leak causing OOM",
    confidence_score=0.85,
    action_type=ActionType.RESTART_POD,
    action_executed=True,
    outcome_success=True,
    outcome_status="success",
    verification_metrics=before_after_metrics,
    time_to_resolution_seconds=120,
)
tracker.record_outcome(record)

# Generate calibration report
report = tracker.generate_calibration_report()
print(report)
```

## 5. What-If Simulation (Optional)

### Purpose
Compare multiple candidate actions before executing. Useful for high-risk scenarios.

### What It Simulates
For each candidate action, predicts:
- Success probability (from historical data)
- Expected improvement percentage
- Expected downtime and recovery time
- Expected cost and worst-case cost
- Blast radius impact
- Prerequisites met/missing
- Potential side effects
- Recommendation with reasoning

### When To Use
- High-risk scenarios (worst-case cost >$10k)
- Critical services
- Uncertain situations (multiple viable actions)
- Operator training
- Policy development

### Example Report
```
======================================================================
WHAT-IF SIMULATION: ACTION COMPARISON
======================================================================

Service: payment-service
Incident: memory_leak
Blast Radius: HIGH (8 services, 5000 users)

----------------------------------------------------------------------
SIMULATED ACTIONS:
----------------------------------------------------------------------

1. SCALE UP
   Status: ✓ RECOMMENDED
   Success Probability: 85%
   Expected Improvement: 24.0%
   Expected Downtime: 0s (worst: 30s)
   Expected Cost: $0.00 (worst: $50.00)
   Risk Score: 0.05
   Blast Radius: deployment
   Side Effects:
     - Increased resource usage
     - Higher infrastructure cost
   Reasoning: Recommended: Success probability: 85%, Risk: 0.05, Expected cost: $0.00, Reversible, No expected downtime

2. RESTART POD
   Status: ✓ RECOMMENDED
   Success Probability: 70%
   Expected Improvement: 49.0%
   Expected Downtime: 10s (worst: 300s)
   Expected Cost: $200.00 (worst: $600.00)
   Risk Score: 0.35
   Blast Radius: single_pod
   Side Effects:
     - Connection termination
     - In-flight request loss
     - Cache cold start
   ⚠ Prerequisites Missing:
     - Check: Multiple replicas available
   Reasoning: Not recommended: Prerequisites not met. Check: Multiple replicas available, Service has health checks

======================================================================
BEST ACTION: SCALE_UP
Reasoning: Recommended: Success probability: 85%, Risk: 0.05, Expected cost: $0.00, Reversible, No expected downtime
======================================================================
```

### Usage
```python
from app.core.simulation.what_if_simulator import get_what_if_simulator

simulator = get_what_if_simulator()

comparison = await simulator.simulate_actions(
    service_name="payment-service",
    incident_category="memory_leak",
    candidate_actions=[
        ActionType.SCALE_UP,
        ActionType.RESTART_POD,
        ActionType.ROLLBACK_DEPLOYMENT,
    ],
    current_metrics=current_metrics,
    blast_radius=blast_assessment,
    service_criticality="high",
)

# Generate comparison report
report = simulator.generate_comparison_report(comparison)
print(report)

# Get best action
if comparison.best_action:
    print(f"Best: {comparison.best_action.value}")
    print(f"Reasoning: {comparison.best_action_reasoning}")
```

## 6. Operator Feedback Loop (Optional)

### Purpose
AIRRA will make mistakes. Allow operators to provide corrections for continuous improvement.

### Feedback Types
- `HYPOTHESIS_INCORRECT`: Wrong root cause (provide correct one)
- `HYPOTHESIS_CORRECT`: Confirmed correct
- `ACTION_INAPPROPRIATE`: Wrong action chosen (provide better one)
- `ACTION_SUCCESSFUL`: Action worked well
- `INCIDENT_RESOLVED`: Incident resolved
- `INCIDENT_ESCALATED`: Required human intervention
- `GENERAL_COMMENT`: Free-form feedback

### What Gets Captured
- What AIRRA decided (hypothesis, confidence, action)
- Operator corrections (correct hypothesis, correct action)
- Incident outcome (resolved, escalated, self-healed)
- Time to resolution
- Operator name and notes
- Tags for analysis

### Analysis Provided
- **Hypothesis accuracy**: % of hypotheses marked correct
- **Action success rate**: % of actions marked successful
- **Common mistakes**: Most frequent incorrect hypotheses
- **Improvement suggestions**: Data-driven recommendations
- **Category performance**: Success rate per category

### Example Report
```
============================================================
OPERATOR FEEDBACK REPORT
============================================================

Time Period: 30 days
Date Range: 2025-12-01 to 2025-12-31
Total Feedback: 87

------------------------------------------------------------
FEEDBACK BY TYPE:
------------------------------------------------------------
  hypothesis_correct                       32
  action_successful                        28
  hypothesis_incorrect                     15
  incident_resolved                        12

------------------------------------------------------------
ACCURACY METRICS:
------------------------------------------------------------
  Hypothesis Accuracy: 68.1%
  Action Success Rate: 73.7%

------------------------------------------------------------
COMMON MISTAKES:
------------------------------------------------------------
  AIRRA: 'memory_leak' → Actually: 'cpu_spike' (8 times)
  AIRRA: 'database_issue' → Actually: 'network_issue' (5 times)
  AIRRA: 'cpu_spike' → Actually: 'memory_leak' (2 times)

------------------------------------------------------------
IMPROVEMENT SUGGESTIONS:
------------------------------------------------------------
  • Hypothesis accuracy is low (68.1%). Review confidence formula and dependency boost weights.
  • Most common mistake: Saying 'memory_leak' when it's actually 'cpu_spike' (8 times). Add detection logic.

============================================================
```

### Usage
```python
from app.services.operator_feedback import (
    get_operator_feedback_collector,
    OperatorFeedback,
    FeedbackType,
)

collector = get_operator_feedback_collector()

# Record feedback when operator corrects AIRRA
feedback = OperatorFeedback(
    feedback_id="fb-123",
    timestamp=datetime.utcnow(),
    incident_id="inc-123",
    service_name="payment-service",
    operator_name="alice",
    feedback_type=FeedbackType.HYPOTHESIS_INCORRECT,
    feedback_text="AIRRA said memory leak but it was actually a CPU spike from increased traffic",
    airra_hypothesis_category="memory_leak",
    airra_hypothesis_description="Memory usage steadily increasing",
    airra_confidence=0.85,
    airra_action_type=ActionType.RESTART_POD,
    correct_hypothesis_category="cpu_spike",
    correct_hypothesis_description="CPU spike from traffic surge",
    correct_action_type=ActionType.SCALE_UP,
    incident_resolved=True,
    resolution_method="manual",
    time_to_resolution_seconds=180,
    tags=["traffic_surge", "misdiagnosis"],
)
collector.record_feedback(feedback)

# Generate feedback report
report = collector.generate_feedback_report(time_period_days=30)
print(report)

# Get accuracy metrics
metrics = collector.calculate_accuracy_metrics(time_period_days=30)
print(f"Hypothesis Accuracy: {metrics.hypothesis_accuracy:.1%}")
print(f"Action Success Rate: {metrics.action_success_rate:.1%}")
```

## Integration Example

Here's how all Phase 3 components work together:

```python
from app.core.decision.blast_radius import get_blast_radius_calculator
from app.core.decision.risk_weighted_actions import get_action_risk_registry
from app.core.simulation.what_if_simulator import get_what_if_simulator
from app.core.execution.verification import PostActionVerifier
from app.services.confidence_tracker import get_confidence_tracker
from app.services.operator_feedback import get_operator_feedback_collector

# 1. Calculate blast radius
blast_calculator = get_blast_radius_calculator(prometheus_client)
blast_assessment = await blast_calculator.calculate_blast_radius("payment-service")
print(f"Blast Level: {blast_assessment.level} ({blast_assessment.urgency_multiplier}x urgency)")

# 2. Get candidate actions from runbook
candidate_actions = [ActionType.RESTART_POD, ActionType.SCALE_UP]

# 3. Rank actions by risk
risk_registry = get_action_risk_registry()
ranked_actions = risk_registry.rank_actions_by_risk(
    candidate_actions,
    service_criticality="high",
    current_downtime_seconds=180,
)

# 4. Run what-if simulation (optional, for high-risk scenarios)
if blast_assessment.level in ["HIGH", "CRITICAL"]:
    simulator = get_what_if_simulator()
    comparison = await simulator.simulate_actions(
        service_name="payment-service",
        incident_category="memory_leak",
        candidate_actions=candidate_actions,
        current_metrics=current_metrics,
        blast_radius=blast_assessment,
    )
    print(simulator.generate_comparison_report(comparison))

# 5. Select best action
best_action, reasoning = risk_registry.select_best_action(
    candidate_actions,
    service_criticality="high",
    blast_radius_multiplier=blast_assessment.urgency_multiplier,
    min_confidence=0.6,
)

# 6. Execute action (with approval if required)
execution_result = await execute_action(best_action)

# 7. Verify outcome with before-after comparison
verifier = PostActionVerifier(prometheus_client)
verification_result = await verifier.verify_action(
    service_name="payment-service",
    execution_result=execution_result,
    before_metrics=before_metrics,
)
print(verification_result.message)  # Shows detailed before-after comparison

# 8. Record confidence vs outcome for calibration
tracker = get_confidence_tracker()
tracker.record_outcome(ConfidenceOutcomeRecord(
    timestamp=datetime.utcnow(),
    incident_id="inc-123",
    service_name="payment-service",
    hypothesis_category="memory_leak",
    hypothesis_description="Memory leak causing OOM",
    confidence_score=0.85,
    action_type=best_action,
    action_executed=True,
    outcome_success=(verification_result.status == VerificationStatus.SUCCESS),
    outcome_status=verification_result.status.value,
    verification_metrics=verification_result.improvement_percentage,
    time_to_resolution_seconds=120,
    blast_radius_level=blast_assessment.level.value,
    risk_level=risk_profile.risk_category.value,
))

# 9. Collect operator feedback (when provided)
collector = get_operator_feedback_collector()
# Operator can provide feedback later if AIRRA was wrong
```

## Storage

All Phase 3 components use JSONL append-only storage:

- **Confidence Tracking**: `data/confidence_tracking.jsonl`
- **Operator Feedback**: `data/operator_feedback.jsonl`

This allows:
- Fast appends (no database required)
- Easy backup and replication
- Simple analysis with standard tools
- Audit trail of all decisions

## Reports

Generate reports to monitor system performance:

```python
# Confidence calibration report
from app.services.confidence_tracker import get_confidence_tracker
tracker = get_confidence_tracker()
print(tracker.generate_calibration_report())

# Operator feedback report
from app.services.operator_feedback import get_operator_feedback_collector
collector = get_operator_feedback_collector()
print(collector.generate_feedback_report(time_period_days=30))
```

## Next Steps

1. **Integration**: Connect Phase 3 components to main decision flow
2. **Testing**: Create unit tests for new modules
3. **Documentation**: Update API documentation
4. **Dashboards**: Build visualization for calibration and feedback
5. **Alerting**: Set up alerts when calibration degrades

## See Also

- [IMPROVEMENTS.md](./IMPROVEMENTS.md) - Complete architectural documentation
- [CONFIGURATION_GUIDE.md](./CONFIGURATION_GUIDE.md) - Configuration instructions
- [README.md](./README.md) - Overall system documentation
