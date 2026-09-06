# ADR-015: The lexical arm ranks with OR, it does not filter with AND

**Status:** Accepted 2026-09-06

## Context

`PostgresSearchIndex.lexical_search` built its `tsquery` with
`websearch_to_tsquery('english', :q)`. That function is the right choice for
accepting raw user input — it never raises a syntax error on stray quotes or
operators, so hostile input is safe without escaping. But it joins every term
with `&`.

AND is correct for a *search box*. A person types two words, gets too many
results, and types a third to narrow; requiring all terms is the feature.

AND is wrong for the lexical arm of a RAG retriever, which is handed a whole
question and must **rank** the corpus, not filter it. The golden question

> How do the multi-factor authentication requirements in SP 800-171 relate to
> the authentication assurance levels in SP 800-63B?

parses to nine ANDed terms:

```
'multi-factor' <-> 'multi' <-> 'factor' & 'authent' & 'requir' & 'sp'
  & '800' <-> '-171' & 'relat' & 'authent' & 'assur' & 'level'
  & '800' <-> '-63' <-> 'b'
```

No 512-token chunk contains all nine. The arm returned **zero rows**. Not a
bad ranking — an empty one.

Measured across the 20-question golden set on the NIST corpus, **14 of 20
questions returned zero lexical rows**, and the six that matched returned 1–4
rows against the dense arm's 20.

### Why nothing caught it

This is the part worth keeping.

1. **RRF degrades silently by design.** Fusing an empty arm is not an error —
   `reciprocal_rank_fusion([dense, []])` returns the dense ranking, correctly.
   Hybrid search had been running as dense-only in production, and every
   health check, contract test and type check passed.

2. **The tests asserted the bug as the specification.** `test_multi_word_query_
   requires_all_terms` passed a two-word query where both words happened to
   co-occur, and asserted the partial match was excluded. AND semantics was
   encoded as intent, so the behaviour was protected rather than caught.

3. **The eval suite measured the symptom and we misread it.** ADR-010 recorded
   hybrid at nDCG 0.897 *below* dense at 0.906 and treated it as a finding
   about fusion — RRF weighting both arms equally, a weak lexical arm dragging
   a strong embedder down. The real cause was that there was no lexical arm.
   An aggregate that looks plausible is the easiest kind of bug to keep.

## Decision

Rewrite the *parsed* tsquery, relaxing top-level `&` to `|`:

```sql
(SELECT replace(websearch_to_tsquery('english', :q)::text, ' & ', ' | ')::tsquery)
```

Any term may match; `ts_rank_cd` then does the ranking it was always meant to
do — scoring by how many terms matched, how rare they are, and how close
together they sit.

Rewriting the parsed output rather than the raw input string is deliberate:

- **Injection safety is retained.** `websearch_to_tsquery` still does the
  parsing, so user input never reaches the tsquery grammar unvalidated.
- **Phrases survive.** A quoted `"exclusive lock"` parses to `<->` adjacency,
  which contains no top-level `& ` to rewrite. Quoted phrases stay strict, and
  a test pins that.
- **Negation survives.** `!term` is preserved for the same reason.

## Consequences

Measured on the NIST corpus, 15 answerable golden questions,
`gemini/gemini-embedding-001`, k=5:

| Arm | recall@5 | precision@5 | MRR | nDCG@5 |
|---|---|---|---|---|
| hybrid — before | 0.967 | 0.760 | 0.889 | 0.897 |
| hybrid — after | 0.967 | 0.680 | **0.947** | **0.920** |
| dense (unchanged) | 0.967 | 0.747 | 0.900 | 0.906 |
| lexical — before | ~0 (dead arm) | — | — | — |
| lexical — after | 0.733 | 0.440 | 0.658 | 0.641 |

**Hybrid now beats dense** (nDCG 0.920 vs 0.906, MRR 0.947 vs 0.900), which is
what ADR-002 claimed hybrid retrieval was for and what the previous numbers
quietly contradicted.

Precision@5 falls 0.760 → 0.680. That is the honest cost: a live lexical arm
promotes chunks that share vocabulary without being the best answer. Recall
and hit-rate hold at 0.967 and 1.000, and the top-of-list metrics — the ones
that decide what the LLM actually reads first — improve.

The regression test is `test_natural_language_question_still_returns_candidates`:
it sends a full sentence and asserts the arm is non-empty. Verified to fail
with `assert []` against the old SQL.

### What this does not fix

`cross-mfa-171-63b` still retrieves no SP 800-171 chunk in its top 5, even
though `§ 03.05.03 Multi-Factor Authentication` exists in the corpus and is
exactly on point. Both arms rank 800-63B above it, because the question is
*about* authentication assurance levels and 800-63B is the authentication
document. This is a genuine ranking failure and remains open — see the
per-document cap evaluated and rejected below.

## Alternatives considered

**Per-document context caps.** This ADR's investigation began as an attempt to
implement them, on the hypothesis that one publication monopolizing all five
context slots was what depressed cross-document faithfulness (0.577 vs 0.868
single-source). The hypothesis did not survive measurement. Only 1 of 3
cross-document questions monopolizes; the other two already retrieve both
sources. Simulated over the real fused lists, every cap value loses more than
it gains:

| Cap | recall@5 | precision@5 | nDCG@5 | cross-doc both sources |
|---|---|---|---|---|
| none | 0.967 | 0.680 | 0.920 | 2/3 |
| 3 per doc | 0.900 | 0.510 | 0.894 | 2/3 |
| 2 per doc | 0.933 | 0.402 | 0.913 | 3/3 |

A cap of 2 buys the third cross-document question at the cost of recall
(0.967 → 0.933), hit-rate (1.000 → 0.933) and a large precision drop, and it
pulls *more* distinct documents into the negative questions (1.80 → 2.40 mean),
which pushes false abstention the wrong way. Backfilling the capped slots from
overflow, so the context never shrinks below k, tracks the hard cap almost
exactly and does not rescue the trade.

Rejected: a global constraint that damages 19 questions to fix 1. The
underlying problem is a ranking problem, and the right fix ranks — query
decomposition for multi-source questions, or a diversity term inside the
fusion score rather than a filter applied after it.

**Weighting the arms in RRF.** Would let a noisy lexical arm contribute less
without silencing it. Worth revisiting now that the arm's standalone quality
is measurable (nDCG 0.641) rather than unknown; premature before that.

**`plainto_tsquery` / raw string manipulation.** Both discard websearch's
quoted-phrase and negation handling for no benefit.
