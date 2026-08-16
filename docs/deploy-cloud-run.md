# Deploying Pandu to Google Cloud Run — roadmap sketch

> **Status: roadmap, not implemented.** v1's deployment story is Docker
> Compose (see the README quickstart). This page is the honest outline of
> what a GCP deployment would look like, kept deliberately at sketch level —
> it becomes a real guide when the roadmap item lands, and pretending
> otherwise would be fake detail.

## Shape

Pandu is a modular monolith with three runtime processes (API, arq worker,
Next.js web) plus Postgres and Redis. That maps onto GCP as:

| Compose service | GCP target | Notes |
|---|---|---|
| `api` | Cloud Run service | The existing multi-stage image works as-is; Cloud Run wants `PORT` respected (uvicorn `--port $PORT`) |
| `worker` | Cloud Run *worker pool* (or a service with min-instances=1 and no ingress) | arq is a long-poll consumer, not request/response — it must not scale to zero while jobs are queued |
| `web` | Cloud Run service | Next.js standalone output; set `API_INTERNAL_URL` to the api service URL |
| `postgres` | Cloud SQL for PostgreSQL 17 | pgvector is a supported Cloud SQL extension (`CREATE EXTENSION vector`) — this is load-bearing for the whole design |
| `redis` | Memorystore for Redis | Serves both rate limiting and the arq queue; needs Serverless VPC Access from Cloud Run |
| `langfuse` profile | Skip self-hosting; use Langfuse Cloud | Self-hosting Langfuse v3 (ClickHouse + MinIO + Redis) on GCP is its own project; the tracer port makes this a config change |

## Known work items (why this isn't a paste-and-run guide yet)

- **SSE on Cloud Run**: streaming responses are supported, but request
  timeouts must be raised (default 300s is fine for chat; confirm buffering
  behavior behind any load balancer in front).
- **Migrations**: `alembic upgrade head` moves from container entrypoint to
  a deploy step (Cloud Run job, or a CI step against Cloud SQL via the
  auth proxy) — running migrations on every cold start is wrong once
  min-instances > 1.
- **Secrets**: `.env` becomes Secret Manager references wired into the
  Cloud Run service definitions; the app already reads pure env vars, so no
  code change.
- **Networking**: Cloud SQL via the built-in connector; Memorystore
  requires a VPC connector — the one piece of real infra plumbing here.
- **Ingestion limits**: uploads currently travel through the API into
  Postgres (`document_blobs`); at 25 MB max this is fine for Cloud Run's
  32 MB request cap, but a GCS-upload path would be the proper fix at
  larger sizes.
- **Cold starts**: keep `min-instances=1` on the API for demo-day latency;
  the worker must be pinned at 1 regardless (see above).
- **CI/CD**: extend the existing GitHub Actions with a
  `gcloud run deploy` step using Workload Identity Federation (no
  long-lived JSON keys).

## What deliberately stays out

Kubernetes/GKE and Terraform remain out of scope even for this sketch —
Cloud Run + Cloud SQL is the smallest honest production footprint for a
single-team monolith, and that claim is itself part of the architecture
story (ADR-003, §8 of `ARCHITECTURE_REVIEW.md`).
