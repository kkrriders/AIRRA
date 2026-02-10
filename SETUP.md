# AIRRA Backend Setup Guide

## 🎯 Quick Start (5 Minutes)

### Prerequisites
- Docker & Docker Compose installed
- API key for Anthropic Claude or OpenAI

### Step-by-Step Setup

#### 1. Configure Environment Variables

```bash
# Copy example environment file
cd backend
cp .env.example .env

# Edit .env and add your API key
# Required: Set ONE of these
AIRRA_ANTHROPIC_API_KEY=sk-ant-your-key-here
# OR
AIRRA_OPENAI_API_KEY=sk-your-key-here
```

#### 2. Start the Backend Stack

```bash
# Return to project root
cd ..

# Start all services (PostgreSQL, Redis, Prometheus, Backend)
docker-compose up -d

# Check services are running
docker-compose ps
```

Expected output:
```
NAME                IMAGE                   STATUS
airra-backend       airra-backend           Up
airra-postgres      postgres:16-alpine      Up (healthy)
airra-prometheus    prom/prometheus:latest  Up (healthy)
airra-redis         redis:7-alpine          Up (healthy)
```

#### 3. Verify Backend is Running

```bash
# Health check
curl http://localhost:8000/health

# Expected response:
# {"status":"healthy","service":"AIRRA Backend","version":"0.1.0","environment":"development"}

# View API documentation
open http://localhost:8000/docs
```

## 🔧 Development Setup (Local)

If you want to run the backend locally without Docker:

### 1. Install Dependencies

```bash
cd backend

# Install Poetry (if not installed)
curl -sSL https://install.python-poetry.org | python3 -

# Install project dependencies
poetry install

# Activate virtual environment
poetry shell
```

### 2. Start Required Services

```bash
# Start PostgreSQL and Redis via Docker
cd ..
docker-compose up -d postgres redis prometheus
```

### 3. Run Backend Locally

```bash
cd backend

# Run with auto-reload (development)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## 📊 Testing the System

### Test 1: Create an Incident

```bash
curl -X POST http://localhost:8000/api/v1/incidents \
  -H "Content-Type: application/json" \
  -d '{
    "title": "High CPU usage in payment service",
    "description": "CPU usage spiked to 95% causing slow response times",
    "severity": "high",
    "affected_service": "payment-service",
    "detected_at": "2024-01-20T10:00:00Z",
    "metrics_snapshot": {
      "cpu_usage": 95.0,
      "memory_usage": 75.0,
      "request_rate": 1000
    }
  }'
```

Save the returned `id` for next steps.

### Test 2: Trigger LLM Analysis

```bash
# Replace {incident_id} with the ID from Test 1
curl -X POST http://localhost:8000/api/v1/incidents/{incident_id}/analyze

# This will:
# 1. Fetch metrics from Prometheus (if available)
# 2. Detect anomalies using statistical methods
# 3. Generate hypotheses using LLM (Claude/GPT)
# 4. Recommend remediation actions
# 5. Calculate risk scores
```

### Test 3: Review Pending Approvals

```bash
curl http://localhost:8000/api/v1/approvals/pending

# Returns list of actions waiting for human approval
```

### Test 4: Approve an Action

```bash
# Replace {action_id} with an action from Test 3
curl -X POST http://localhost:8000/api/v1/approvals/{action_id}/approve \
  -H "Content-Type: application/json" \
  -d '{
    "approved_by": "admin@example.com",
    "execution_mode": "dry_run"
  }'
```

### Test 5: Execute the Action

```bash
# Replace {action_id} with the approved action
curl -X POST http://localhost:8000/api/v1/actions/{action_id}/execute

# In dry_run mode, this simulates execution without making changes
```

## 🧪 Running Tests

```bash
cd backend

# Run all tests
poetry run pytest

# Run with coverage report
poetry run pytest --cov=app --cov-report=html

# View coverage report
open htmlcov/index.html

# Run specific test file
poetry run pytest tests/unit/test_anomaly_detector.py -v
```

## 📡 Monitoring & Observability

### Prometheus
- URL: http://localhost:9090
- Metrics: AIRRA exposes `/metrics` endpoint
- Query examples:
  - `airra_incidents_total` - Total incidents created
  - `airra_llm_tokens_used` - LLM token usage

### Logs
```bash
# View backend logs
docker-compose logs -f backend

# View all logs
docker-compose logs -f
```

### Database Access
```bash
# Connect to PostgreSQL
docker-compose exec postgres psql -U airra -d airra

# Example queries:
# \dt                              -- List tables
# SELECT * FROM incidents;         -- View incidents
# SELECT * FROM hypotheses;        -- View hypotheses
# SELECT * FROM actions;           -- View actions
```

## 🐛 Troubleshooting

### Issue: API Key Not Working

```bash
# Check environment variables are loaded
docker-compose exec backend env | grep AIRRA_

# Restart backend to reload config
docker-compose restart backend
```

### Issue: Database Connection Failed

```bash
# Check PostgreSQL is running
docker-compose ps postgres

# View PostgreSQL logs
docker-compose logs postgres

# Restart PostgreSQL
docker-compose restart postgres
```

### Issue: Port Already in Use

```bash
# Check what's using port 8000
lsof -i :8000

# Option 1: Kill the process
kill -9 <PID>

# Option 2: Change port in docker-compose.yml
# Edit ports section: "8001:8000"
```

## 🔄 Common Commands

```bash
# Start services
docker-compose up -d

# Stop services
docker-compose down

# View logs
docker-compose logs -f backend

# Rebuild backend (after code changes)
docker-compose up -d --build backend

# Reset database (WARNING: Deletes all data)
docker-compose down -v
docker-compose up -d

# Access backend shell
docker-compose exec backend bash

# Run database migrations (when using Alembic)
docker-compose exec backend alembic upgrade head
```

## 📝 Configuration Options

Edit `backend/.env` to customize:

| Variable | Default | Description |
|----------|---------|-------------|
| `AIRRA_LLM_PROVIDER` | `anthropic` | LLM provider (`anthropic` or `openai`) |
| `AIRRA_LLM_MODEL` | `claude-3-5-sonnet-20241022` | Model identifier |
| `AIRRA_ANOMALY_THRESHOLD_SIGMA` | `3.0` | Z-score threshold for anomaly detection |
| `AIRRA_CONFIDENCE_THRESHOLD_HIGH` | `0.8` | High confidence threshold |
| `AIRRA_CONFIDENCE_THRESHOLD_LOW` | `0.5` | Low confidence (triggers human review) |
| `AIRRA_DRY_RUN_MODE` | `true` | Safe mode - simulates actions without executing |
| `AIRRA_DEBUG` | `true` | Enable debug mode and API docs |
| `AIRRA_LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |

## 🎓 For Your Demo/Presentation

### Demo Flow
1. Start with system architecture diagram (from README)
2. Show live API at http://localhost:8000/docs
3. Create incident via API call
4. Trigger analysis - explain each layer:
   - Perception: Anomaly detection
   - Reasoning: LLM hypothesis generation
   - Decision: Action selection with risk assessment
5. Show approval workflow (human-in-the-loop)
6. Execute in dry-run mode
7. Show database records (incident → hypotheses → actions)

### Key Points to Highlight
- **Production-grade code**: Type hints, async, error handling
- **LLM integration**: Structured prompting, confidence scoring
- **Safety**: Approval workflow, dry-run mode, risk assessment
- **Observability**: Structured logs, metrics, database audit trail
- **Extensibility**: Clean architecture, easy to add features

## 📚 Next Steps

1. **Add more tests** - Cover edge cases, integration tests
2. **Create demo data** - Script to generate realistic incidents
3. **Add Kubernetes actions** - Real execution layer
4. **Integrate with monitoring** - Alert manager, Grafana
5. **Build CI/CD** - GitHub Actions for testing and deployment

## 🆘 Getting Help

- API Documentation: http://localhost:8000/docs
- Backend README: [backend/README.md](backend/README.md)
- Architecture: [features.md](features.md)

---

**You're now ready to run and demo AIRRA!** 🚀
