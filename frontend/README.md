# Pandu RAG — frontend

Next.js App Router UI for the Pandu RAG platform: streamed chat with inline citations,
document ingestion, and an eval/cost dashboard.

## Stack

- **Next.js 16** (App Router, React 19, TypeScript strict)
- **Tailwind CSS 4 + shadcn/ui** — theme-aware (light/dark via `next-themes`)
- **TanStack Query** for server state; **Zustand** (persisted) only for connection settings
- **Native SSE over `fetch`** — the chat stream is parsed by a hand-rolled WHATWG-compliant
  frame parser (`src/lib/sse.ts`), because `EventSource` cannot send the `X-API-Key` header
- **Biome** for lint + format, **Vitest + Testing Library** for unit tests,
  **Playwright** for e2e
- **pnpm**, Node 24

## How it talks to the backend

All requests go straight from the browser to the FastAPI backend
(`{API base URL}/api/v1/...`) with an `X-API-Key` header. Base URL and key are configured
on the **Settings** page and persisted in `localStorage` (never cookies). The typed client
lives in `src/lib/api/`:

- `types.ts` — hand-written mirror of the frozen HTTP contract
- `client.ts` — fetch wrapper injecting base URL + `X-API-Key`, error normalization,
  SSE-response helper
- one module per resource (`documents.ts`, `conversations.ts`, `retrieval.ts`,
  `evals.ts`, `stats.ts`)

`pnpm generate:api` regenerates `src/lib/api/generated.d.ts` from the live backend's
OpenAPI schema (`openapi-typescript`). CI drift-checks the generated types against the
hand-written contract, so frontend and backend cannot silently diverge.

## Scripts

| Script | What it does |
| --- | --- |
| `pnpm dev` | Dev server on :3000 |
| `pnpm build` | Production build (`output: "standalone"`) |
| `pnpm start` | Serve the production build |
| `pnpm lint` / `pnpm lint:fix` | Biome check (lint + format + import order) |
| `pnpm typecheck` | `tsc --noEmit` (strict) |
| `pnpm test` | Vitest unit tests (SSE parser, citation renderer) |
| `pnpm test:e2e` | Playwright e2e — env-gated, see below |
| `pnpm generate:api` | Regenerate OpenAPI types from a running backend |

## E2E tests

The Playwright specs (chat happy path, upload flow) run against the full compose stack
and self-skip unless `E2E_BASE_URL` is set:

```sh
docker compose up -d           # repo root: api on :8000, web on :3000
cd frontend
E2E_BASE_URL=http://localhost:3000 E2E_API_KEY=<key from backend .env> pnpm test:e2e
```

`E2E_API_BASE_URL` (default `http://localhost:8000`) points the app at the backend.

## Docker

Multi-stage build (deps → build → slim runtime, non-root `nextjs` user, port 3000):

```sh
docker build -t pandu-frontend frontend/
docker run -p 3000:3000 pandu-frontend
```

## Layout

```
src/
├── app/                  # routes: / (chat), /documents, /dashboard, /settings
├── components/
│   ├── chat/             # conversation sidebar, message list, citation chips, sources panel
│   ├── documents/        # upload dropzone, status table, chunk inspector
│   ├── dashboard/        # metric trend + daily cost charts, eval/cost tables
│   └── ui/               # shadcn/ui primitives (generated, owned)
└── lib/
    ├── api/              # typed contract client (see above)
    ├── hooks/            # useChatStream — drives the SSE answer lifecycle
    ├── sse.ts            # SSE frame parser (unit-tested)
    └── settings-store.ts # persisted connection settings (zustand)
```
