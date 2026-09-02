# ADR-011: Abstention is a measured output, not a prompt instruction

**Status:** Accepted 2026-09-02

## Context

`golden_v1` contained 15 questions, every one of them answerable from the NIST
corpus. That makes one failure mode structurally invisible: a system that
answers *everything* — including questions the corpus cannot support — scores
exactly as well as one that correctly declines. The metric has no way to tell
them apart.

The system prompt already said "if the context does not contain the answer,
say so plainly." That is an instruction, not a mechanism. Nothing verified the
model complied, and nothing measured how often it did.

For a corpus of compliance documents this is the failure mode that actually
costs something. A confident wrong answer about an authentication requirement
is worse than no answer at all: no answer routes to a human, a wrong answer
routes into someone's audit evidence.

## Decision

Abstention becomes a first-class, measured property.

1. **Negatives in the dataset.** `GoldenExample` gains `answerable: bool`
   (default `True`). `golden_v2.jsonl` = the 15 answerable examples of v1 plus
   **5 negatives** — questions about HIPAA, GDPR, PCI DSS, Kubernetes, and
   ISO 27001 clause numbers. Each was verified absent from the corpus text
   before being added, not assumed absent.
2. **A schema that cannot be labelled wrong in silence.** An answerable
   example must list at least one `source_files` entry; a negative must list
   none. Both directions are enforced at parse time, because a negative
   carrying source files would score as a permanent retrieval miss and a
   positive without them makes recall undefined.
3. **A deterministic detector.** `is_abstention()` matches a closed list of
   refusal phrases; an empty answer counts as abstention. No LLM call, so the
   metric stays free and can gate every push alongside recall@k and MRR.
4. **Two error directions, reported separately.** `abstention_recall` (of the
   negatives, how many were correctly declined) and `false_abstention_rate`
   (of the answerable, how many were needlessly declined). Collapsing them
   into one number would hide the trade: a system that refuses everything
   scores a perfect 1.0 on the first.
5. **Rank metrics exclude negatives.** `RunRetrievalEval` skips them —
   recall and MRR are undefined without a relevant document, and including
   them would silently drag the aggregate toward zero.

## Consequences

- The abstention failure mode is now visible and gated
  (`abstention_recall >= 0.60`, tightening-only like every other threshold).
- `golden_v2` is a new file rather than an edit to `golden_v1`: scores are
  only comparable within a dataset version, and v1's published numbers stay
  reproducible.
- **Honest limitation:** phrase matching is not semantic understanding. A
  refusal worded outside the marker list reads as an answer, which *under*-
  reports abstention — the safe direction for a gate, since the metric can
  only make us look worse than we are, never better. An LLM-judged detector
  would be more faithful and would cost tokens on every run; that trade is
  revisitable if the phrase list starts missing real refusals.

  This is not hypothetical: the first marker list caught only **1 of the 5**
  negatives' own reference answers, because "the corpus does not *cover* X"
  is a natural refusal wording that the list did not include. Two tests now
  read the golden file directly and assert that every negative's reference
  answer reads as a refusal and no answerable one does — so a missing phrase
  fails a unit test instead of quietly costing abstention recall in a scored
  run. That is the mechanism that keeps the list honest as the set grows.
- **First measurement (2026-09-02) immediately justified the two-direction
  split.** `abstention_recall = 1.000` — all 5 negatives correctly declined —
  alongside `false_abstention_rate = 0.400`: the system also refused **6 of
  the 15 answerable questions**. A single combined "abstention score" would
  have reported this configuration as flawless. What it actually is: a system
  biased hard toward refusal, which is the safe direction for compliance work
  and a real usability problem worth attacking next. That finding is the
  entire argument for reporting both directions, and it appeared on the first
  run.
- Five negatives against fifteen positives is a small sample. The ratio is
  deliberate (negatives should not dominate), but neither number is large
  enough for a tight confidence interval, and the README says so.

## Alternatives considered

- **Prompt-only abstention** — the status quo. Rejected: unverified and
  unmeasured, which is exactly the gap this ADR exists to close.
- **A closed label set on the answer** (`supported` / `insufficient_support` /
  `not_in_corpus`) — genuinely better, and how the mini-RAG does it. Deferred
  because it changes the chat response schema and the SSE contract the
  frontend depends on; the detector measures the same property without a
  breaking API change. Recorded as the upgrade path.
- **LLM-judged abstention detection** — more faithful, but it makes the metric
  cost tokens and vary run to run, which moves it out of the always-on tier.
  Deliberately kept in the free, deterministic tier.
