# ADR-001: Own the multi-provider seam — custom ports and adapters, not LiteLLM

**Status:** Accepted 2026-08-16

## Context

Pandu must call multiple LLM vendors (OpenAI, Google Gemini, DeepSeek at
launch) for three distinct capabilities — chat completion, embeddings, and
reranking — with provider switching by environment variable, an ordered
fallback chain, and per-call token/cost metering. The obvious shortcut is a
gateway SDK such as LiteLLM, which normalizes ~100 providers behind one
`completion()` call.

Two forces push the other way. First, this is a portfolio repo: the
multi-provider abstraction *is* one of the things being showcased, and a
third-party gateway would hide exactly the engineering worth demonstrating.
Second, the March 2026 PyPI supply-chain incident around LiteLLM is a live
reminder that a dependency sitting on the path of every API key and every
prompt is a concentrated risk; owning that seam is a defensible security
posture, not just pride of craft.

Capabilities also do not decompose uniformly across vendors: DeepSeek has no
embedding API at all, which means "the provider" is not one thing — chat,
embeddings, and reranking must be independently configurable.

## Decision

Define three narrow domain ports as Python `Protocol`s — `LLMProvider`
(`complete()` / `stream()`), `EmbeddingProvider` (`embed_batch()`), and
`Reranker` (`rerank()`) — and implement them with hand-written adapters over
the official vendor SDKs in `backend/src/app/shared/infrastructure/ai/`, the
only package allowed to import vendor SDKs (enforced by import-linter).

A `ProviderFactory` resolves `provider/model` env strings (e.g.
`AI_CHAT_MODEL=openai/gpt-4o-mini`, `AI_EMBED_MODEL=openai/text-embedding-3-small`)
at call time. A `FallbackChain` wraps the primary provider and fails over to
`AI_FALLBACK_MODEL` on provider errors. A `CostMeter` records token counts ×
a price table into Postgres (`llm_calls`) on every call. DeepSeek and any
OpenAI-compatible endpoint (Ollama, vLLM, Groq) ride the same
`OpenAICompatibleAdapter` with a custom base URL.

## Consequences

- Adding a vendor is one adapter file plus a price-table entry; nothing above
  the ports changes. This is the claim the repo exists to prove, and CI's
  architecture contracts make it checkable rather than aspirational.
- Chat, embedding, and judge models are configured independently, so
  asymmetric vendors (DeepSeek) are a config detail, not a special case.
- Cost tracking and fallback behavior are ours to test — unit tests exercise
  the chain with fake adapters, no network required.
- We accept the maintenance cost: SDK breaking changes are our problem, and
  we will always support fewer providers than LiteLLM. The long tail is
  mitigated by the OpenAI-compatible adapter, which covers most of it.
- We re-implement things a gateway gives for free (retries, price tables).
  The price table in particular must be kept current by hand.

## Alternatives considered

- **LiteLLM as the core abstraction** — rejected: hides the showcase, adds a
  large dependency on the credential path (supply-chain incident, Mar 2026),
  and its object model would leak into application code.
- **Hybrid: our ports with a LiteLLM-backed adapter** — viable later as the
  long-tail adapter behind the same `LLMProvider` port; rejected for v1 to
  keep the dependency surface minimal.
- **Single-vendor with abstract "someday" seams** — rejected: an abstraction
  with one implementation is untested by definition; launching with three
  vendors keeps the ports honest.
