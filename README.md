# AIRRA - Autonomous Incident Response & Reliability Agent

## 🎯 Project Overview

AIRRA is an intelligent incident management system that combines Site Reliability Engineering (SRE) best practices with modern LLM capabilities to automate incident detection, root cause analysis, and remediation.

### The Problem

Traditional incident response suffers from:
- **Alert Fatigue**: Too many false positives from single-metric alerts
- **Slow Root Cause Analysis**: Manual correlation of logs, metrics, and traces
- **Inconsistent Response**: Different operators take different actions
- **Lack of Learning**: No systematic improvement from past incidents

### The Solution

AIRRA provides:
- **Multi-Signal Correlation**: Analyzes metrics, logs, and traces together
- **LLM-Powered Analysis**: Generates hypotheses like an experienced SRE
- **Confidence-Aware Decisions**: Knows when to act vs. when to escalate
- **Human-in-the-Loop**: Safety through approval workflows
- **Continuous Learning**: Improves from feedback and outcomes

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        OBSERVABILITY LAYER                          │
│         Prometheus • Logs • Traces • Events                         │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  PERCEPTION AGENTS  │
                    │  (Anomaly Detection)│
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │   AIRRA CORE (LLM)  │
                    │   ├─ Hypothesis Gen │
                    │   ├─ Evidence Eval  │
                    │   └─ Confidence Score│
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  DECISION MODULE    │
                    │  (Action Selection) │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  APPROVAL GATE      │
                    │  (Human-in-Loop)    │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  ACTION EXECUTOR    │
                    │  (Dry-Run / Live)   │
                    └─────────────────────┘
```

## 🚀 Key Features

### 1. **Intelligent Detection**
- Statistical anomaly detection (z-score based)
- Multi-metric correlation
- Configurable sensitivity thresholds

### 2. **LLM-Powered Reasoning**
- Hypothesis-driven root cause analysis
- Chain-of-thought explanations
- Evidence-based ranking
- Support for Claude and GPT-4

### 3. **Safe Automation**
- Confidence scoring (0.0-1.0)
- Risk assessment for actions
- Human approval workflow
- Dry-run mode for testing

### 4. **Production-Ready**
- Async FastAPI backend
- PostgreSQL with proper indexing
- Structured JSON logging
- Docker deployment
- Prometheus metrics
- Comprehensive testing

## 📊 Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Backend** | Python 3.11 + FastAPI | Async API framework |
| **Database** | PostgreSQL 16 | Persistent storage |
| **Cache** | Redis 7 | Performance & queuing |
| **LLM** | Claude 3.5 Sonnet / GPT-4 | Reasoning engine |
| **Monitoring** | Prometheus + Grafana | Metrics collection |
| **ORM** | SQLAlchemy 2.0 (async) | Database abstraction |
| **Validation** | Pydantic v2 | Type safety |
| **Testing** | pytest + coverage | Quality assurance |
| **Container** | Docker + Compose | Deployment |

This project demonstrates:

### Software Engineering Excellence
- ✅ Clean Architecture (separation of concerns)
- ✅ Dependency Injection (testability)
- ✅ SOLID Principles
- ✅ Async/Await patterns
- ✅ Type hints throughout
- ✅ Comprehensive error handling

### Novel Approaches
- **Confidence-Aware Decision Making**: Differentiates between high and low confidence scenarios
- **Hypothesis-Driven Analysis**: Systematic root cause analysis vs. trial-and-error
- **LLM as SRE**: Using large language models for operational reasoning

### Production Patterns
- State machine for incident lifecycle
- Repository pattern for data access
- Service layer for business logic
- Event-driven architecture (ready for expansion)
- Structured logging for observability

## 📁 Project Structure

```
AIRRA/
├── backend/                 # Backend service
│   ├── app/
│   │   ├── core/           # Business logic
│   │   │   ├── perception/ # Anomaly detection
│   │   │   ├── reasoning/  # LLM integration
│   │   │   ├── decision/   # Action selection
│   │   │   └── execution/  # Action execution
│   │   ├── models/         # Database models
│   │   ├── schemas/        # API schemas
│   │   ├── api/            # REST endpoints
│   │   ├── services/       # External services
│   │   └── main.py         # FastAPI app
│   ├── tests/              # Test suite
│   └── Dockerfile
├── monitoring/             # Observability stack
│   └── prometheus/
├── docs/                   # Documentation
│   ├── thesis/             # Academic documentation
│   └── diagrams/           # Architecture diagrams
├── docker-compose.yml      # Full stack
└── README.md              # This file
```

## 🏃 Quick Start

### Prerequisites
- Docker & Docker Compose
- API key for Claude or OpenAI

### Setup

1. **Clone the repository:**
```bash
git clone <repository-url>
cd "Autonomous Incident Response & Reliability Agent (AIRRA)"
```

2. **Configure environment:**
```bash
cp backend/.env.example backend/.env
# Edit backend/.env and add your API key:
# AIRRA_ANTHROPIC_API_KEY=sk-ant-...
```

3. **Start the stack:**
```bash
docker-compose up -d
```

4. **Verify services:**
```bash
# Backend API
curl http://localhost:8000/health

# Prometheus
open http://localhost:9090

# API Docs
open http://localhost:8000/docs
```

### Running a Test Incident

```bash
# 1. Create an incident
curl -X POST http://localhost:8000/api/v1/incidents \
  -H "Content-Type: application/json" \
  -d '{
    "title": "High CPU usage detected",
    "description": "CPU usage spiked to 95% on payment service",
    "severity": "high",
    "affected_service": "payment-service",
    "metrics_snapshot": {"cpu_usage": 95.0}
  }'

# 2. Analyze the incident (triggers LLM)
curl -X POST http://localhost:8000/api/v1/incidents/{incident_id}/analyze

# 3. Check pending approvals
curl http://localhost:8000/api/v1/approvals/pending

# 4. Approve action
curl -X POST http://localhost:8000/api/v1/approvals/{action_id}/approve \
  -H "Content-Type: application/json" \
  -d '{"approved_by": "operator@example.com", "execution_mode": "dry_run"}'

# 5. Execute action
curl -X POST http://localhost:8000/api/v1/actions/{action_id}/execute
```

## 📚 Documentation

- [Backend README](backend/README.md) - Detailed backend documentation
- [Features Document](features.md) - Complete feature specifications
- [API Documentation](http://localhost:8000/docs) - Interactive API docs (when running)

## 🧪 Testing

```bash
# Run all tests
cd backend
poetry install
poetry run pytest

# With coverage
poetry run pytest --cov=app --cov-report=html

# View coverage report
open htmlcov/index.html
```

## 🔐 Security Considerations

### Current Implementation (MVP)
- ✅ Environment-based configuration
- ✅ No hardcoded secrets
- ✅ Dry-run mode by default
- ✅ Input validation with Pydantic
- ✅ SQL injection prevention (SQLAlchemy)

### Production Requirements
- ⚠️ Add authentication (JWT/OAuth2)
- ⚠️ Implement RBAC for approvals
- ⚠️ Use secrets manager (Vault, AWS Secrets)
- ⚠️ Enable rate limiting
- ⚠️ Add audit logging
- ⚠️ Network policies (if Kubernetes)

## 📈 Future Enhancements

### Phase 2 Features
- [ ] Log analysis integration (ELK/Loki)
- [ ] Distributed tracing (Jaeger)
- [ ] ServiceNow integration
- [ ] Slack/PagerDuty notifications
- [ ] Multi-tenancy support

### Advanced Capabilities
- [ ] ML-based anomaly detection (Prophet, Isolation Forest)
- [ ] Multi-action plan generation
- [ ] A/B testing for remediation strategies
- [ ] Runbook auto-generation
- [ ] Predictive incident detection

## 👨‍🎓 Academic Context

This project serves as a final year capstone demonstrating:

1. **System Design**: Distributed system architecture
2. **AI Integration**: Practical LLM application in operations
3. **Software Engineering**: Production-grade code quality
4. **Research**: Novel approaches to incident management
5. **Documentation**: Comprehensive technical writing

### Evaluation Criteria Addressed

- ✅ **Technical Complexity**: Multi-layer architecture with LLM integration
- ✅ **Innovation**: Confidence-aware automation, hypothesis-driven analysis
- ✅ **Code Quality**: Type-safe, tested, documented
- ✅ **Practical Value**: Solves real industry problem
- ✅ **Scalability**: Designed for production use

## 📝 License

MIT License - Academic Project

## 🤝 Contributing

As this is a final year project, external contributions are not accepted during the academic period. However, feedback and suggestions are welcome via issues.

## 📧 Contact

For academic inquiries or technical questions, please open an issue.

---

**Built with ❤️ using production-grade engineering practices**

*Demonstrating that academic projects can meet industry standards*
