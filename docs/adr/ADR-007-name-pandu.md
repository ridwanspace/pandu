# ADR-007: Product name — Pandu

**Status:** Accepted 2026-08-16

## Context

The project needs a name that works as a GitHub repo, reads well to an
international audience, and ideally says something about what the system
does. Generic names ("rag-platform") are forgettable; clever English puns
tend to collide with existing projects.

## Decision

**Pandu** — Indonesian for *guide* / *scout*. Tagline: "grounded answers,
guided by your documents." Repo name `pandu` (falling back to `pandu-rag`
if taken).

## Consequences

- The name carries personal identity — the author is Indonesian — which is
  a feature in a portfolio: it invites the one-line explanation and makes
  the project memorable.
- Semantically on-target: a RAG system's job is literally to guide answers
  through source documents.
- Low collision risk on GitHub and PyPI-adjacent namespaces at decision
  time.
- Cost: non-Indonesian speakers get no meaning from the word alone, so the
  tagline and README must do that work (they do, in the first line).

## Alternatives considered

- **Groundwork** — a parseable pun on "grounded generation", but a generic
  English word with heavy existing usage.
- **Corpora** — professional but sterile, and multiple existing projects
  already use it.
- **Descriptive names** (`rag-production-platform`) — say what it is, but
  indistinguishable from every other RAG repo; kept as the GitHub topic
  tags instead.
