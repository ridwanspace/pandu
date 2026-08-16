# ADR-002: One Postgres for everything — pgvector + FTS behind a SearchIndex port

**Status:** Accepted 2026-08-16

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
  or Tantivy baseline. For this corpus and a fused pipeline (RRF only
  consumes ranks, not scores) the difference is marginal — but we say
  "BM25-like" in the docs, not "BM25".
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
