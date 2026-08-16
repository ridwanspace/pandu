# ADR-006: NIST SP 800-series publications as the seed corpus

**Status:** Accepted 2026-08-16

## Context

The golden dataset and demo need a corpus that is (a) legally redistributable
in a public repo, (b) enterprise-realistic, (c) hard enough to exercise the
pipeline — real PDFs with tables and multi-column layout, cross-document
questions — and (d) in English, because the reviewer audience is
international. Most public QA datasets fail (a) or (d) (research-only
licenses) or (c) (Markdown-native, no parsing challenge).

## Decision

Seed the corpus with four NIST cybersecurity publications, fetched by
`scripts/fetch_corpus.sh` into `backend/evals/corpus/`:

| File | Publication |
|---|---|
| `nist-sp-800-53r5.pdf` | SP 800-53 rev. 5 — Security and Privacy Controls |
| `nist-sp-800-63b.pdf` | SP 800-63B — Digital Identity: Authentication & Lifecycle |
| `nist-sp-800-171r3.pdf` | SP 800-171 rev. 3 — Protecting CUI |
| `nist-csf-2.0.pdf` | CSWP 29 — Cybersecurity Framework 2.0 |

NIST publications are works of the US federal government: public domain in
the United States (17 U.S.C. §105), no copyright, redistribution permitted;
NIST asks only for acknowledgement, which `CORPUS_LICENSE.md` provides.

An **optional secondary corpus** — GDPR and the EU AI Act from EUR-Lex
(CC BY 4.0 under Commission Decision 2011/833/EU) — is documented for
multilingual/regulatory flavor but not fetched by default.

## Consequences

- SP 800-53r5 is a massive control catalog full of dense tables — an ideal
  stress test for Docling's layout-aware parsing and structure-aware
  chunking, which is precisely the ingestion showcase.
- Enterprise-realistic queries fall out naturally ("What are the MFA
  requirements for AAL2?", "Which controls cover audit log retention?"),
  including cross-document ones (CSF 2.0 references map into 800-53
  controls) — good raw material for a golden set that isn't toy trivia.
- Clean licensing story: the corpus can live in CI and in the repo's
  fetch script without a takedown risk, stated in `CORPUS_LICENSE.md`.
- Cost: the domain is narrow (cybersecurity compliance). Eval numbers won't
  claim generality across domains, and the docs say so.

## Alternatives considered

- **Kubernetes documentation** — CC BY 4.0 and well-known, but
  Markdown-native: it would waste the PDF-parsing showcase entirely.
- **MS MARCO / existing QA datasets** — research-only licenses or the wrong
  shape (passage ranking, not document QA over a coherent corpus).
- **Indonesian tax regulations** — public domain locally and personally
  relevant, but an Indonesian-language corpus narrows the
  international-reviewer audience; kept as an idea, not the default.
