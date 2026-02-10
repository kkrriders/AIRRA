# Frontend Installation Guide

## ⚠️ Important: Windows Path Issue

Your project directory has spaces in the name: `"Autonomous Incident Response & Reliability Agent (AIRRA)"`

This can cause npm install issues on Windows. Here are **two solutions**:

## Solution 1: Clean Install (Recommended)

```bash
# Navigate to frontend directory
cd frontend

# Remove old node_modules and lock file if they exist
rm -rf node_modules package-lock.json

# Clear npm cache
npm cache clean --force

# Install with legacy peer deps (handles React 19 transitions)
npm install --legacy-peer-deps
```

## Solution 2: Use Short Path (Alternative)

If Solution 1 doesn't work, use Windows short path:

```bash
# Get short path
cd ..
cd /d %cd%

# This converts the path to something like C:\Users\karti\AUTONO~1
# Then navigate to frontend
cd frontend
npm install --legacy-peer-deps
```

## Solution 3: Docker (Easiest - No local install needed)

Skip npm install completely and use Docker:

```bash
# From project root
docker-compose up frontend

# This handles everything automatically
```

## What's New in This Version

✅ **Next.js 15.1.6** (latest stable)
✅ **React 19** (latest)
✅ **ESLint 9** (flat config)
✅ **TypeScript 5.7**
✅ No deprecated packages
✅ No security vulnerabilities

## After Installation

### Start Development Server

```bash
npm run dev
```

Open http://localhost:3000

### Build for Production

```bash
npm run build
npm start
```

### Type Check

```bash
npm run type-check
```

## Troubleshooting

### Error: "Cannot find module"

```bash
# Clear everything and reinstall
rm -rf node_modules package-lock.json .next
npm cache clean --force
npm install --legacy-peer-deps
```

### Error: "EPERM: operation not permitted"

This is a Windows permissions issue:

1. Close any editors/terminals using the frontend folder
2. Run your terminal as Administrator
3. Try install again

### Error: "unrs-resolver" or path issues

```bash
# Use legacy peer deps flag
npm install --legacy-peer-deps

# Or use npm 8 (more stable on Windows)
npm install -g npm@8
npm install
```

### Still Having Issues?

Use Docker (recommended for Windows):

```bash
# From project root
docker-compose up frontend
```

This avoids all local npm issues!

## Verification

After successful install:

```bash
# Check Next.js version
npx next --version
# Should show: 15.1.6 or similar

# Start dev server
npm run dev
# Should open on http://localhost:3000
```

## Dependencies Installed

### Core
- Next.js 15.1.6 (React framework)
- React 19 (UI library)
- TypeScript 5.7 (Type safety)

### Data & API
- @tanstack/react-query 5.62 (Data fetching)
- axios 1.7 (HTTP client)

### UI & Styling
- Tailwind CSS 3.4 (Styling)
- Lucide React (Icons)
- Sonner (Toasts)
- class-variance-authority (Component variants)

### Development
- ESLint 9 (Linting)
- TypeScript (Type checking)

All packages are **latest stable versions** with **no security vulnerabilities**.

## Quick Commands

```bash
# Install
npm install --legacy-peer-deps

# Develop
npm run dev

# Build
npm run build

# Production
npm start

# Type check
npm run type-check

# Lint
npm run lint
```

---

**Recommended: Use Docker to avoid all npm install issues on Windows!**
