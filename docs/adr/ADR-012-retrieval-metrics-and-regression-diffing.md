# ADR-012: Full rank metrics, and gate on the diff as well as the threshold

**Status:** Accepted 2026-09-02

## Context

The evaluation module measured exactly two things: `recall@k` and `MRR`. Two
problems followed from that.

**The metrics were too coarse to fail.** 12 of the 15 golden examples have a
single source file. With `top_k = 5`, recall@5 over one relevant document is
effectively a *hit rate* — "did the right PDF appear anywhere in five slots".
A reported 0.967 mostly says the corpus is small and k is generous. Nothing
measured how much noise reached the model (precision), and nothing measured
the quality of the whole ordering (nDCG) — which is the metric that can
actually show fusion making things worse.

**The gate could not see a swap.** CI compared each run against fixed
thresholds. An aggregate can sit perfectly still while five examples break and
five different ones improve; every threshold passes and the suite reports
green. The average lies in exactly the case you most want to catch.

## Decision

**Expand the metrics.** `precision@k`, `hit_rate@k`, and binary-gain `nDCG@k`
join recall and MRR. All are pure, deterministic and LLM-free, so they stay in
the always-on tier that runs on every push. Reporting at `k = 1, 3, 5, 10`
makes the recall@1-vs-recall@5 gap visible — the specific signal that says
"retrieval finds it but ranks it badly", which is when reranking pays.

Two identity rules, chosen because the id model has duplicates by
construction (`__miss_N` markers occupy non-relevant positions):

- **precision** counts relevant *positions*, since two chunks from the same
  relevant file are two useful context slots.
- **nDCG** credits each unique relevant id once, at its best position, so a
  retriever cannot inflate its score by returning one document repeatedly.

**Gate on movement, not just level.** `evals/run.py --compare` diffs the
current run against the most recent stored run of the same dataset version and
fails on *any* per-metric regression, independent of whether absolute
thresholds pass. `false_abstention_rate` is registered as lower-is-better so
its direction inverts. Bookkeeping fields (`examples`, `negatives`,
`positives`, `k`) are excluded — growing the golden set is not a regression.
A float tolerance keeps noise from reading as a signal.

## Consequences

- A change that trades one question's correctness for another's now fails CI
  instead of passing it.
- The first run on a new dataset version has no baseline; it becomes the
  baseline and reports that plainly rather than failing.
- Comparison is per-*metric*, not per-*example*. It catches an aggregate that
  moved; it does not yet name which question broke. Per-example diffing needs
  example-level results persisted, which the `EvalRun` schema does not carry —
  recorded as the next step, not claimed as done.
- Reported nDCG is binary-gain (relevant / not relevant). The golden set has
  no graded relevance labels, so a graded nDCG would be a more precise number
  computed from labels we do not have.

## Addendum: the judge's token budget is part of the eval's definition

Running the LLM-judge track on `golden_v2` failed immediately with
`invalid JSON`. The cause was not a malformed verdict — it was **no verdict
at all**. With real retrieved context in the prompt, `deepseek-v4-flash`
consumed its entire 2048-token completion budget on hidden reasoning and
returned an empty string. Measured: `completion_tokens = 2048`,
`len(text) = 0`.

Raising the cap to 8192 was not sufficient on its own. Measuring the same
prompt at temperature 0 across six runs gave completion-token counts of
**548, 611, 615, 1696, 3258 and 4295** — an eightfold spread on identical
input. Reasoning length is not a property of the prompt you can size a
budget against; it has a long tail, and a fixed cap only moves how often the
tail truncates.

Three changes followed:

1. The judge budget went to **8192**, which covers the observed distribution
   with headroom.
2. An **empty verdict is retried once**. This is deliberately not "run the
   judge N times and average" — that treats truncations as scores and makes
   the problem invisible. A non-empty verdict is parsed strictly and never
   re-sampled; only the empty case retries, and a second empty response
   still fails the run.
3. `parse_verdict` reports the empty case with its own message naming
   `max_output_tokens`, rather than folding it into "invalid JSON".

The second change matters more than the first. As a generic JSON error this
presents as judge flakiness, and the instinctive response — average across
repeated runs — makes it strictly worse, because every repeat truncates
identically. A wrong diagnosis here costs far more than the bug.

The general rule this supports: the judge model, its version, **and its
token budget** are part of the eval's definition, not deployment details.
They belong beside the thresholds, which is why the resolved judge model is
recorded on every run's config.

## Addendum: the faithfulness gate currently FAILS, and that is the correct outcome

First `golden_v2` judge run: **faithfulness 0.798 against a 0.85 gate — FAIL.**
The gate is not being lowered. Two investigations explain the number.

**First, a real bug in this work.** The initial run scored 0.749 across all 20
examples, negatives included. But the rubric asks whether the reference
answer's claims are supported by the retrieved passages, and a negative's
reference answer is a *refusal* whose supporting evidence is the corpus's
silence. That question is not well-posed, and the judge answered it
essentially at random — measured across the five negatives:
**0.0 / 1.0 / 0.0 / 1.0 / 1.0**. Negatives were already excluded from rank
metrics for exactly this reason; missing the same argument for the judge was
an oversight. Fixed, and worth +0.049.

**Second, what remains is a real retrieval limitation.** Splitting the
corrected run by example type:

| Example type | n | mean faithfulness |
|---|---|---|
| single-source | 12 | **0.868** (would pass) |
| cross-document | 3 | **0.577** |

The mechanism, measured directly on `cross-mfa-171-63b`:

```
top_k= 5: {800-63b: 5}                          <- one document takes every slot
top_k=10: {800-63b: 9, 800-53r5: 1}
top_k=20: {800-63b: 13, 800-53r5: 4, 800-171r3: 3}
```

A cross-document question needs evidence from two publications. Relevance is
scored per chunk with no diversity constraint, so the document with the
strongest lexical and semantic overlap monopolises all five context slots and
the second source never reaches the prompt. The second source first appears
around rank 18. Retrieval is not failing to *find* the evidence — it is
failing to *distribute* the context budget across the sources the question
needs.

This is precisely the failure that a single aggregate hides and that
recall@k alone cannot see: recall@5 is 0.967 because it credits the sources
that were found, while faithfulness catches that the answer could not
actually be composed. Two metrics disagreeing is the system working.

**The fix is retrieval, not the threshold**: per-document caps on context
slots (max-marginal-relevance style diversity), or a decomposition step that
retrieves per sub-question and merges. Both are real work, and neither is
being done under cover of a relaxed gate. The gate stays at 0.85, currently
red, with the reason documented — a failing gate that names its cause is
worth more than a green one that was moved.

## Alternatives considered

- **Keep recall@k and MRR only** — rejected: they cannot distinguish "found
  it and ranked it first" from "found it and buried it", and precision is the
  metric that says how much noise the model has to read past.
- **Gate on the diff instead of thresholds** — rejected: a diff gate alone
  ratchets nothing. A run can degrade slowly within tolerance forever. The two
  gates answer different questions and both are kept.
- **ragas for context precision/recall** — rejected for the always-on tier.
  ragas' `llm_factory` targets OpenAI via langchain, so a non-OpenAI judge is
  skipped rather than scored, and it makes a free metric cost tokens. The
  ragas path remains available behind `--ragas`.
