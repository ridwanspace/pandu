# The corpus

Pandu's demo and evaluation corpus is four NIST cybersecurity publications.
This page explains what they are, why they were chosen, and how the golden
dataset is built on top of them. The licensing story lives in
[`CORPUS_LICENSE.md`](../CORPUS_LICENSE.md); the decision record is
[ADR-006](adr/ADR-006-nist-seed-corpus.md).

## Fetching

```bash
./scripts/fetch_corpus.sh
```

Downloads into `backend/evals/corpus/` (idempotent — existing files are
skipped), verifies each file is a real PDF of plausible size, and fails
loudly otherwise. The PDFs are fetched from the canonical
`nvlpubs.nist.gov` locations; if NIST moves a file, verify the current URL
on its [publication page](https://csrc.nist.gov/publications) and update
the script.

| File | Publication | Why it's in the set |
|---|---|---|
| `nist-sp-800-53r5.pdf` | SP 800-53 rev. 5 — Security and Privacy Controls | Dense control-catalog tables: the stress test for layout-aware parsing and structure-aware chunking |
| `nist-sp-800-63b.pdf` | SP 800-63B — Digital Identity: Authentication & Lifecycle | Precise normative language (AAL levels, MFA requirements) — great for factual-grounding questions |
| `nist-sp-800-171r3.pdf` | SP 800-171 rev. 3 — Protecting CUI | Overlaps 800-53 conceptually, enabling cross-document and "which document says X" questions |
| `nist-csf-2.0.pdf` | CSWP 29 — Cybersecurity Framework 2.0 | Framework functions map into 800-53 controls — natural multi-hop material |

### Demo excerpt: SP 800-53r5

The full SP 800-53r5 is 492 pages and costs tens of CPU-minutes to parse
with Docling's layout models. For the demo/eval corpus we deliberately
ingest a **56-page excerpt** — title/abstract, chapters 1–2 (how the control
catalog is organized), the chapter-3 opening with AC-1/AC-2, the complete
Audit & Accountability family (AU-1…AU-16, incl. AU-9 and AU-11), and the
complete Incident Response family — which is every section the golden
dataset references. The excerpt is produced from the fetched PDF with
`pypdfium2` (page ranges 1–3, 28–49, 92–109, 176–188 of the original) and
uploaded under the canonical filename so golden-set source matching is
unaffected. Nothing stops you ingesting the full document — it just takes
CPU time, not money.

## Why this corpus

The seed corpus had four requirements, and most candidates fail at least one:

1. **Redistributable in a public repo.** NIST publications are US-government
   works: public domain, no copyright, acknowledgement requested (and
   given). No takedown risk, usable in CI.
2. **Enterprise-realistic.** Compliance documents are exactly what real
   internal knowledge bases are full of. Queries like *"What are the MFA
   requirements for AAL2?"* or *"Which controls cover audit log retention?"*
   are the shape of questions an enterprise RAG system actually gets.
3. **Hard in the right ways.** Real PDFs with multi-column layout, deep
   heading hierarchies, and enormous tables — the ingestion pipeline
   (Docling + structure-aware chunking) has something real to prove.
4. **English**, because the reviewer audience is international.

Alternatives considered and rejected: Kubernetes docs (CC BY 4.0 but
Markdown-native — no PDF-parsing showcase), MS MARCO and similar QA sets
(research-only licenses or wrong shape), Indonesian tax regulations
(narrows the audience). Details in ADR-006.

## The golden dataset

`backend/evals/` holds a versioned golden dataset — currently 20 items
(15 answerable + 5 negatives), growing toward 50–100
question/answer/source triples over this corpus, stored as JSONL and
treated like code (reviewed, versioned, changelog'd via
`dataset_version`).

The construction method matters more than the count:

- **Bootstrap** candidate pairs with ragas' `TestsetGenerator` against the
  parsed corpus.
- **Human-curate every item.** Synthetic-only golden sets are a known
  anti-pattern — generators produce paraphrase-shaped questions that flatter
  retrievers. Each kept item is verified for: answerable-from-corpus, a
  correct reference answer, and accurate source chunk attribution. Some
  items are written by hand specifically to be hard (cross-document,
  table-lookup, negation).
- **Question mix**: single-fact lookups, table lookups (800-53 control
  parameters), cross-document questions (CSF function → 800-53 controls),
  and deliberately unanswerable questions to measure abstention.

### Negatives (shipped in `golden_v2`)

The unanswerable questions are no longer aspirational: `golden_v2.jsonl`
carries five, marked `"answerable": false` and carrying no `source_files` —
HIPAA, GDPR, PCI DSS, Kubernetes hardening, and ISO 27001 clause numbers.

Each was **verified absent from the extracted text of all four PDFs** before
being accepted, rather than assumed absent. That check earned its keep
immediately: two candidates that looked obviously safe were not. "Basel" and
"AML" both occur in the corpus — as substrings of *baseline* and of *AML*
inside other tokens — and either would have become a question with no
correct answer that also scored as a permanent retrieval miss.

Negatives are excluded from rank metrics (undefined without a relevant
document) and scored only by the abstention eval
([ADR-011](adr/ADR-011-abstention-as-a-measured-output.md)).

The dataset feeds three evaluation tracks — rank metrics (recall@k,
precision@k, hit-rate@k, MRR, nDCG@k at k=1/3/5/10 — deterministic, no LLM,
cheap enough for every run), abstention (two error directions, also LLM-free
to score), and generation metrics (faithfulness/relevancy/precision/recall +
LLM-as-judge — nightly and on-demand). See the README's evaluation section.

## Optional secondary corpus

For multilingual/regulatory flavor: GDPR and the EU AI Act from EUR-Lex
(CC BY 4.0, attribution notice in `CORPUS_LICENSE.md`). Not fetched by
default and not part of the scored golden set; if added, keep its items in
a separate dataset version so scores stay comparable.
