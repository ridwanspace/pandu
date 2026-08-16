# ADR-010: Reranker defaults to no-op, opt-in by config

**Status:** Accepted 2026-08-16

## Context

Cross-encoder reranking is part of the retrieval showcase, and the
`Reranker` port has real adapters: hosted APIs (Cohere Rerank, Jina) and a
local cross-encoder (`sentence-transformers`, BGE-reranker). But each
default carries a cost:

- **Local-by-default** drags torch into the base image (2–3 GB) and gives
  slow CPU inference to every user who just wants the demo.
- **Hosted-by-default** requires a *second* API key before anything works,
  breaking the "clone → add one key → `make up`" quickstart that the whole
  onboarding story is built around.

Meanwhile, hybrid search + RRF alone already produces respectable results;
reranking is a quality improvement, not a prerequisite.

## Decision

The default reranker is a **no-op**: fused RRF results go straight to the
LLM (`RERANKER=none`). Reranking is opt-in via env:

- `RERANKER=cohere` or `RERANKER=jina` — hosted API adapters (add the key).
- `RERANKER=local` — local cross-encoder, installed only via
  `uv sync --extra rerank-local` / compose `--profile rerank`, so torch
  never enters the base image.

The evaluation dashboard reports rerank-on vs rerank-off scores side by
side.

## Consequences

- The quickstart stays one API key, and the base image stays slim —
  graceful degradation is a designed feature, not an accident.
- The toggle becomes *evidence*: the eval suite quantifies exactly what
  reranking buys on the golden set, which is a stronger showcase than
  having it silently always-on.
- The no-op adapter proves the port is honest (three real implementations
  plus a null object, all behind one `Protocol`).
- Cost: out-of-the-box answer quality is slightly below the system's best
  configuration, and a hurried reviewer might evaluate the default. The
  README counters this by stating the toggle and pointing at the eval
  comparison.

## Alternatives considered

- **Local cross-encoder by default** — rejected: 2–3 GB image, slow CPU
  inference, worst first-run experience for the most common visitor.
- **Hosted reranker by default** — rejected: a second mandatory API key is
  exactly the onboarding friction the quickstart promise forbids.
- **No reranking at all in v1** — rejected: cross-encoder reranking is an
  explicit CV claim and a phase-3 deliverable; it must exist and be
  measured, just not be mandatory.
