# ADR-002: One Postgres for everything — pgvector + FTS behind a SearchIndex port

**Status:** Accepted 2026-08-16 · amended by
[ADR-013](ADR-013-optional-qdrant-adapter.md) (2026-09-02): the Qdrant adapter
described below as a documented-but-unbuilt path now **exists and ships off by
default**, so the "swap is an adapter, not a rewrite" claim is demonstrated
rather than asserted. The decision — one Postgres for everything — is
unchanged.

## Context

Hybrid retrieval needs two indexes: dense vectors (semantic) and a lexical
index (keyword). The fashionable answer is a dedicated vector database
(Qdrant, Weaviate, Pinecone) next to Postgres. But Pandu's relational data —
documents, chunks, conversations, cost ledger — already lives in Postgres,
and the corpus is portfolio-scale (thousands to low millions of chunks), far
below the ~10–50M-vector region where dedicated engines start earning their
operational cost. Every extra stateful service also erodes the
"clone → one API key → `make up`" quickstart.

## Decision

Postgres 17 with the **pgvector** extension is the only database. Chunks,
their embeddings (`Vector(1536)`, HNSW index with cosine distance), and a
generated `tsvector` column (GIN-indexed) live in one table, written in one
transaction. Dense search is a pgvector HNSW query; lexical search is
Postgres full-text search ranked with `ts_rank_cd`; both feed Reciprocal
Rank Fusion in the retrieval module. Access goes through a `SearchIndex`
port, so the storage engine is an implementation detail to the application
layer.

## Consequences

- Chunks and their vectors are transactionally consistent — a failed
  ingestion can't leave orphaned embeddings, and deleting a document is one
  cascading delete, not a cross-system saga.
- Metadata filtering (by document, tag, date) is a SQL `WHERE` clause
  composed into the same query — no filter-pushdown API to learn.
- One less service in compose, in CI (testcontainers runs the real
  `pgvector/pgvector:pg17` image), and in the mental model.
- **Honest caveat:** Postgres FTS is BM25-*like*, not BM25.
  `ts_rank_cd` has no term-saturation or document-length normalization the
  way true BM25 does, so lexical rankings will differ from an Elasticsearch
  or Tantivy baseline. We say "BM25-like" in the docs, not "BM25".

  **Measured 2026-09-02, re-measured 2026-09-06.** The first measurement put
  the lexical arm at nDCG@5 **0.267** and hybrid (0.897) *below* dense alone
  (0.906), and this ADR concluded the BM25-like caveat was "larger than
  marginal". That conclusion was wrong, and instructively so: the arm was not
  weak, it was **empty**. `websearch_to_tsquery` ANDs every term, so whole
  questions matched no chunk at all — 14 of 20 golden questions returned zero
  lexical rows. See [ADR-015](ADR-015-lexical-arm-ranks-not-filters.md).

  With the arm actually ranking, lexical alone scores nDCG@5 **0.641** and
  hybrid+RRF **0.920** against dense's 0.906 — so hybrid *does* beat its
  strongest arm, and by more at low k (0.933 vs 0.800 at k=1). The BM25-like
  caveat stands as written — `ts_rank_cd` still has no term saturation or
  length normalisation, and 0.641 is not what a real BM25 would score — but
  it is now a genuine caveat about ranking quality rather than an explanation
  invented for a number produced by a bug. The exact-BM25 upgrade path below
  remains the honest next step, no more urgent than it was.
- Scale-out path is documented, not built: exact BM25 via ParadeDB
  `pg_search`, or a Qdrant adapter behind the same `SearchIndex` port (with
  server-side hybrid search) when the vector count or QPS outgrows a single
  Postgres. The port exists precisely so this swap is an adapter, not a
  rewrite.

## Alternatives considered

- **Qdrant from day 1** — better ANN throughput and native server-side
  hybrid search, but adds a second stateful store, dual-write consistency
  work, and operational surface with no benefit at this scale. Documented as
  the upgrade path instead.
- **Dual adapters (pgvector and Qdrant) from day 1** — rejected: doubles the
  phase-1 integration-test matrix for a capability nothing needs yet.
- **Elasticsearch/OpenSearch for lexical** — exact BM25, but the heaviest
  service in the stack for the smallest part of the pipeline.
