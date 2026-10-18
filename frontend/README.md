# Frontend - Client Insights

Next.js (App Router) + TypeScript + Tailwind CSS. Auth pages, dashboard layout, and workspace switcher for Phase 1.

## Architecture

- **Root Routing**: `app/` (no `src/` directory)
- **Components**: atomic design under `components/{atoms,molecules,organisms,templates}`
- **Configuration**: `config/index.ts` for API URLs
- **API Services**: `services/` class-based Axios clients with JWT attach + refresh

## Scripts

```bash
npm install
npm run dev
```

App: http://localhost:3000 (API expected at http://localhost:8000)
