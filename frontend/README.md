# AIRRA Frontend

Next.js 14 web interface for the AIRRA incident management platform.

## Tech Stack

| Technology | Purpose |
|---|---|
| **Next.js 14** | React framework with App Router |
| **TypeScript** | Type safety across the stack |
| **Tailwind CSS** | Utility-first styling |
| **React Query** | Data fetching, caching, and mutations |
| **Axios** | HTTP client |
| **Recharts** | Analytics charts |
| **Lucide React** | Icon library |
| **Sonner** | Toast notifications |

---

## Pages

| Page | Path | Description |
|---|---|---|
| Dashboard | `/` | Live stats, active alerts, system health |
| Incidents | `/incidents` | Filterable list with status/severity badges |
| Incident Detail | `/incidents/[id]` | Hypotheses, actions, timeline, analysis trigger |
| Approvals | `/approvals` | Actions waiting for human sign-off |
| On-Call | `/on-call` | Who is on-call now, grouped by service |
| Engineers | `/engineers` | Team roster with capacity bars, create engineers |
| Notifications | `/notifications` | Alert delivery history, SLA tracking |
| Analytics | `/analytics` | MTTR, resolution rates, pattern insights |

---

## Project Structure

```
frontend/src/
├── app/                        # Next.js App Router
│   ├── page.tsx                # Dashboard
│   ├── incidents/
│   │   ├── page.tsx            # Incident list
│   │   └── [id]/page.tsx       # Incident detail
│   ├── approvals/page.tsx
│   ├── on-call/page.tsx
│   ├── engineers/page.tsx
│   ├── notifications/page.tsx
│   ├── analytics/page.tsx
│   ├── layout.tsx              # Root layout (navigation)
│   └── providers.tsx           # React Query provider
├── components/
│   ├── navigation.tsx          # Sidebar navigation
│   ├── IncidentTimeline.tsx    # Incident event timeline
│   └── ui/                     # Reusable UI primitives
│       ├── card.tsx
│       ├── button.tsx
│       └── badge.tsx
└── lib/
    ├── api-client.ts           # Primary API client (fetch-based, proxy-aware)
    ├── api.ts                  # Compatibility wrapper
    └── utils.ts                # Helper functions
```

---

## Quick Start

The recommended way is via Docker Compose from the project root:

```bash
docker compose up -d
```

Frontend will be available at **http://localhost:3000**.

### Local development (without Docker)

```bash
cd frontend
npm install
npm run dev
```

Create `.env.local`:

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_API_KEY=dev-test-key-12345
```

---

## API Integration

All API calls go through `src/lib/api-client.ts`. In Docker, requests from the browser to `/api/v1/*` are proxied by Next.js to `http://backend:8000` to avoid CORS issues.

```typescript
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/lib/api-client';

// Fetch incidents
const { data } = useQuery({
  queryKey: ['incidents'],
  queryFn: () => apiClient.get('/api/v1/incidents/?page=1'),
});

// Approve action and refresh list
const qc = useQueryClient();
const approveMutation = useMutation({
  mutationFn: (id: string) =>
    apiClient.post(`/api/v1/approvals/${id}/approve`, {
      approved_by: 'engineer@example.com',
      execution_mode: 'dry_run',
    }),
  onSuccess: () => qc.invalidateQueries({ queryKey: ['approvals'] }),
});
```

---

## Available Scripts

```bash
npm run dev        # Development server with hot reload
npm run build      # Production build
npm start          # Start production server
npm run lint       # ESLint check
```

---

## Troubleshooting

### Port 3000 already in use

```bash
# macOS/Linux
lsof -ti:3000 | xargs kill -9

# Or change port
PORT=3001 npm run dev
```

### API connection errors

1. Verify the backend is running: `curl http://localhost:8000/health`
2. Check `NEXT_PUBLIC_API_URL` matches the backend host
3. In Docker: the frontend container calls `http://backend:8000` internally — ensure `backend` service is healthy

### Build errors after dependency changes

```bash
rm -rf .next node_modules
npm install
npm run build
```
