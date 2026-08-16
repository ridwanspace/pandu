# ADR-005: Plain two-folder monorepo — no Nx, no Turborepo

**Status:** Accepted 2026-08-16

## Context

The repo holds two toolchains: a Python backend (uv) and a Next.js frontend
(pnpm). Monorepo frameworks (Nx, Turborepo) offer task graphs, remote
caching, and affected-only builds — features that pay off when many packages
share a language and a dependency graph.

Here there are exactly two projects, in different languages, with no shared
build artifacts except one generated file: the TypeScript API client emitted
from the FastAPI OpenAPI schema.

## Decision

A plain monorepo: `backend/` (uv project) and `frontend/` (pnpm project)
side by side, coordinated by a root `Makefile` and `docker-compose.yml`.
Cross-project consistency is enforced where it actually matters — CI
regenerates the OpenAPI client and fails on drift.

## Consequences

- Zero monorepo-tool configuration, upgrades, or cache debugging. Each
  toolchain stays idiomatic (`uv run ...`, `pnpm ...`), and the Makefile is
  the single discoverable entry point.
- CI splits naturally into `backend.yml`, `frontend.yml`, and `evals.yml`
  with path filters — affected-only builds without a task graph.
- The contract between the halves is the OpenAPI schema, checked in CI —
  stronger than a shared-types package because it tests the wire format,
  not just TypeScript declarations.
- If the repo ever grows real shared packages (a design system, a second
  service), this decision should be revisited; at two projects it is pure
  overhead avoided.

## Alternatives considered

- **Turborepo** — pleasant task caching, but it is a JS-ecosystem tool
  wrapping a mostly-Python repo; the cache would help exactly one project.
- **Nx** — same, with more machinery and a plugin model to maintain.
- **Two separate repos** — rejected: the API contract check and the
  single-command quickstart (`make up`) both depend on one checkout being
  the whole system.
