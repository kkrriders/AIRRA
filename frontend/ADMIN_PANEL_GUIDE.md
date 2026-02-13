# AIRRA Admin Panel - Engineer Notification System

## Overview

The Admin Panel provides a complete UI for the engineer notification and on-call management system built in Phase 4.

## Features

### 1. **Token-Based Admin Access** (`/admin/[token]`)
- Engineers receive email notifications with secure token links
- Click link → Auto-acknowledge → Review incident
- No password required - frictionless 2 AM experience
- SLA tracking with response time metrics

### 2. **On-Call Dashboard** (`/on-call`)
- Real-time view of all on-call engineers
- Grouped by service with escalation priority (PRIMARY/SECONDARY/TERTIARY)
- Engineer availability status
- Auto-refreshing every 60 seconds

### 3. **Notifications Dashboard** (`/notifications`)
- Track all incident notifications
- SLA compliance metrics
- Average response time
- Multi-channel support (Email, Slack, SMS)
- Auto-refreshing every 30 seconds

### 4. **Main Dashboard** (`/`)
- System overview with key metrics
- Active incidents count
- On-call engineer count
- Notification statistics
- Recent incidents feed

## Setup

### 1. Install Dependencies
```bash
cd frontend
npm install
```

### 2. Environment Configuration

Create `.env.local` file:

```env
# Backend API URL
NEXT_PUBLIC_API_URL=http://localhost:8000

# API Key (must match backend AIRRA_API_KEY)
NEXT_PUBLIC_API_KEY=dev-test-key-12345
```

**Important:** The `NEXT_PUBLIC_API_KEY` must match the `AIRRA_API_KEY` set in your backend `.env` file.

### 3. Start Development Server
```bash
npm run dev
```

The frontend will be available at http://localhost:3000

## Architecture

### API Client (`src/lib/api-client.ts`)
- Centralized axios instance with interceptors
- Automatic API key injection (except for `/acknowledge` endpoint)
- Type-safe request/response interfaces
- Error handling and logging

### Pages
```
src/app/
├── page.tsx                    # Main dashboard
├── admin/[token]/page.tsx      # Token-based admin panel
├── on-call/page.tsx            # On-call engineer dashboard
├── notifications/page.tsx      # Notifications tracking
└── layout.tsx                  # Root layout with navigation
```

### Components
```
src/components/
├── navigation.tsx              # Main navigation bar
└── ui/                         # Reusable UI components
    ├── card.tsx
    ├── badge.tsx
    └── button.tsx
```

## Testing the Admin Panel

### Prerequisites
1. Backend must be running (`docker-compose up` or `uvicorn app.main:app`)
2. PostgreSQL database initialized
3. At least one engineer and on-call schedule created

### Test Flow

#### 1. Create Test Data (using backend API)

**Create an Engineer:**
```bash
curl -X POST http://localhost:8000/api/v1/admin/engineers/ \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-test-key-12345" \
  -d '{
    "name": "Alice Engineer",
    "email": "alice@example.com",
    "role": "Senior SRE",
    "slack_handle": "@alice",
    "phone": "+1234567890"
  }'
```

**Create On-Call Schedule:**
```bash
curl -X POST http://localhost:8000/api/v1/on-call/ \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-test-key-12345" \
  -d '{
    "engineer_id": "<engineer-id-from-above>",
    "service": "payment-service",
    "team": "backend",
    "start_time": "2025-02-01T00:00:00Z",
    "end_time": "2025-12-31T23:59:59Z",
    "priority": "PRIMARY",
    "schedule_name": "Q1 2025 Rotation"
  }'
```

**Create an Incident:**
```bash
curl -X POST http://localhost:8000/api/v1/incidents/ \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-test-key-12345" \
  -d '{
    "title": "Payment Processing Slow",
    "description": "Response times degraded by 300%",
    "affected_service": "payment-service",
    "severity": "high"
  }'
```

**Send Notification:**
```bash
curl -X POST http://localhost:8000/api/v1/notifications/send \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-test-key-12345" \
  -d '{
    "engineer_id": "<engineer-id>",
    "incident_id": "<incident-id>",
    "channel": "email",
    "priority": "high"
  }'
```

#### 2. View Dashboards

**Main Dashboard:**
- Navigate to http://localhost:3000
- Should see: Active incidents, on-call engineers, notification stats

**On-Call Dashboard:**
- Navigate to http://localhost:3000/on-call
- Should see: Alice Engineer listed under "payment-service" with PRIMARY priority

**Notifications Dashboard:**
- Navigate to http://localhost:3000/notifications
- Should see: Recent notification with status and SLA metrics

#### 3. Test Admin Panel Access

**Get Token from Notification:**
```bash
# Get notification details
curl http://localhost:8000/api/v1/notifications/<notification-id> \
  -H "X-API-Key: dev-test-key-12345"
```

Look for `acknowledgement_token` in the response.

**Access Admin Panel:**
```
http://localhost:3000/admin/<acknowledgement-token>
```

**Expected Behavior:**
1. Page loads with "Validating token..." spinner
2. Auto-acknowledges the notification
3. Shows success toast with response time and SLA status
4. Displays incident details with severity badge
5. Shows AI hypotheses (if generated)
6. Shows recommended actions
7. Provides buttons to Approve/Reject/Escalate

## UI Components & Features

### Admin Panel Features
- **Auto-Acknowledgement:** Token validates and marks notification as acknowledged
- **SLA Tracking:** Shows if engineer responded within SLA target
- **Incident Overview:** Color-coded severity, real-time status
- **Hypothesis Review:** AI-generated root cause analysis
- **Action Approval:** One-click approve/reject for automated remediation
- **Escalation:** Quick escalate button for senior engineer involvement
- **Feedback:** Provide learning feedback for AI improvement

### Real-Time Updates
- Dashboard: Refreshes every 30 seconds
- On-Call: Refreshes every 60 seconds
- Notifications: Refreshes every 30 seconds

### Responsive Design
- Mobile-friendly layouts
- Tailwind CSS utilities
- Dark mode support (via system preference)

## Common Issues

### 1. "Connection Error" on Dashboard
**Cause:** Backend not running or wrong API URL
**Fix:**
- Ensure backend is running: `docker-compose up`
- Check `NEXT_PUBLIC_API_URL` in `.env.local`

### 2. "Invalid or Expired Token"
**Cause:** Token expired (1 hour default) or already used
**Fix:** Generate a new notification and use the new token

### 3. "503 Service Unavailable"
**Cause:** API key not configured in backend
**Fix:** Set `AIRRA_API_KEY` in backend `.env` file

### 4. Empty Dashboards
**Cause:** No data in database
**Fix:** Create test engineers, schedules, and incidents using curl commands above

## API Key Security

**Development:**
- Use test key like `dev-test-key-12345`
- Store in `.env.local` (gitignored)

**Production:**
- Generate strong random key: `openssl rand -base64 32`
- Use environment variables (never commit)
- Consider rotating keys regularly

## Next Steps

- [ ] Add WebSocket support for real-time incident updates
- [ ] Implement incident timeline visualization
- [ ] Add engineer performance analytics
- [ ] Build SLA reporting dashboard
- [ ] Implement notification preference settings
- [ ] Add mobile push notifications via PWA

## Screenshots

### Main Dashboard
![Dashboard showing metrics and recent incidents]

### Admin Panel
![Token-based incident review interface]

### On-Call Schedule
![List of current on-call engineers by service]

### Notifications
![Notification history with SLA tracking]

## Support

For issues or questions:
1. Check backend logs: `docker-compose logs backend`
2. Check frontend console: Browser DevTools → Console
3. Verify API connectivity: `curl http://localhost:8000/health`
