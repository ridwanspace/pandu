# ADR-014: Citation validity is an assertion, not a filter

**Status:** Accepted 2026-09-02

## Context

The chat pipeline hands the model `k` numbered contexts and asks it to cite
them inline as `[1]`, `[2]`. Afterwards, `used_citations()` filtered the
retrieved citation list down to the markers that appeared in the answer, and
persisted those.

That filter is silently forgiving in the one case that matters. Markers are
generated `1..n` from the retrieved set, so if the model emitted `[9]` against
five contexts, the marker matched nothing and was **dropped**. No error, no
log line, no metric. A fabricated citation — the model producing
citation-*shaped* text rather than a real reference — left no trace anywhere
in the system.

Citation fabrication is one of the few RAG failure modes that is a *code*
problem rather than a model problem. Whether every citation refers to a
retrieved chunk is decidable by set membership. It should be checked, not
prompted for.

## Decision

`validate_citations()` returns a `CitationReport` carrying:

- `cited` — the valid, referenced citations (what gets persisted; identical to
  the previous behaviour),
- `invalid_markers` — markers with no matching retrieved context,
- `uncited_markers` — retrieved contexts the answer never referenced,
- `is_valid` / `validity` — the fraction of distinct markers that were valid.

`AskQuestion` computes the report and annotates the trace span with
`invalid_citation_count` and `citation_validity`. Counts and a float only —
no answer or prompt text reaches the tracer, per the existing privacy stance.

`used_citations()` is kept and is now a one-line accessor over the report, so
there is no duplicated marker logic.

**An answer that cites nothing scores `validity = 1.0`, not `0.0.`** Under a
grounded prompt, citing nothing is what a correct abstention looks like
(see [ADR-011](ADR-011-abstention-as-a-measured-output.md)). Scoring it zero
would penalise exactly the behaviour the system is supposed to exhibit when
the context does not carry the answer.

## Consequences

- Fabricated citations are now visible in traces and countable over time,
  instead of vanishing.
- No API change: no new SSE event, no reordering of the
  `sources → token* → usage → done` sequence the OpenAPI contract and the
  frontend depend on. The change is additive and internal.
- **The check is structural, not semantic.** It proves a cited marker refers
  to a chunk that was actually retrieved. It does *not* prove that chunk
  supports the claim it is attached to — that needs a second-pass judge and is
  a different, token-costing layer. The distinction is worth stating plainly
  rather than letting "citation validation" imply more than it does.
- A negative marker such as `[-3]` is unreachable: the marker regex matches
  digits only, so it parses as no marker rather than an invalid one. Covered
  by a test that says so, rather than one implying negatives are rejected.

## Alternatives considered

- **Fail the request on an invalid citation** — rejected: a hallucinated
  marker in one sentence should not discard an otherwise grounded answer. The
  right response is to record it and let the metric ratchet.
- **A new SSE event carrying validation results** — rejected for v1: it
  breaks the frozen event contract for information that belongs in traces and
  metrics rather than in the user-facing stream.
- **Prompt harder** — rejected. This is the whole point: a property that can
  be decided by set membership should be decided by set membership.
