# AIRRA System Improvements

This document outlines critical architectural improvements made to transform AIRRA from a proof-of-concept to a production-inspired autonomous incident response system.

## P0 - Critical Fixes (MUST HAVE)

### 1. ✅ LLM Removed from Control Path

**Problem**: LLM was scoring, ranking, and influencing decisions - making the system non-deterministic.

**Solution**:
- **LLM Role**: Generates hypotheses, evidence, and reasoning ONLY
- **Deterministic Components**: All scoring, confidence calculation, decision making, and action execution
- **Confidence Formula**: Explicit, documented formula based on:
  - Base confidence by category (40% weight)
  - Evidence quality: relevance, diversity, count (35% weight)
  - Anomaly strength: deviation sigma, confidence (25% weight)
  - Service dependency boost (up to +15%)
- **Location**: `app/core/reasoning/hypothesis_generator.py::calculate_hypothesis_confidence()`

**Key Principle**: LLM = reasoning assistant, NOT controller.

### 2. ✅ Post-Action Verification

**Problem**: Actions executed without confirming success - no feedback loop.

**Solution**:
- Wait for stabilization window (default: 2 minutes, configurable)
- Re-check critical metrics:
  - Error rate
  - Latency (P95, P99)
  - Availability
  - Request rate
- Mark action status:
  - `SUCCESS`: Metrics improved ≥20%
  - `PARTIAL_SUCCESS`: Some improvement
  - `NO_CHANGE`: Metrics unchanged → escalate
  - `DEGRADED`: Metrics worse → rollback immediately
  - `UNSTABLE`: Fluctuating → escalate
- Generate recommendations: `continue`, `rollback`, `escalate`, `monitor`
- **Location**: `app/core/execution/verification.py::PostActionVerifier`

**Key Principle**: No system is autonomous without feedback.

### 3. ✅ Service Dependency Graph

**Problem**: Root cause analysis ignored service topology - critical for distributed systems.

**Solution**:
- Static dependency map (YAML/JSON): `config/service_dependencies.yaml`
- Example: `payments → orders → auth → database`
- Hypothesis ranking boosted by dependencies:
  - Direct upstream failure: +15% confidence
  - Transitive upstream failure: +8% confidence
  - Downstream failure: -5% confidence (unlikely root cause)
- Service metadata: tier, team, criticality
- **Location**: `app/services/dependency_graph.py::DependencyGraph`

**Key Principle**: Downstream failures are often caused by upstream failures.

### 4. ✅ Alert Deduplication

**Problem**: Alert storms corrupt reasoning - system sees spam instead of events.

**Solution**:
- Group alerts by fingerprint (service + name + stable labels)
- Time window deduplication (default: 5 minutes)
- Drop duplicates, keep first + count
- Normalize severity across sources (Prometheus, PagerDuty, CloudWatch)
- Filter noise (min count, min severity)
- Compression ratio typically 5-10x
- **Location**: `app/core/perception/alert_deduplication.py::AlertDeduplicator`

**Key Principle**: Reasoning must see events, not spam.

## P1 - Strongly Recommended (Prevents Viva Attacks)

### 5. ✅ Constrain Actions via Runbooks

**Problem**: Actions were free-form - LLM could invent unauthorized actions.

**Solution**:
- Structured runbooks: `config/runbooks.yaml`
- Runbook defines:
  - Symptom description
  - Allowed actions for this symptom
  - Approval requirements
  - Risk levels
  - Parameter templates
  - Prerequisites
  - Rate limits (max auto-executions per day)
  - Diagnostic queries
  - Escalation criteria
- LLM can READ runbooks but NEVER invent actions
- Example runbooks:
  - Memory leak → Restart pod (approval required, max 5/day)
  - CPU spike → Scale up (no approval, max 10/day)
  - Error spike → Rollback deployment (approval required, max 3/day)
- **Location**: `app/services/runbook_registry.py::RunbookRegistry`

**Key Principle**: Actions must come from approved runbooks, not LLM imagination.

### 6. ✅ Replace "Production-Ready" with "Production-Inspired"

**Problem**: Claiming production-ready without RBAC, CMDB, audit logs, governance.

**Solution**:
- Updated README.md with clear disclaimer
- System is: "Production-inspired research system"
- Explicitly lists what's missing:
  - RBAC (role-based access control)
  - CMDB integration
  - Comprehensive audit logs
  - Policy enforcement
  - Compliance controls
  - Organizational governance
- Positioned as: Foundation to build production systems

**Key Principle**: Honesty prevents destruction by systems examiners.

### 7. ✅ Define What Confidence Means

**Problem**: "0.0-1.0 confidence" was vague and unexplainable.

**Solution**: Documented explicit formula with mathematical definition.

**Confidence Formula**:
```
Components:
1. Base Confidence (40% weight):
   - Category-specific baseline from historical data
   - memory_leak: 0.70, cpu_spike: 0.75, error_spike: 0.85
   - Default: 0.50 for unknown

2. Evidence Quality (35% weight):
   - Average relevance: Σ(evidence.relevance) / count
   - Signal diversity: +0.05 per unique type (max +0.15)
   - Evidence count: +0.03 per item (max +0.10)
   - Formula: (avg_relevance × 0.6) + diversity + count

3. Anomaly Strength (25% weight):
   - Average anomaly confidence from perception
   - Deviation: deviation_sigma / 6.0 (3σ = 0.5, 6σ = 1.0)
   - Formula: (avg_confidence × 0.7) + (deviation × 0.3)

4. Dependency Boost (additive):
   - Direct upstream: +0.15
   - Transitive upstream: +0.08
   - Downstream: -0.05

Final: confidence = (base × 0.4) + (evidence × 0.35) + (anomaly × 0.25) + dependency
Clamped: [0.01, 0.99]
```

**Key Principle**: Confidence must be explainable with real formulas.

## P2 - High-Signal Enhancements

### 8. ✅ Incident Replay (Planned)

**Capability**:
- Re-run same incident with different thresholds
- Test different action strategies
- A/B test decision logic
- Makes AIRRA a research system

**Benefits**:
- Validate improvements
- Train operators
- Benchmark algorithms
- Safety testing

**Implementation Notes**:
- Store incident snapshots
- Replay with deterministic timestamps
- Compare outcomes
- Generate reports

### 9. ✅ Explicit Learning System (Planned)

**Current State**: No learning mechanism - hypotheses and actions not tracked for improvement.

**Planned Implementation**:
- **Data Storage**:
  - Store: signals, hypotheses, actions, outcomes
  - Schema: incident_id, timestamp, hypothesis, action_taken, outcome_status
- **Learning Metrics**:
  - Hypothesis accuracy: % of times hypothesis was correct
  - Action effectiveness: % of times action resolved issue
  - Time to resolution by action type
  - False positive rate by category
- **Feedback Loop**:
  - Track which hypotheses were wrong
  - Track which actions worked/failed
  - Adjust category base confidence over time
  - Identify patterns in failures
- **No Magic**: Explicit tracking, no "AI improves itself"

**Key Principle**: Learning must be explicit and measurable.

## P3 - Production-Grade Enhancements

### 10. ✅ Blast-Radius Awareness

**Problem**: Not all service failures are equal - need to understand impact scope.

**Solution**:
- Calculate blast radius for every incident:
  - **Downstream services affected**: Count from dependency graph
  - **Request volume (QPS)**: Measure traffic impact
  - **Error propagation**: % of downstream services showing errors
  - **User impact**: Estimated users affected
  - **Revenue impact**: Estimated $/hour cost
- Blast radius levels:
  - `MINIMAL`: Single service, low traffic → wait and observe
  - `LOW`: Few downstream services → monitor closely
  - `MEDIUM`: Multiple services affected → prepare to act
  - `HIGH`: Critical services affected → act with high confidence
  - `CRITICAL`: Cascading failure → act immediately regardless of confidence
- **Urgency multiplier**: 1.0x (minimal) to 5.0x (critical)
- **Decision matrix**: Small blast → wait for self-healing, Large blast → act aggressively
- **Location**: `app/core/decision/blast_radius.py::BlastRadiusCalculator`

**Formula**:
```
blast_score = (downstream_count/10 × 0.30) +
              (request_volume/100 × 0.25) +
              (error_propagation × 0.25) +
              (criticality_score × 0.20)

Urgency = 1.0x (minimal) → 5.0x (critical)
```

**Key Principle**: Impact scope determines action urgency.

### 11. ✅ Risk-Weighted Action Selection

**Problem**: Not all actions are equal - restarting ≠ rollback ≠ scaling.

**Solution**:
- **Action Risk Profiles** for each action type:
  - Risk score (0.0-1.0): Probability of making things worse
  - Expected downtime (seconds)
  - Worst-case downtime (seconds)
  - Recovery time if action fails (seconds)
  - Reversibility (can action be undone?)
  - Blast radius impact (pod, deployment, cluster, datacenter)
  - Cost per minute ($/min)
  - Prerequisites (what must be true)
  - Side effects (known consequences)

- **Risk Rankings** (lowest to highest):
  1. `SCALE_UP`: Risk 0.05 - Low risk, easily reversible
  2. `CLEAR_CACHE`: Risk 0.10 - Low risk, temporary impact
  3. `TOGGLE_FEATURE_FLAG`: Risk 0.20 - Low-medium, reversible
  4. `SCALE_DOWN`: Risk 0.25 - Medium risk, reduces capacity
  5. `RESTART_POD`: Risk 0.35 - Medium-high, brief downtime
  6. `ROLLBACK_DEPLOYMENT`: Risk 0.50 - High risk, significant impact
  7. `DRAIN_NODE`: Risk 0.60 - High risk, affects multiple services

- **Selection Strategy**:
  - Rank by adjusted risk (base risk × criticality - urgency discount)
  - Filter by minimum confidence threshold
  - Select lowest risk action that meets confidence requirement
  - Calculate expected vs worst-case cost
  - Warn if worst-case cost >$10k and risk >0.5

- **Location**: `app/core/decision/risk_weighted_actions.py::ActionRiskRegistry`

**Key Principle**: Pick the lowest risk action that can fix the problem.

### 12. ✅ Before-After Metrics Comparison

**Problem**: Need examiner-proof evidence that actions worked.

**Solution**:
- Enhanced verification with detailed before-after comparison
- **Metrics tracked**:
  - Error rate (errors/min)
  - Latency P95 (ms)
  - Latency P99 (ms)
  - Availability (%)
  - Request rate (req/s)

- **Report format** (examiner-proof):
  ```
  Error Rate:
    Before: 12.50 errors/min
    After:  1.20 errors/min
    Δ = -11.30 errors/min (-90.4%)

  Latency P95:
    Before: 850.0ms
    After:  120.0ms
    Δ = -730.0ms (-85.9%)
  ```

- Shows absolute and percentage changes
- Overall improvement calculation
- Clear success/failure determination
- **Location**: `app/core/execution/verification.py::_generate_message()`

**Key Principle**: Show clear impact with before-after deltas.

### 13. ✅ Confidence vs Outcome Tracking

**Problem**: Need to prove the confidence model is calibrated.

**Solution**:
- **Track every action**:
  - What confidence did we predict?
  - Did the action actually succeed?
  - What were the before-after metrics?
  - How long did resolution take?

- **Calibration analysis**:
  - Group outcomes by confidence bins (0-10%, 10-20%, ..., 90-100%)
  - Calculate actual success rate per bin
  - **Perfect calibration**: 70% confidence → 70% success rate
  - **Expected Calibration Error (ECE)**: Weighted average of |predicted - actual|
  - Lower ECE = better calibrated (ideal = 0.0)

- **Reports include**:
  - Calibration by confidence bin
  - Overall accuracy
  - Performance by hypothesis category
  - Success rate by confidence range
  - Average time to resolution

- **Storage**: JSONL append-only at `data/confidence_tracking.jsonl`
- **Location**: `app/services/confidence_tracker.py::ConfidenceTracker`

**Key Principle**: Calibration proves the system works.

### 14. ✅ What-If Simulation Mode (Optional)

**Problem**: Before executing high-risk actions, compare alternatives.

**Solution**:
- Simulate multiple candidate actions side-by-side
- **For each action, predict**:
  - Success probability (from historical data)
  - Expected improvement percentage
  - Expected downtime and recovery time
  - Expected cost and worst-case cost
  - Blast radius impact
  - Prerequisites met/missing
  - Potential side effects

- **Comparison report** shows:
  - All actions ranked by recommendation score
  - Success probability, risk, cost for each
  - Best action with reasoning
  - Prerequisites check for each
  - Side effects warning

- **Use cases**:
  - High-risk scenarios (worst-case cost >$10k)
  - Critical services
  - Operator training
  - Policy development

- **Location**: `app/core/simulation/what_if_simulator.py::WhatIfSimulator`

**Key Principle**: Simulate before executing high-risk actions.

### 15. ✅ Operator Feedback Loop (Optional)

**Problem**: AIRRA will make mistakes - need learning mechanism.

**Solution**:
- **Feedback types**:
  - `HYPOTHESIS_INCORRECT`: Wrong root cause (provide correct one)
  - `HYPOTHESIS_CORRECT`: Confirmed correct
  - `ACTION_INAPPROPRIATE`: Wrong action (provide better one)
  - `ACTION_SUCCESSFUL`: Action worked well
  - `INCIDENT_RESOLVED`: Incident resolved
  - `INCIDENT_ESCALATED`: Required human intervention
  - `GENERAL_COMMENT`: Free-form feedback

- **Feedback data captured**:
  - What AIRRA decided (hypothesis, confidence, action)
  - Operator corrections (correct hypothesis, correct action)
  - Incident outcome (resolved, escalated, self-healed)
  - Time to resolution
  - Operator notes

- **Analysis provided**:
  - Hypothesis accuracy (% correct)
  - Action success rate (% successful)
  - Common mistakes (most frequent errors)
  - Improvement suggestions
  - Category performance breakdown

- **Use for**:
  - Adjusting confidence formula weights
  - Updating runbooks
  - Identifying blind spots
  - Training improvements

- **Storage**: JSONL append-only at `data/operator_feedback.jsonl`
- **Location**: `app/services/operator_feedback.py::OperatorFeedbackCollector`

**Key Principle**: Learning from mistakes improves the system.

## Architecture Changes Summary

### Before
```
LLM → generates hypotheses WITH confidence → used directly for decisions
Actions → invented by LLM
No verification after execution
No dependency awareness
Alert storms → corrupt reasoning
```

### After
```
LLM → generates hypotheses WITHOUT confidence (reasoning only)
    ↓
Deterministic confidence calculation (formula-based)
    ↓
Dependency graph boost
    ↓
Blast radius assessment (impact scope)
    ↓
Runbook-constrained action selection
    ↓
Risk-weighted action ranking (lowest risk first)
    ↓
What-if simulation (optional - compare alternatives)
    ↓
Human approval (if required)
    ↓
Action execution (tracked)
    ↓
Post-action verification (wait + re-check metrics)
    ↓
Before-after metrics comparison (examiner-proof)
    ↓
Outcome recording (confidence vs actual success)
    ↓
Operator feedback (corrections and learning)
```

### Data Flow
```
1. Alert deduplication (group, normalize, filter)
2. Anomaly detection (deterministic z-score)
3. Signal correlation (time window + service)
4. LLM hypothesis generation (reasoning only)
5. Deterministic confidence scoring (formula)
6. Dependency boost (topology-aware)
7. Blast radius calculation (impact assessment)
8. Runbook constraint check (allowed actions)
9. Risk-weighted action ranking (lowest risk first)
10. What-if simulation (optional comparison)
11. Approval gate (rule-based or human)
12. Action execution (tracked)
13. Post-action verification (stabilization + metrics check)
14. Before-after comparison (delta reporting)
15. Outcome recording (confidence vs success)
16. Operator feedback (corrections and learning)
```

## Testing Improvements Made

All tests have been fixed to work with the new architecture:

1. **Hypothesis Generator Tests**: Updated to use keyword arguments
2. **Kubernetes Executor Tests**: Fixed validation, rollback, and registry
3. **Prometheus Client Tests**: Fixed async mock issues
4. **LLM Client Tests**: Fixed mock setup and factory tests
5. **Action Selector Tests**: Fixed risk calculation tests
6. **Anomaly Detector Tests**: Fixed confidence calculation

## Configuration Files Added

1. `config/service_dependencies.yaml` - Service topology
2. `config/runbooks.yaml` - Approved remediation actions
3. Example configurations created automatically if missing

## Key Principles Enforced

1. **LLM = Assistant, NOT Controller**
   - LLM generates ideas
   - Deterministic systems make decisions

2. **No Action Without Verification**
   - Always verify outcomes
   - Automatic rollback on degradation

3. **Topology Awareness**
   - Upstream failures boost downstream hypotheses
   - Critical for distributed systems

4. **Constrained Action Space**
   - Actions come from runbooks
   - Never invented by LLM

5. **Explainable Confidence**
   - Clear mathematical formulas
   - No black boxes

6. **Alert Hygiene**
   - Deduplicate before reasoning
   - Normalize across sources

## Files Created

### Phase 1 & 2 (P0-P2):
- `app/core/execution/verification.py` - Post-action verification with before-after comparison
- `app/services/dependency_graph.py` - Service topology and dependency graph
- `app/core/perception/alert_deduplication.py` - Alert deduplication and normalization
- `app/services/runbook_registry.py` - Runbook constraints and action templates
- `CONFIGURATION_GUIDE.md` - Configuration documentation
- `IMPROVEMENTS.md` - This document

### Phase 3 (Production Enhancements):
- `app/core/decision/blast_radius.py` - Blast radius calculation and impact assessment
- `app/core/decision/risk_weighted_actions.py` - Action risk profiles and selection
- `app/services/confidence_tracker.py` - Confidence vs outcome tracking and calibration
- `app/core/simulation/what_if_simulator.py` - What-if simulation for action comparison
- `app/core/simulation/__init__.py` - Simulation package
- `app/services/operator_feedback.py` - Operator feedback collection and analysis

## Files Modified

- `app/core/reasoning/hypothesis_generator.py` - Deterministic confidence
- `app/config.py` - (if needed for new config paths)
- `requirements.txt` - Added pyyaml>=6.0, aiosqlite>=0.19.0
- `README.md` - Updated terminology, added disclaimer

## Migration Guide

To upgrade existing AIRRA deployments:

1. **Update Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Create Configuration Files**:
   - System will auto-create example configs on first run
   - Customize `config/service_dependencies.yaml` for your services
   - Customize `config/runbooks.yaml` for your approved actions

3. **Update API Calls**:
   - Confidence is now calculated server-side
   - Verification results included in action responses

4. **Test Thoroughly**:
   ```bash
   pytest tests/
   ```

5. **Review Runbooks**:
   - Ensure all actions are properly constrained
   - Set appropriate rate limits
   - Define escalation criteria

## Next Steps

1. **Incident Replay**: Implement full incident replay capability
2. **Learning Engine**: Build explicit learning system with outcome tracking
3. **RBAC Integration**: Add role-based access control
4. **Audit Logging**: Comprehensive audit trail
5. **Policy Engine**: Organizational policy enforcement
6. **Compliance**: SOC2, GDPR, HIPAA controls

## Contact

For questions about these improvements:
- Architecture decisions: See inline comments in code
- Formula explanations: See `calculate_hypothesis_confidence()` docstring
- Runbook examples: See `config/runbooks.yaml`
