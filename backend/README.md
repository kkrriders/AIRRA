# AIRRA Backend

**Autonomous Incident Response & Reliability Agent** - Production-inspired research system for intelligent incident management.

> **Note**: This is a research and demonstration system inspired by production incident response patterns. It is NOT a complete production system. Missing: RBAC, CMDB integration, comprehensive audit logs, policy enforcement, compliance controls, and organizational governance frameworks. Use this as a foundation to build production systems tailored to your organization's requirements.

## Architecture Overview

AIRRA uses a layered architecture implementing the perception-reasoning-decision-execution pattern:

```
┌─────────────────────────────────────────────────────────┐
│                   REST API Layer                        │
│           (FastAPI with async endpoints)                │
└──────────────────────┬──────────────────────────────────┘
                       │
    ┌──────────────────┼──────────────────┐
    │                  │                  │
    ▼                  ▼                  ▼
┌─────────┐      ┌──────────┐      ┌──────────┐
│Perception│      │Reasoning │      │ Decision │
│  Layer   │ ───► │  Module  │ ───► │  Module  │
└─────────┘      └──────────┘      └──────────┘
    │                  │                  │
    │            LLM Integration          │
    ▼                  ▼                  ▼
┌──────────────────────────────────────────────┐
│          Human Approval Gate                 │
└──────────────┬───────────────────────────────┘
               │
               ▼
         ┌──────────┐
         │Execution │
         │  Layer   │
         └──────────┘
```

## Recent Improvements

See [IMPROVEMENTS.md](./IMPROVEMENTS.md) for detailed documentation of architectural improvements.

### Phase 1 & 2 (P0-P2: Foundation)
- **LLM Removed from Control Path**: Deterministic confidence scoring
- **Post-Action Verification**: Automatic outcome validation with rollback
- **Service Dependency Graph**: Topology-aware root cause analysis
- **Alert Deduplication**: Prevent alert storms from corrupting reasoning
- **Runbook Constraints**: Actions limited to approved runbooks
- **Explicit Confidence Formula**: Documented, explainable confidence calculation

### Phase 3 (Production-Grade Enhancements)
See [PHASE3_ENHANCEMENTS.md](./PHASE3_ENHANCEMENTS.md) for detailed documentation.

- **Blast-Radius Awareness**: Impact-based decision making (1.0x-5.0x urgency multiplier)
- **Risk-Weighted Actions**: Select lowest risk action that fixes the problem
- **Before-After Metrics**: Examiner-proof delta reporting showing impact
- **Confidence Tracking**: Prove calibration with Expected Calibration Error (ECE)
- **What-If Simulation**: Compare multiple actions before executing (optional)
- **Operator Feedback Loop**: Learn from corrections and mistakes (optional)

## Key Features

### 1. **Perception Layer** (`app/core/perception/`)
- **Anomaly Detection**: Statistical z-score based detection with configurable thresholds
- **Metrics Ingestion**: Prometheus integration for time-series data
- **Multi-Signal Correlation**: Analyzes multiple metrics simultaneously

### 2. **Reasoning Module** (`app/core/reasoning/`)
- **LLM-Powered Hypothesis Generation**: Uses Claude/GPT for root cause analysis
- **Evidence-Based Ranking**: Hypotheses ranked by confidence with supporting evidence
- **Chain-of-Thought Reasoning**: LLM provides explainable reasoning

### 3. **Decision Module** (`app/core/decision/`)
- **Action Selection**: Rule-based action recommendation with risk assessment
- **Confidence-Aware Approval**: Low confidence triggers human review
- **Risk Scoring**: Multi-factor risk calculation (action type, confidence, service tier)

### 4. **Execution Layer** (`app/core/execution/`)
- **Dry-Run Mode**: Safe testing without actual execution
- **Action Tracking**: Full audit trail of all actions
- **Rollback Support**: Action rollback capability

### 5. **Human-in-the-Loop** (`app/api/v1/approvals.py`)
- **Approval Workflow**: Human review for high-risk actions
- **Rejection Feedback**: Captures reasoning for model improvement
- **Escalation**: Routes complex cases to human operators

## Technology Stack

- **Framework**: FastAPI (async Python web framework)
- **Database**: PostgreSQL with SQLAlchemy 2.0 (async)
- **LLM Integration**: Anthropic Claude & OpenAI GPT support
- **Monitoring**: Prometheus for metrics
- **Caching**: Redis for performance
- **Testing**: pytest with async support
- **Code Quality**: black, ruff, mypy

## Getting Started

### Prerequisites

- Python 3.11+
- Poetry (dependency management)
- Docker & Docker Compose
- API key for Claude or OpenAI

### Quick Start with Docker

1. **Clone and navigate to project:**
```bash
cd "Autonomous Incident Response & Reliability Agent (AIRRA)"
```

2. **Set up environment variables:**
```bash
cp backend/.env.example backend/.env
# Edit .env and add your API key
```

3. **Start all services:**
```bash
docker-compose up -d
```

This starts:
- PostgreSQL (port 5432)
- Redis (port 6379)
- Prometheus (port 9090)
- AIRRA Backend (port 8000)

4. **Access the API:**
- API Documentation: http://localhost:8000/docs
- Health Check: http://localhost:8000/health
- Prometheus: http://localhost:9090

### Local Development Setup

1. **Install Poetry:**
```bash
curl -sSL https://install.python-poetry.org | python3 -
```

2. **Install dependencies:**
```bash
cd backend
poetry install
```

3. **Activate virtual environment:**
```bash
poetry shell
```

4. **Set up environment variables:**
```bash
cp .env.example .env
# Edit .env with your configuration
```

5. **Run database migrations:**
```bash
# For development, tables are auto-created
# For production, use Alembic:
alembic upgrade head
```

6. **Start the server:**
```bash
uvicorn app.main:app --reload
```

## API Workflow

### Complete Incident Response Flow

```
1. Create Incident (POST /api/v1/incidents)
   ↓
2. Trigger Analysis (POST /api/v1/incidents/{id}/analyze)
   ├─ Fetch metrics from Prometheus
   ├─ Detect anomalies (statistical)
   ├─ Generate hypotheses (LLM)
   ├─ Recommend action
   └─ Status: PENDING_APPROVAL
   ↓
3. Review Action (GET /api/v1/approvals/pending)
   ↓
4. Approve/Reject (POST /api/v1/approvals/{action_id}/approve)
   ↓
5. Execute Action (POST /api/v1/actions/{id}/execute)
   └─ Status: RESOLVED
```

### Example: Creating and Analyzing an Incident

```bash
# 1. Create incident
curl -X POST http://localhost:8000/api/v1/incidents \
  -H "Content-Type: application/json" \
  -d '{
    "title": "High latency in payment service",
    "description": "P95 latency increased to 2000ms",
    "severity": "high",
    "affected_service": "payment-service",
    "detected_at": "2024-01-15T10:30:00Z",
    "metrics_snapshot": {
      "latency_p95": 2000,
      "latency_p50": 500
    }
  }'

# Response: { "id": "550e8400-e29b-41d4-a716-446655440000", ... }

# 2. Trigger analysis
curl -X POST http://localhost:8000/api/v1/incidents/550e8400-e29b-41d4-a716-446655440000/analyze

# 3. Get pending approvals
curl http://localhost:8000/api/v1/approvals/pending

# 4. Approve action
curl -X POST http://localhost:8000/api/v1/approvals/{action_id}/approve \
  -H "Content-Type: application/json" \
  -d '{
    "approved_by": "john.doe@example.com",
    "execution_mode": "dry_run"
  }'

# 5. Execute action
curl -X POST http://localhost:8000/api/v1/actions/{action_id}/execute
```

## Project Structure

```
backend/
├── app/
│   ├── core/                    # Business logic
│   │   ├── perception/          # Anomaly detection
│   │   ├── reasoning/           # Hypothesis generation
│   │   ├── decision/            # Action selection
│   │   └── execution/           # Action execution
│   ├── models/                  # SQLAlchemy models
│   ├── schemas/                 # Pydantic schemas
│   ├── api/                     # FastAPI routes
│   │   └── v1/                  # API version 1
│   ├── services/                # External integrations
│   │   ├── llm_client.py        # LLM abstraction
│   │   └── prometheus_client.py # Metrics client
│   ├── config.py                # Configuration
│   ├── database.py              # Database setup
│   └── main.py                  # FastAPI app
├── tests/                       # Test suite
├── pyproject.toml               # Dependencies
└── Dockerfile                   # Container image
```

## Configuration

All configuration is via environment variables with the `AIRRA_` prefix.

### Key Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `AIRRA_LLM_PROVIDER` | `anthropic` | LLM provider (`anthropic` or `openai`) |
| `AIRRA_LLM_MODEL` | `claude-3-5-sonnet-20241022` | Model identifier |
| `AIRRA_ANOMALY_THRESHOLD_SIGMA` | `3.0` | Z-score threshold for anomalies |
| `AIRRA_CONFIDENCE_THRESHOLD_HIGH` | `0.8` | High confidence threshold |
| `AIRRA_DRY_RUN_MODE` | `true` | Enable dry-run (safe testing) |

See `.env.example` for complete list.

## Testing

```bash
# Run all tests
poetry run pytest

# Run with coverage
poetry run pytest --cov=app --cov-report=html

# Run specific test file
poetry run pytest tests/unit/test_anomaly_detector.py
```

## Code Quality

```bash
# Format code
poetry run black app tests

# Lint
poetry run ruff check app tests

# Type checking
poetry run mypy app
```

## Database Migrations

```bash
# Create new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

## Monitoring & Observability

The application exports structured JSON logs and includes:

- **Health endpoint**: `/health`
- **Metrics endpoint**: `/metrics` (Prometheus format)
- **Request tracing**: Correlation IDs in logs
- **Token usage tracking**: LLM cost monitoring

## Production Considerations

### Security
- [ ] Add authentication (JWT, OAuth2)
- [ ] Implement RBAC for approvals
- [ ] Use secrets management (Vault, AWS Secrets Manager)
- [ ] Enable rate limiting
- [ ] Add request validation and sanitization

### Scalability
- [ ] Add caching layer (Redis)
- [ ] Implement background task queue (Celery, RQ)
- [ ] Set up load balancing
- [ ] Configure connection pooling
- [ ] Add circuit breakers for external services

### Reliability
- [ ] Set up database replicas
- [ ] Implement retry logic with backoff
- [ ] Add dead letter queues
- [ ] Configure graceful shutdown
- [ ] Enable blue-green deployments

## Contributing

This is a final year project demonstrating production-grade engineering practices:

- Clean architecture with separation of concerns
- Dependency injection for testability
- Type hints throughout
- Comprehensive error handling
- Structured logging
- Async/await for performance

## License

Academic project - MIT License

## Contact

For questions or feedback, please open an issue in the repository.

---

**Built with production-grade patterns for incident response automation.**
