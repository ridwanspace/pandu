# Golden evaluation dataset

Hand-curated question/answer/source triples over the NIST SP 800 seed corpus
(see `ARCHITECTURE_REVIEW.md` §7 and `CORPUS_LICENSE.md`):

| File | Publication |
|---|---|
| `nist-sp-800-53r5.pdf` | SP 800-53 Rev. 5 — Security and Privacy Controls |
| `nist-sp-800-63b.pdf` | SP 800-63B — Digital Identity: Authentication & Lifecycle |
| `nist-sp-800-171r3.pdf` | SP 800-171 Rev. 3 — Protecting CUI in Nonfederal Systems |
| `nist-csf-2.0.pdf` | CSWP 29 — Cybersecurity Framework 2.0 |

## Format

One JSON object per line. `golden_v1.jsonl` is the released 15-example set;
`golden_v2.jsonl` is the current set — the same 15 answerable examples plus 5
negatives (see below):

```json
{
  "id": "aal2-mfa-requirements",
  "question": "...",
  "reference_answer": "2-4 factually accurate sentences",
  "source_files": ["nist-sp-800-63b.pdf"],
  "source_hints": ["AAL2"],
  "answerable": true
}
```

- `source_files` — the documents a correct answer must draw from. Relevance is
  labeled at the **file level**, not the chunk level: chunk ids change every
  time the chunking config changes, so chunk-level labels would rot on every
  re-ingest. File-level labels survive re-chunking.
- `source_hints` — optional case-insensitive substrings; when present, a
  retrieved chunk only counts as relevant if it comes from a source file *and*
  matches at least one hint (in its text or heading path). Hints keep "right
  file, wrong section" from inflating scores in 500-page documents.
- Cross-document questions (ids prefixed `cross-`) list multiple
  `source_files`; recall@k only reaches 1.0 when the top-k contexts cover
  **all** of them, which makes those examples strictly harder than a hit rate.
- `answerable` — optional, defaults to `true`. `false` marks a **negative**:
  a question the corpus genuinely cannot answer (ids prefixed `neg-`). The
  schema enforces both directions: an answerable example must list at least
  one source file, a negative must list none. A negative carrying source
  files would score as a permanent retrieval miss; an answerable one without
  them makes recall undefined.

## Negatives, and why they exist

A dataset of only answerable questions cannot distinguish a careful system
from one that answers everything confidently — both score identically. The
five negatives in `golden_v2` (HIPAA, GDPR, PCI DSS, Kubernetes hardening,
ISO 27001 clause numbers) are what make abstention measurable
([ADR-011](../../../docs/adr/ADR-011-abstention-as-a-measured-output.md)).

Each was **verified absent from the corpus text** before being added, not
assumed absent — a probe over the extracted text of all four PDFs. That check
caught two candidates that looked safe and were not: "Basel" and "AML" both
appear as substrings of `baseline` and `AML` in the NIST text, which would
have made them false negatives scoring a permanent, unfixable miss.

Negatives are excluded from rank metrics (recall@k, MRR, nDCG@k) — those are
undefined without a relevant document — and are scored only by the abstention
eval, which reports two error directions separately: `abstention_recall` (of
the negatives, how many were correctly declined) and `false_abstention_rate`
(of the answerable, how many were needlessly declined). A system that refuses
everything scores 1.0 on the first and is caught by the second.

## Curation methodology

1. Questions are written the way a compliance or security engineer would ask
   them (the corpus's natural audience), not reverse-engineered from chunk
   text. Synthetic-only golden sets are a known anti-pattern; every item here
   was authored and fact-checked by hand against the actual publications.
2. Reference answers are 2-4 sentences, factually grounded in the documents,
   and self-contained — they are judge inputs, not generation targets.
3. Coverage is deliberate: per-document factual lookups, catalog-structure
   questions, and three cross-document questions that force multi-source
   retrieval.
4. Grow the set by *appending* to a **new version** (`golden_v2.jsonl`), never
   by editing a released version in place — eval runs record
   `dataset_version`, and scores are only comparable within one version.
   Ragas' `TestsetGenerator` may be used to *propose* candidates for future
   versions, but every accepted item is human-reviewed and rewritten.

## Threshold policy: tightening-only

CI thresholds (see `evals/run.py`) start permissive — recall@5 >= 0.60,
faithfulness >= 0.85, context precision >= 0.75, abstention recall >= 0.60 —
and may only ever be
**raised**, never lowered. If a change drops a metric below threshold, fix the
pipeline or consciously revisit the change; do not loosen the gate. Lowering a
threshold to make CI green defeats the entire point of having an eval gate.

## Measured results (golden_v2, 2026-09-02)

Corpus: 1826 chunks across the four NIST publications,
`gemini-embedding-001`, hybrid + RRF, no reranker.

| Metric | k=1 | k=3 | k=5 | k=10 |
|---|---|---|---|---|
| recall@k | 0.767 | 0.933 | 0.967 | 0.967 |
| precision@k | 0.800 | 0.822 | 0.760 | 0.660 |
| MRR | 0.800 | 0.889 | 0.889 | 0.889 |
| nDCG@k | 0.800 | 0.880 | 0.897 | 0.897 |
| hit-rate@k | 0.800 | 1.000 | 1.000 | 1.000 |

Abstention: `abstention_recall` **1.000** (5/5 negatives declined),
`false_abstention_rate` **0.400** (6 of 15 answerable questions also
declined — the number to attack next).

The gap between recall@1 (0.767) and recall@5 (0.967) is the classic
"found it but ranked it badly" signal, which is normally the case for
reranking. Measured, reranking made it worse — see
[ADR-010](../../../docs/adr/ADR-010-reranker-default-noop.md).

## Regression diffing

Thresholds alone cannot catch a *swap*: an aggregate can hold steady while
some examples break and others improve, and every threshold still passes.
`uv run python -m evals.run --compare` diffs a run against the most recent
stored run of the same `dataset_version` and fails on any per-metric
regression, independent of the absolute gates
([ADR-012](../../../docs/adr/ADR-012-retrieval-metrics-and-regression-diffing.md)).

The comparison is per-metric, not per-example — it detects that something
moved, not yet which question broke. Per-example diffing needs example-level
results persisted, which `EvalRun` does not currently carry.
