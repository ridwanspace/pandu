# ADR-013: A Qdrant adapter that ships off by default

**Status:** Accepted 2026-09-02
**Amends:** [ADR-002](ADR-002-pgvector-single-postgres.md) (does not reverse it)

## Context

ADR-002 chose one Postgres for everything and documented a Qdrant adapter as
the scale-out path — "the port exists precisely so this swap is an adapter,
not a rewrite." That is a claim about the codebase that nothing in the
codebase demonstrated. A port with exactly one implementation is an
*assertion* that it would be easy to add a second.

The pull to simply adopt Qdrant is worth resisting, and the reasons ADR-002
gave still hold at this scale: chunks and vectors stay transactionally
consistent, metadata filtering is a `WHERE` clause rather than a second system
to keep in sync, and the tenant filter that will eventually be a security
boundary lives in the same query as the vector search. Sync is where leaks
live.

## Decision

Build the adapter. Ship it **off**.

`QdrantSearchIndex` implements the same `SearchIndex` port. `SEARCH_INDEX=pg`
(the default) constructs `PostgresSearchIndex` exactly as before — zero
behaviour change on the default path. `SEARCH_INDEX=qdrant` swaps the dense
arm only. The `qdrant-client` dependency lives in an optional `qdrant` extra,
so the base image never carries it, and the import is lazy with an actionable
error if the extra is missing.

**The honest part, stated in the module docstring and here:** Qdrant's core
API has no BM25. The adapter therefore replaces *only the dense arm* and
delegates `lexical_search` to the injected Postgres index. A "Qdrant
deployment" of Pandu is Qdrant-dense plus Postgres-lexical. Returning `[]`
from the lexical arm would have been the easy alternative and would have
quietly halved hybrid recall while dashboards still said "hybrid".

The `status = 'ready'` invariant — which Postgres gets from a join — moves
into the Qdrant payload filter, and is applied unconditionally. Points written
without a `status` field are invisible: fail-closed, so a partially-indexed
document cannot leak into an answer.

## Consequences

- ADR-002's central claim is now demonstrated rather than asserted, at the
  cost of one adapter file and a config switch.
- The default deployment, the quickstart, and every published number are
  unchanged. Postgres remains the measured baseline.
- **The adapter is unit-tested against an in-memory fake, not a live Qdrant.**
  The fake applies the adapter's own constructed filter to its stored points,
  so filter construction is genuinely exercised — but no test proves this
  works against a real Qdrant server. Integration coverage is honest future
  work, not a thing to claim now.
- Running with `SEARCH_INDEX=qdrant` means two stateful stores and a
  dual-write path that nothing in the repo yet manages — there is no
  chunk→Qdrant sync job. The adapter proves the seam; it is not a supported
  production topology.
- Worth recording for a future decision: the import-linter contract that
  quarantines vendor SDKs is a **deny-list** (`openai`, `google`, `langfuse`,
  `sentence_transformers`), so `qdrant_client` is permitted anywhere under
  `app.modules.*` without amendment. Inverting it to an allow-list would be a
  real strengthening, and is deliberately out of scope here rather than
  changed unasked.

## Alternatives considered

- **Adopt Qdrant as the default** — rejected. It reverses ADR-002 for no
  measured benefit at portfolio scale, adds a second stateful service, and
  costs the transactional-consistency and single-`WHERE`-filter properties
  that are the strongest arguments for the current design.
- **Leave it as a documented path** — the status quo. Rejected because a
  one-implementation port evidences nothing about how hard the second one is.
- **Full Qdrant hybrid (its own sparse-vector support)** — larger than the
  claim being tested here, and it would mean maintaining two lexical
  implementations that must be kept in agreement.
