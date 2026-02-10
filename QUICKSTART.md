# AIRRA Quick Start Guide

Complete guide to get AIRRA (Backend + Frontend) running in 5 minutes.

## 🚀 Full Stack Setup (Recommended)

### Prerequisites
- Docker and Docker Compose installed
- API key for Anthropic Claude or OpenAI

### Step 1: Configure API Key

```bash
# Create environment file in backend directory
cd backend
cp .env.example .env

# Edit .env and add your API key
# Required: Set ONE of these
nano .env
# Add: AIRRA_ANTHROPIC_API_KEY=sk-ant-your-key-here
```

### Step 2: Start Everything

```bash
# Return to project root
cd ..

# Start all services (backend, frontend, database, redis, prometheus)
docker-compose up -d

# Check services are running
docker-compose ps
```

Expected output:
```
NAME                STATUS
airra-backend       Up
airra-frontend      Up
airra-postgres      Up (healthy)
airra-prometheus    Up (healthy)
airra-redis         Up (healthy)
```

### Step 3: Access the Application

- **Frontend**: http://localhost:3000 ← Start here!
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Prometheus**: http://localhost:9090

### Step 4: Test the System

#### Option A: Via Web UI (Easiest)

1. Open http://localhost:3000
2. Navigate to "Incidents" → Click "+" to create
3. Fill in incident details
4. Click "Analyze with AI" to trigger LLM analysis
5. Review hypotheses and recommended actions
6. Go to "Approvals" to approve/reject actions

#### Option B: Via API (Postman/curl)

See [SETUP.md](SETUP.md) for detailed API testing examples.

## 🛑 Stop Everything

```bash
# Stop all services
docker-compose down

# Stop and remove all data (WARNING: Deletes database)
docker-compose down -v
```

## 📊 What You'll See

### Homepage Dashboard
- Real-time incident statistics
- Recent incidents
- Pending approvals
- System overview

### Incident Management
- Create and track incidents
- AI-powered root cause analysis
- Confidence-scored hypotheses
- Risk-assessed recommendations

### Approval Workflow
- Review pending actions
- See risk levels and parameters
- Approve (dry-run mode) or reject
- Track approval history

## 🔧 Development Mode

### Run Services Separately

```bash
# Terminal 1: Start infrastructure
docker-compose up postgres redis prometheus

# Terminal 2: Backend
cd backend
poetry install
poetry shell
uvicorn app.main:app --reload

# Terminal 3: Frontend
cd frontend
npm install
npm run dev
```

### Access Points in Dev Mode
- Frontend: http://localhost:3000
- Backend: http://localhost:8000
- Backend docs: http://localhost:8000/docs

## 🎓 Demo Scenario

### Complete Walkthrough

1. **Create Incident** (Frontend: Home → Incidents → Create)
   ```
   Title: High CPU usage in payment service
   Description: CPU spiked to 95% causing slow response times
   Severity: High
   Service: payment-service
   ```

2. **Trigger Analysis** (Incident Detail page → "Analyze with AI" button)
   - System fetches metrics from Prometheus
   - Detects anomalies using statistical methods
   - Generates hypotheses using Claude/GPT
   - Ranks by confidence (e.g., "Memory leak: 87%")
   - Recommends action (e.g., "Restart pod")

3. **Review Approval** (Approvals page)
   - See recommended action
   - View risk level and parameters
   - Enter your email
   - Click "Approve (Dry-Run)"

4. **See Results** (Back to Incident Detail)
   - Status updated to "Approved"
   - Action executed in dry-run mode
   - Incident marked as "Resolved"

## 🐛 Troubleshooting

### Frontend won't start
```bash
# Check if port 3000 is available
lsof -i :3000

# View frontend logs
docker-compose logs frontend

# Rebuild frontend
docker-compose up -d --build frontend
```

### Backend API errors
```bash
# Check backend logs
docker-compose logs backend

# Verify API key is set
docker-compose exec backend env | grep AIRRA_

# Restart backend
docker-compose restart backend
```

### Database connection failed
```bash
# Check PostgreSQL
docker-compose logs postgres

# Restart database
docker-compose restart postgres
```

### "Cannot connect to backend" error
```bash
# Verify backend is running
curl http://localhost:8000/health

# Check CORS settings (should allow localhost:3000)
# Already configured in backend/app/main.py
```

## 📚 Next Steps

1. **Explore the UI**
   - Create multiple incidents
   - Test different severity levels
   - Review the approval workflow

2. **Read Documentation**
   - [Backend README](backend/README.md) - API details
   - [Frontend README](frontend/README.md) - UI components
   - [Features](features.md) - Full architecture

3. **Customize**
   - Adjust anomaly detection thresholds
   - Configure LLM prompts
   - Add your own action types
   - Integrate with your monitoring

4. **Extend**
   - Add more metrics sources
   - Integrate ServiceNow (mock available)
   - Add Slack notifications
   - Implement WebSocket real-time updates

## 💡 Tips

- **Start with dry-run mode** (default) for safety
- **Use the web UI** for easier testing
- **Check API docs** at /docs for all endpoints
- **View logs** with `docker-compose logs -f [service]`
- **Reset everything** with `docker-compose down -v && docker-compose up -d`

## 🎯 For Your Presentation

### Demo Flow
1. Show architecture diagram (from features.md)
2. Open frontend at http://localhost:3000
3. Create incident via UI
4. Click "Analyze with AI"
5. Show generated hypotheses with confidence scores
6. Explain reasoning: Perception → Reasoning → Decision
7. Navigate to Approvals
8. Show human-in-the-loop safety gate
9. Approve in dry-run mode
10. Show execution result
11. Open backend API docs at /docs
12. Show database records (optional)

### Key Points to Highlight
- **Full Stack**: Professional frontend + backend
- **AI-Powered**: Real LLM integration (Claude/GPT)
- **Production-Ready**: Docker, type safety, error handling
- **Safe**: Confidence scoring, approval workflow, dry-run
- **Well-Documented**: READMEs, inline comments, API docs

## 🆘 Getting Help

- Check service logs: `docker-compose logs [service]`
- View backend errors: `docker-compose logs backend`
- Frontend debugging: Browser console (F12)
- API testing: http://localhost:8000/docs

---

**You're ready! Open http://localhost:3000 and start exploring AIRRA** 🚀
