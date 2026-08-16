# ADR-004: No RAG framework in the core pipeline

**Status:** Accepted 2026-08-16

## Context

LangChain and LlamaIndex are the default answer to "build a RAG app" — they
ship retrievers, splitters, fusion, rerankers, and vendor integrations out
of the box. For a product team on a deadline that is often the right call.

This repo has a different objective: it exists to demonstrate that the
author can *build* retrieval — hybrid search SQL, Reciprocal Rank Fusion,
the rerank stage, grounded prompting, streaming with citations. A framework
would hide exactly the parts worth showing; a reviewer opening
`modules/retrieval/` and finding `RetrievalQAChain` learns nothing about the
author. Frameworks also own their object model (documents, nodes,
callbacks), which conflicts with the clean-architecture dependency rule this
repo enforces in CI: the domain and application layers import no frameworks,
and vendor SDKs appear only in the shared AI adapters.

## Decision

The core pipeline — parsing orchestration, chunking, embedding, hybrid
search, RRF (k=60), reranking, grounded generation, citation tracking — is
hand-built against our own ports. No LangChain, no LlamaIndex, no LangGraph.

**pydantic-ai** is permitted at the edges where an agent framework genuinely
helps and nothing is hidden: the LLM-as-judge in the evaluation module and,
in a later phase, query rewriting/decomposition. The pipeline itself stays
framework-free.

## Consequences

- Every retrieval decision (fusion constant, candidate counts, prompt
  shape) is explicit, configurable, and unit-tested in our code — the
  showcase is visible, and interview questions about it have first-hand
  answers.
- No framework-version churn in the critical path, and the import-linter
  contract "domain imports no frameworks" is actually satisfiable.
- Cost: we forgo the frameworks' breadth — dozens of loaders, retrievers,
  and integrations we would get for free. Each capability we want, we build
  or wrap ourselves (Docling for parsing is a library choice behind a
  `DocumentParser` port, not a framework takeover).
- We re-derive known patterns (RRF, retrieve-20/rerank/top-5) from the
  literature rather than inheriting tuned defaults; the eval suite exists to
  verify our implementation rather than trusting a framework's.

## Alternatives considered

- **LangChain / LlamaIndex** — rejected for the core: hides the engineering,
  owns the object model, and drags heavy transitive dependencies through the
  clean-architecture boundary.
- **LangGraph** — deferred, not rejected. It solves stateful multi-actor
  agent orchestration; v1's pipeline is a linear request flow with no state
  machine to manage. If the roadmap's agentic-retrieval spike (multi-hop,
  query decomposition with tool use) materializes, LangGraph is the first
  candidate for that layer — above the ports, never inside them.
- **Haystack** — same objection as LangChain with a smaller ecosystem.
