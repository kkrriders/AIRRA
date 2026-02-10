# AIRRA Frontend

Modern, responsive web interface for the AIRRA incident management platform built with Next.js 14, TypeScript, and Tailwind CSS.

## Features

### 📊 Dashboard
- Real-time incident statistics
- Quick access to pending approvals
- Recent incident overview
- System health indicators

### 🔍 Incident Management
- List view with filtering and pagination
- Detailed incident views with:
  - AI-generated hypotheses ranked by confidence
  - Supporting evidence and signals
  - Recommended actions with risk assessment
- LLM analysis trigger from UI

### ✅ Approval Workflow
- Human-in-the-loop safety gates
- Action review with risk details
- Approve/reject with reasoning
- Execution mode selection (dry-run/live)

### 🎨 Modern UI
- Clean, professional design
- Responsive layout (mobile-friendly)
- Real-time updates with React Query
- Toast notifications for actions
- Loading states and error handling

## Technology Stack

| Technology | Purpose |
|------------|---------|
| **Next.js 14** | React framework with App Router |
| **TypeScript** | Type safety across the stack |
| **Tailwind CSS** | Utility-first styling |
| **React Query** | Data fetching and caching |
| **Axios** | HTTP client |
| **Recharts** | Data visualization (ready for metrics) |
| **Lucide React** | Modern icon library |
| **Sonner** | Toast notifications |

## Project Structure

```
frontend/
├── src/
│   ├── app/                    # Next.js App Router pages
│   │   ├── page.tsx           # Home/Dashboard
│   │   ├── incidents/         # Incident pages
│   │   │   ├── page.tsx       # List view
│   │   │   └── [id]/          # Detail view
│   │   ├── approvals/         # Approval workflow
│   │   ├── layout.tsx         # Root layout
│   │   ├── providers.tsx      # React Query provider
│   │   └── globals.css        # Global styles
│   ├── components/            # React components
│   │   └── ui/                # Reusable UI components
│   │       ├── card.tsx
│   │       ├── button.tsx
│   │       └── badge.tsx
│   ├── lib/                   # Utilities
│   │   ├── api.ts             # Backend API client
│   │   └── utils.ts           # Helper functions
│   └── types/                 # TypeScript types
│       └── index.ts           # API type definitions
├── public/                    # Static assets
├── package.json
├── tsconfig.json
├── tailwind.config.ts
└── next.config.js
```

## Quick Start

### Prerequisites
- Node.js 20+ and npm
- Backend API running (see backend/README.md)

### Development Setup

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

The frontend will be available at http://localhost:3000

### Environment Variables

Create `.env.local`:

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### Docker Setup

```bash
# Build the image
docker build -t airra-frontend .

# Run the container
docker run -p 3000:3000 \
  -e NEXT_PUBLIC_API_URL=http://localhost:8000 \
  airra-frontend
```

Or use docker-compose (recommended):

```bash
# From project root
docker-compose up frontend
```

## Available Scripts

```bash
# Development server with hot reload
npm run dev

# Production build
npm run build

# Start production server
npm start

# Run linting
npm run lint

# Type checking
npm run type-check
```

## Pages

### Home Page (`/`)
- Overview dashboard
- Quick stats (total, active, pending, resolved)
- Recent incidents preview
- Pending approvals preview
- Navigation to main sections

### Incidents List (`/incidents`)
- All incidents with pagination
- Status and severity badges
- Filtering capabilities (ready for implementation)
- Clickable rows to detail view

### Incident Detail (`/incidents/[id]`)
- Complete incident information
- AI-generated hypotheses with confidence scores
- Recommended actions with risk assessment
- Trigger LLM analysis button
- Link to approval workflow

### Approvals (`/approvals`)
- List of all pending actions
- Risk level indicators
- Action parameters display
- Approve/Reject buttons with email tracking
- Direct link to related incident

## API Integration

The frontend uses a centralized API client (`src/lib/api.ts`) that:

- Provides type-safe methods for all backend endpoints
- Handles error responses
- Uses Axios for HTTP requests
- Integrates with React Query for caching

### Example Usage

```typescript
import { useQuery, useMutation } from '@tanstack/react-query';
import { api } from '@/lib/api';

// Fetch incidents
const { data } = useQuery({
  queryKey: ['incidents'],
  queryFn: () => api.getIncidents({ page: 1, page_size: 20 }),
});

// Approve action
const approveMutation = useMutation({
  mutationFn: (id: string) =>
    api.approveAction(id, {
      approved_by: 'user@example.com',
      execution_mode: 'dry_run',
    }),
});
```

## Styling

### Tailwind CSS Setup

The project uses Tailwind CSS with a custom design system:

- Custom color palette (defined in `tailwind.config.ts`)
- Dark mode support (ready to implement)
- Responsive breakpoints
- Custom component variants

### Component Library

Custom UI components built with:
- **Class Variance Authority** for variant management
- **clsx** and **tailwind-merge** for dynamic classes
- Consistent styling across the app

## Type Safety

Full TypeScript coverage:

- API types match backend Pydantic schemas
- Component props are fully typed
- Utility functions have type inference
- No `any` types in production code

## Performance Optimizations

- React Query caching (1-minute stale time)
- Next.js automatic code splitting
- Image optimization (Next.js Image component ready)
- Standalone output for smaller Docker images

## Future Enhancements

Ready to implement:

- [ ] Real-time updates via WebSocket
- [ ] Advanced filtering and search
- [ ] Metrics charts with Recharts
- [ ] Dark mode toggle
- [ ] Export to CSV/PDF
- [ ] User authentication
- [ ] Multi-language support
- [ ] Accessibility improvements (WCAG 2.1)

## Browser Support

- Chrome/Edge (latest)
- Firefox (latest)
- Safari (latest)
- Mobile browsers (iOS Safari, Chrome Mobile)

## Troubleshooting

### Port 3000 already in use

```bash
# Kill process on port 3000
lsof -ti:3000 | xargs kill -9

# Or use a different port
PORT=3001 npm run dev
```

### API connection errors

1. Verify backend is running on http://localhost:8000
2. Check CORS settings in backend
3. Verify NEXT_PUBLIC_API_URL environment variable

### Build errors

```bash
# Clean Next.js cache
rm -rf .next

# Reinstall dependencies
rm -rf node_modules package-lock.json
npm install

# Try building again
npm run build
```

## Contributing

This is a final year academic project. The code demonstrates:

- Production-grade React patterns
- Type-safe frontend development
- Modern UI/UX principles
- Integration with AI-powered backend

## License

MIT License - Academic Project

---

**Built with Next.js 14 and TypeScript for production-grade incident management**
