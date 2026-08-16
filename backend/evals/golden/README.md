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

One JSON object per line (`golden_v1.jsonl`):

```json
{
  "id": "aal2-mfa-requirements",
  "question": "...",
  "reference_answer": "2-4 factually accurate sentences",
  "source_files": ["nist-sp-800-63b.pdf"],
  "source_hints": ["AAL2"]
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
faithfulness >= 0.85, context precision >= 0.75 — and may only ever be
**raised**, never lowered. If a change drops a metric below threshold, fix the
pipeline or consciously revisit the change; do not loosen the gate. Lowering a
threshold to make CI green defeats the entire point of having an eval gate.
