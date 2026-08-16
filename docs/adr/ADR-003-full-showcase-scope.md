# ADR-003: v1 scope — full showcase, not core-first

**Status:** Accepted 2026-08-16

## Context

A RAG portfolio project can stop at "retrieval + a chat endpoint" and still
demonstrate the algorithms. But the thesis of this repo is that the
difference between a demo and infrastructure is everything *around* the
pipeline: evaluation, observability, governance, and engineering discipline.
A core-only v1 would undercut that thesis, while an unbounded scope
(multi-tenancy, SSO, agents) would never ship.

## Decision

v1 ships the full showcase, no more:

- Ingestion with a real UI: upload → Docling parse → structure-aware chunking
  → embeddings → indexing, as an async job with status polling.
- Streaming chat (SSE) with inline numbered citations and a sources panel.
- Hybrid retrieval (dense + lexical), RRF fusion, optional reranking.
- Evaluation as a CI gate: golden dataset, ragas metrics, retrieval-only
  metrics, LLM-as-judge.
- Langfuse tracing (optional compose profile) and a cost dashboard.
- API-key auth, rate limiting, input bounds, counts-only logging.

Explicitly **out of scope for v1** (roadmap, §10 of the architecture
review): multi-tenancy/workspaces, GraphRAG, agentic multi-hop retrieval,
SSO, Kubernetes/Terraform.

## Consequences

- The repo can back every CV claim with running code and CI evidence, which
  is the point.
- The build is phased (foundations → ingestion → retrieval/chat → quality →
  observability → hardening) so each phase lands as a reviewable PR train
  with the full quality gate — the git history itself is portfolio evidence.
- Cost: v1 is a genuinely large build for one person. The mitigations are
  the phase plan and the modular monolith (each module can land
  independently).
- Deferring multi-tenancy means some schemas (API keys, conversations) are
  single-tenant shaped; the roadmap notes workspaces as the
  biggest-bang later addition, and the modular boundaries keep that
  refactor localized.

## Alternatives considered

- **Core-first (pipeline + minimal API, no UI/evals/observability)** —
  faster to ship, but indistinguishable from a thousand RAG demos; rejected.
- **Include multi-tenancy in v1** — the most valuable later addition, but it
  taints every table and endpoint with workspace scoping before the core is
  proven; deferred.
- **Include agentic retrieval (query decomposition, multi-hop)** — deferred
  to a roadmap spike; v1's pipeline is deliberately linear so the retrieval
  engineering stays legible (see ADR-004).
