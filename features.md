# AIRRA - Feature Documentation

> **Autonomous Incident Response & Reliability Agent**
> A production-grade intelligent incident management platform

---

## Table of Contents

1. [Overview](#overview)
2. [System Architecture](#system-architecture)
3. [Core Features](#core-features)
4. [AI/LLM Integration](#aillm-integration)
5. [ServiceNow Integration Architecture](#servicenow-integration-architecture)
6. [Production-Grade Capabilities](#production-grade-capabilities)

---

## Overview

AIRRA is an autonomous incident response system designed to handle production incidents with the sophistication of experienced SRE teams while maintaining safety through confidence-aware decision making and human oversight.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           OBSERVABILITY LAYER                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │   Metrics   │  │    Logs     │  │   Traces    │  │   Events/Alerts     │ │
│  │ (Prometheus)│  │ (ELK/Loki) │  │  (Jaeger)   │  │ (PagerDuty/OpsGenie)│ │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘ │
└─────────┼────────────────┼────────────────┼────────────────────┼────────────┘
          │                │                │                    │
          ▼                ▼                ▼                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        SERVICE DEPENDENCY MAP                               │
│         (Topology Context • Service Relationships • Impact Radius)          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          PERCEPTION AGENTS                                  │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐                   │
│  │  Log Analyzer │  │Metric Watcher │  │ Trace Parser  │                   │
│  └───────────────┘  └───────────────┘  └───────────────┘                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │      SIGNAL CORRELATION       │
                    │    (Multi-Signal Fusion)      │
                    └───────────────┬───────────────┘
                                    │
                          ┌─────────▼─────────┐
                          │                   │
┌─────────────────────────┴───────────────────┴─────────────────────────────┐
│                                                                            │
│                        ★ AIRRA CORE (LLM Engine) ★                      │
│                                                                            │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │                    REASONING MODULE                                 │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                 │   │
│  │  │  Hypothesis │  │  Evidence   │  │  Confidence │                 │   │
│  │  │  Generator  │  │  Evaluator  │  │  Scorer     │                 │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘                 │   │
│  └────────────────────────────────────────────────────────────────────┘   │
│                                                                            │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │                    DECISION MODULE                                  │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                 │   │
│  │  │   Action    │  │  Trade-off  │  │ Abstention  │                 │   │
│  │  │  Selector   │  │  Analyzer   │  │  Handler    │                 │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘                 │   │
│  └────────────────────────────────────────────────────────────────────┘   │
│                                                                            │
│  ◄──── Bidirectional Signal Request (can request additional signals) ────► │
│                                                                            │
└───────────────────────────────────┬───────────────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │       ACTION EXECUTOR         │
                    │   (Remediation Orchestrator)  │
                    └───────────────┬───────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │    HUMAN APPROVAL GATE        │
                    │  ┌─────────────────────────┐  │
                    │  │  ✓ Approve              │  │
                    │  │  ✗ Reject               │  │
                    │  │  ✎ Modify               │  │
                    │  │  ⏸ Escalate             │  │
                    │  └─────────────────────────┘  │
                    │  (Confidence-Based Routing)   │
                    └───────────────┬───────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │   CONTROLLED ACTION LAYER     │
                    │  ┌─────────────────────────┐  │
                    │  │ • Service Restart       │  │
                    │  │ • Rollback Deployment   │  │
                    │  │ • Scale Resources       │  │
                    │  │ • Toggle Feature Flags  │  │
                    │  │ • DNS/Traffic Shift     │  │
                    │  └─────────────────────────┘  │
                    └───────────────┬───────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │      FEEDBACK LOOP            │
                    │  (Post-Incident Learning)     │
                    └───────────────────────────────┘
```

---

## Core Features

### 1. Multi-Signal Correlation

| Attribute | Details |
|-----------|---------|
| **Priority** | High |
| **Category** | Detection & Analysis |
| **Description** | Correlates logs, metrics, traces, and events to identify incident patterns |
| **Value** | Eliminates single-metric alerting which is the #1 cause of alert fatigue. Mirrors how experienced SREs actually diagnose issues. |

### 2. Hypothesis-Driven Root Cause Analysis

| Attribute | Details |
|-----------|---------|
| **Priority** | High |
| **Category** | Analysis & Reasoning |
| **Description** | Generates and tests hypotheses systematically rather than random troubleshooting |
| **Value** | Mirrors real debugging workflows. Eliminates "guess and pray" automation. |

### 3. Confidence-Aware Decisions

| Attribute | Details |
|-----------|---------|
| **Priority** | Critical |
| **Category** | Decision Making |
| **Description** | Every action includes confidence scoring; low-confidence decisions trigger human review |
| **Value** | Separates responsible automation from dangerous automation. Essential for production trust. |

### 4. Action Trade-Off Evaluation

| Attribute | Details |
|-----------|---------|
| **Priority** | High |
| **Category** | Decision Making |
| **Description** | Evaluates restart vs rollback vs scale decisions with explicit cost/risk modeling |
| **Value** | Explicit cost/risk modeling is mature engineering. Prevents suboptimal remediation choices. |

### 5. Human-in-the-Loop

| Attribute | Details |
|-----------|---------|
| **Priority** | Critical |
| **Category** | Safety & Governance |
| **Description** | Approval gates for high-risk actions; supports approve, reject, modify, and escalate flows |
| **Value** | Non-negotiable for production systems. Also required for ML feedback loops. |

### 6. Post-Incident Learning

| Attribute | Details |
|-----------|---------|
| **Priority** | High |
| **Category** | Continuous Improvement |
| **Description** | Captures incident patterns, remediation outcomes, and operator feedback for model improvement |
| **Value** | Without memory, the system can't improve. Enables continuous refinement. |

### 7. Dry-Run Mode

| Attribute | Details |
|-----------|---------|
| **Priority** | High |
| **Category** | Testing & Validation |
| **Description** | Simulates actions without execution for testing and validation |
| **Value** | Essential for testing without production risk. Great for demos and evaluation. |

### 8. Abstention Handling

| Attribute | Details |
|-----------|---------|
| **Priority** | Critical |
| **Category** | Safety & Governance |
| **Description** | Knows when NOT to act; gracefully handles uncertainty |
| **Value** | "Knowing when NOT to act" is undervalued. Prevents cascading failures from overconfident automation. |

### 9. Explainability Engine

| Attribute | Details |
|-----------|---------|
| **Priority** | High |
| **Category** | Audit & Compliance |
| **Description** | Generates human-readable explanations for all decisions and actions |
| **Value** | Required for auditors, postmortems, and debugging. Black-box automation fails in enterprise. |

### 10. Reliability Metrics

| Attribute | Details |
|-----------|---------|
| **Priority** | High |
| **Category** | Measurement & ROI |
| **Description** | Tracks MTTR, MTTD, incident frequency, and automation success rates |
| **Value** | Proves value to stakeholders. Without metrics, you can't demonstrate improvement. |

---

## AI/LLM Integration

### What the AI/LLM Does in AIRRA

The LLM serves as the **cognitive core** of AIRRA, performing tasks that traditionally required human SRE expertise:

#### 1. Natural Language Understanding

| Capability | Implementation |
|------------|----------------|
| **Log Interpretation** | Parse unstructured logs, error messages, and stack traces |
| **Alert Contextualization** | Understand alert semantics beyond simple pattern matching |
| **Runbook Comprehension** | Read and execute human-written runbooks dynamically |

#### 2. Reasoning & Analysis

| Capability | Implementation |
|------------|----------------|
| **Causal Inference** | Determine root cause from correlated signals |
| **Pattern Recognition** | Identify known incident patterns from historical data |
| **Anomaly Explanation** | Explain why a metric or behavior is anomalous |
| **Impact Assessment** | Estimate blast radius and business impact |

#### 3. Decision Making

| Capability | Implementation |
|------------|----------------|
| **Action Selection** | Choose optimal remediation from available options |
| **Risk Scoring** | Evaluate risk of each potential action |
| **Confidence Calibration** | Know when to act vs. when to escalate |
| **Trade-off Analysis** | Balance speed vs. safety in remediation choices |

#### 4. Communication

| Capability | Implementation |
|------------|----------------|
| **Incident Summaries** | Generate executive and technical summaries |
| **Stakeholder Updates** | Craft context-appropriate status updates |
| **Postmortem Drafts** | Auto-generate initial postmortem documents |
| **Runbook Suggestions** | Propose runbook improvements based on incidents |

#### 5. Continuous Learning

| Capability | Implementation |
|------------|----------------|
| **Feedback Integration** | Learn from human corrections and overrides |
| **Pattern Library** | Build and refine incident pattern recognition |
| **Confidence Tuning** | Adjust confidence thresholds based on outcomes |

---

## ServiceNow Integration Architecture

### Design Philosophy

> **AIRRA augments ServiceNow — it does not replace it.**
>
> AIRRA produces structured incident candidates and enrichment data. ServiceNow remains the system of record for tickets, workflows, and approvals.

### Responsibility Boundary

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        RESPONSIBILITY MATRIX                                │
├─────────────────────────────────┬───────────────────────────────────────────┤
│           AIRRA OWNS            │           SERVICENOW OWNS                 │
├─────────────────────────────────┼───────────────────────────────────────────┤
│ • Signal ingestion & correlation│ • Ticket lifecycle management             │
│ • Hypothesis generation         │ • Workflow orchestration                  │
│ • Confidence scoring            │ • Approval chains                         │
│ • Root cause analysis           │ • SLA tracking & escalations              │
│ • Action recommendations        │ • Change request management               │
│ • Runbook ID mapping            │ • CMDB (source of truth)                  │
│ • Postmortem artifact generation│ • Knowledge base storage                  │
│ • Learning & pattern refinement │ • Audit & compliance records              │
└─────────────────────────────────┴───────────────────────────────────────────┘
```

### Integration Flow

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                    AIRRA ↔ SERVICENOW INTEGRATION FLOW                       │
└──────────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────┐
  │  OBSERVABILITY  │    Events, Metrics, Logs, Traces
  │     LAYER       │
  └────────┬────────┘
           │
           ▼
  ┌─────────────────┐
  │   PERCEPTION    │    Signal Analysis
  │     AGENTS      │
  └────────┬────────┘
           │
           ▼
  ┌─────────────────┐
  │   AIRRA CORE    │    Hypothesis Generation
  │   (LLM Engine)  │    Confidence Scoring
  └────────┬────────┘
           │
           ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │                    INCIDENT CANDIDATE OUTPUT                     │
  │  ┌─────────────────────────────────────────────────────────────┐ │
  │  │ {                                                           │ │
  │  │   "incident_id": "AIRRA-2024-001234",                       │ │
  │  │   "hypotheses": [                                           │ │
  │  │     { "description": "Memory leak in payment-service",      │ │
  │  │       "confidence": 0.87,                                   │ │
  │  │       "evidence": ["heap_growth_rate", "gc_pressure"] }     │ │
  │  │   ],                                                        │ │
  │  │   "suggested_actions": [                                    │ │
  │  │     { "action": "restart_pod",                              │ │
  │  │       "target": "payment-service-7d4f8b",                   │ │
  │  │       "risk_score": 0.2,                                    │ │
  │  │       "runbook_id": "RB-SVC-001" }                          │ │
  │  │   ],                                                        │ │
  │  │   "affected_cis": ["payment-service", "checkout-api"],      │ │
  │  │   "blast_radius": "medium",                                 │ │
  │  │   "priority_suggestion": "P2"                               │ │
  │  │ }                                                           │ │
  │  └─────────────────────────────────────────────────────────────┘ │
  └──────────────────────────────┬──────────────────────────────────┘
                                 │
                                 ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │                     SERVICENOW INTEGRATION                       │
  │                                                                  │
  │   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
  │   │   Incident   │    │    Change    │    │   Knowledge  │      │
  │   │    Table     │    │   Request    │    │     Base     │      │
  │   │  (Enriched)  │    │  (If action) │    │  (Postmortem)│      │
  │   └──────────────┘    └──────────────┘    └──────────────┘      │
  │                                                                  │
  │   ServiceNow Workflow Engine handles approvals & execution       │
  └─────────────────────────────────────────────────────────────────┘
```

### 1. Ticket Enrichment Schema

When AIRRA detects an incident, it enriches ServiceNow tickets with structured data:

| ServiceNow Field | AIRRA Provides | Example |
|------------------|----------------|---------|
| **Work Notes** | Ranked hypotheses with evidence | "Hypothesis 1 (87% confidence): Memory leak detected..." |
| **Priority** | Priority suggestion based on impact | P2 (suggested), final set by workflow |
| **Affected CIs** | Configuration items from dependency analysis | `payment-service`, `checkout-api` |
| **Related KB Articles** | Runbook ID pointers | `KB0012345`, `RB-SVC-001` |
| **Custom Fields** | Confidence score, blast radius | `airra_confidence: 0.87`, `blast_radius: medium` |
| **Related Tasks** | Suggested remediation actions | "Restart payment-service pod" |

### 2. Runbook Mapping

AIRRA maintains a runbook registry that maps to ServiceNow Knowledge Base articles:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         RUNBOOK MAPPING LAYER                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   AIRRA Runbook Registry              ServiceNow KB                         │
│   ┌─────────────────────┐             ┌─────────────────────┐               │
│   │ runbook_id: RB-001  │ ──────────► │ KB Article: KB00123 │               │
│   │ name: "Pod Restart" │             │ Workflow: WF-RESTART│               │
│   │ actions:            │             │ Approval: L1-AUTO   │               │
│   │   - restart_pod     │             └─────────────────────┘               │
│   │   - verify_health   │                                                   │
│   │ risk_level: low     │                                                   │
│   └─────────────────────┘                                                   │
│                                                                             │
│   Key Behaviors:                                                            │
│   • AIRRA suggests actions from mapped runbooks only (allow-list)           │
│   • Execution defers to ServiceNow workflow approval chains                 │
│   • Unknown/unmapped actions → escalate to human, never auto-execute        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Runbook Registry Schema:**

```json
{
  "runbook_id": "RB-SVC-001",
  "name": "Service Pod Restart",
  "servicenow_kb_id": "KB0012345",
  "servicenow_workflow_id": "WF-POD-RESTART",
  "allowed_actions": [
    "restart_pod",
    "scale_replicas",
    "drain_node"
  ],
  "approval_level": "L1_AUTO | L2_ONCALL | L3_MANAGER",
  "risk_tier": "low | medium | high | critical",
  "preconditions": [
    "replica_count >= 2",
    "no_active_deployment"
  ]
}
```

### 3. CMDB-Aware Reasoning

AIRRA uses topology context to rank hypotheses and assess blast radius:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    DEPENDENCY GRAPH OPTIONS                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   OPTION A: Local Static Graph (Default MVP)                                │
│   ┌─────────────────────────────────────────────────────────────────┐       │
│   │  • YAML/JSON file defining service relationships                │       │
│   │  • Version-controlled alongside AIRRA config                    │       │
│   │  • Manual updates when architecture changes                     │       │
│   │  • Best for: Small teams, stable architectures                  │       │
│   └─────────────────────────────────────────────────────────────────┘       │
│                                                                             │
│   OPTION B: Periodic CMDB Sync (ServiceNow Integration)                     │
│   ┌─────────────────────────────────────────────────────────────────┐       │
│   │  • Scheduled sync via ServiceNow CMDB API                       │       │
│   │  • Pulls CI relationships, dependencies, ownership              │       │
│   │  • Configurable sync interval (default: 1 hour)                 │       │
│   │  • Best for: Enterprises with mature CMDB practices             │       │
│   └─────────────────────────────────────────────────────────────────┘       │
│                                                                             │
│   OPTION C: Cloud CMDB Adapter (Pluggable)                                  │
│   ┌─────────────────────────────────────────────────────────────────┐       │
│   │  • Adapter interface for cloud-native discovery                 │       │
│   │  • Implementations:                                             │       │
│   │    - AWS: Config, Resource Groups, Service Map                  │       │
│   │    - Azure: Resource Graph, Application Insights Map            │       │
│   │    - GCP: Asset Inventory, Service Directory                    │       │
│   │    - K8s: Native service discovery, Istio service mesh          │       │
│   │  • Best for: Cloud-native, dynamic environments                 │       │
│   └─────────────────────────────────────────────────────────────────┘       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Adapter Interface:**

```python
class CMDBAdapter(Protocol):
    """Pluggable CMDB adapter interface"""

    def get_service_dependencies(self, service_id: str) -> List[Dependency]:
        """Returns upstream and downstream dependencies"""
        ...

    def get_blast_radius(self, service_id: str) -> BlastRadius:
        """Calculates affected services if this service fails"""
        ...

    def get_service_metadata(self, service_id: str) -> ServiceMetadata:
        """Returns ownership, tier, SLA requirements"""
        ...

    def sync(self) -> SyncResult:
        """Performs full or incremental sync"""
        ...
```

**Topology-Aware Hypothesis Ranking:**

| Factor | Weight | Example |
|--------|--------|---------|
| **Dependency Depth** | High | Root cause likely in upstream service |
| **Blast Radius** | High | Issues in critical path services ranked higher |
| **Service Tier** | Medium | Tier-1 services get priority attention |
| **Historical Patterns** | Medium | Services with past incidents weighted |
| **Change Proximity** | High | Recently deployed services suspected first |

### 4. Feedback Loop & Learning

After incident resolution (automated or manual), AIRRA captures outcomes:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         FEEDBACK LOOP ARCHITECTURE                          │
└─────────────────────────────────────────────────────────────────────────────┘

  Incident Resolution
         │
         ▼
  ┌─────────────────┐
  │  OUTCOME        │    Was the hypothesis correct?
  │  CAPTURE        │    Did the action resolve the issue?
  └────────┬────────┘    How long did resolution take?
           │
           ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │                 STRUCTURED POSTMORTEM ARTIFACT                   │
  │  ┌─────────────────────────────────────────────────────────────┐ │
  │  │ {                                                           │ │
  │  │   "incident_ref": "INC0012345",                             │ │
  │  │   "airra_candidate_id": "AIRRA-2024-001234",                │ │
  │  │   "outcome": {                                              │ │
  │  │     "hypothesis_correct": true,                             │ │
  │  │     "action_effective": true,                               │ │
  │  │     "time_to_resolution_mins": 12,                          │ │
  │  │     "human_override": false,                                │ │
  │  │     "override_reason": null                                 │ │
  │  │   },                                                        │ │
  │  │   "learnings": {                                            │ │
  │  │     "pattern_id": "PAT-MEMLEAK-001",                        │ │
  │  │     "confidence_delta": +0.05,                              │ │
  │  │     "new_evidence_signals": ["jvm_old_gen_pct"]             │ │
  │  │   },                                                        │ │
  │  │   "runbook_feedback": {                                     │ │
  │  │     "runbook_id": "RB-SVC-001",                             │ │
  │  │     "steps_followed": ["restart_pod", "verify_health"],     │ │
  │  │     "suggested_improvements": null                          │ │
  │  │   }                                                         │ │
  │  │ }                                                           │ │
  │  └─────────────────────────────────────────────────────────────┘ │
  └──────────────────────────────┬──────────────────────────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
  │   ServiceNow    │ │   AIRRA         │ │   ServiceNow    │
  │   Ticket        │ │   Pattern       │ │   Knowledge     │
  │   (Work Notes)  │ │   Library       │ │   Base          │
  └─────────────────┘ └─────────────────┘ └─────────────────┘
        │                    │                    │
        │                    ▼                    │
        │           ┌─────────────────┐           │
        │           │  Model Learning │           │
        │           │  • Confidence   │           │
        │           │    calibration  │           │
        │           │  • Pattern      │           │
        │           │    refinement   │           │
        │           └─────────────────┘           │
        │                                         │
        └─────────────────────────────────────────┘
                 Audit Trail & Compliance
```

**What Gets Written Back:**

| Destination | Artifact | Purpose |
|-------------|----------|---------|
| **ServiceNow Ticket** | Resolution summary, actions taken | Audit trail, SLA compliance |
| **ServiceNow KB** | Postmortem document (draft) | Team knowledge sharing |
| **AIRRA Pattern Library** | Incident signature + outcome | Model learning & confidence tuning |
| **AIRRA Runbook Registry** | Runbook effectiveness score | Runbook improvement suggestions |

---

## Production-Grade Capabilities

### ServiceNow-Level Enterprise Features

To achieve production-grade status comparable to ServiceNow, AIRRA implements:

#### 1. ITSM Integration

```
┌─────────────────────────────────────────────────────────────┐
│                    ITSM INTEGRATION LAYER                   │
├─────────────────────────────────────────────────────────────┤
│  • Incident Ticket Enrichment (hypotheses, confidence)      │
│  • Change Request Suggestions for Remediations              │
│  • CMDB Synchronization for Service Dependencies            │
│  • Defers to ServiceNow for Approvals & Workflows           │
│  • Audit Trail for Compliance (SOC2, HIPAA, PCI-DSS)        │
└─────────────────────────────────────────────────────────────┘
```

#### 2. Workflow Automation

| Feature | Description |
|---------|-------------|
| **Approval Workflows** | Multi-level approval chains based on action risk |
| **Escalation Policies** | Time-based and severity-based escalation rules |
| **On-Call Integration** | PagerDuty/OpsGenie integration for human routing |
| **SLA Management** | Track response and resolution time commitments |

#### 3. Knowledge Management

| Feature | Description |
|---------|-------------|
| **Incident Knowledge Base** | Searchable repository of past incidents |
| **Runbook Library** | Version-controlled remediation procedures |
| **Pattern Catalog** | Documented incident patterns with resolutions |
| **AI-Assisted Search** | Semantic search across all knowledge artifacts |

#### 4. Enterprise Security

| Feature | Description |
|---------|-------------|
| **RBAC** | Role-based access control for actions and data |
| **SSO/SAML** | Enterprise identity provider integration |
| **Audit Logging** | Immutable logs of all system actions |
| **Secrets Management** | Vault integration for credential handling |
| **Data Encryption** | At-rest and in-transit encryption |

#### 5. Multi-Tenancy & Scale

| Feature | Description |
|---------|-------------|
| **Tenant Isolation** | Logical separation of customer environments |
| **Rate Limiting** | Prevent runaway automation |
| **Horizontal Scaling** | Handle enterprise incident volumes |
| **High Availability** | Active-active deployment support |

#### 6. Observability (Self-Monitoring)

| Feature | Description |
|---------|-------------|
| **Health Dashboards** | Real-time system health visibility |
| **Performance Metrics** | LLM latency, decision accuracy, action success rates |
| **Cost Tracking** | LLM token usage and cloud resource costs |
| **Alerting on Self** | AIRRA monitors its own health |

---

## Architecture Improvements Implemented

### 1. Human Approval Gate
Added between Action Executor and Controlled Action Layer to ensure human oversight for critical actions.

### 2. Bidirectional Signal Request
AIRRA CORE can now request additional signals from Perception Agents during hypothesis testing for deeper investigation.

### 3. Service Dependency Map
Positioned between Observability Layer and Perception Agents to enrich signals with topology context, enabling accurate blast radius assessment.

### 4. ServiceNow Integration Architecture
Comprehensive integration layer that positions AIRRA as an augmentation to ServiceNow rather than a replacement:
- **Ticket Enrichment**: AIRRA provides hypotheses, confidence scores, and runbook pointers
- **Runbook Mapping**: Allow-list based action suggestions with deference to ServiceNow workflows
- **CMDB-Aware Reasoning**: Pluggable adapters for topology context (static, ServiceNow sync, cloud-native)
- **Feedback Loop**: Structured postmortem artifacts written back to tickets and KB for continuous learning

---

## Summary

AIRRA combines the cognitive capabilities of modern LLMs with the operational rigor required for production incident management. The system is designed to **augment—not replace**—both human operators and existing ITSM platforms like ServiceNow, providing intelligent automation while maintaining safety through confidence-aware decisions and human oversight.

**Key Differentiators:**
- **Cognitive Automation**: LLM-powered reasoning, not just rule-based scripts
- **Safety First**: Confidence scoring, abstention handling, human-in-the-loop
- **ServiceNow Native**: Enriches tickets, maps runbooks, defers to existing workflows
- **CMDB-Aware**: Topology-aware hypothesis ranking with pluggable adapters
- **Continuously Learning**: Feedback loops that write structured artifacts back to KB
