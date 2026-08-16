# ADR-008: Layered coverage gate — 100% core, ~85% overall

**Status:** Accepted 2026-08-16

## Context

A single flat coverage number is a weak signal. Flat 90% says nothing about
*where* the uncovered 10% lives — it may be the domain logic. Flat 100%
forces either testing trivial glue through mocks (noise) or maintaining
exclusion lists (which rot). Meanwhile the repo makes a specific
architectural claim: the domain and application layers are framework-free
and fully unit-testable without I/O. That claim should be measurable.

## Decision

Two `coverage report --fail-under` checks run in CI (and `make coverage`):

1. **100%** on `**/domain/` and `**/application/` — the framework-free core,
   unit-tested with hand-written fakes implementing the ports. No mocks of
   SQLAlchemy, no network, no exclusions.
2. **~85%** overall — adapters, presentation, and wiring are covered
   primarily by integration tests (testcontainers against real
   `pgvector/pgvector:pg17`) and contract tests (schemathesis), where
   line-coverage percentages are a secondary signal.

## Consequences

- The clean-architecture claim becomes falsifiable: if domain logic leaks
  into an adapter to dodge the 100% gate, import-linter catches the
  dependency direction and the coverage split makes the dodge visible.
- Test effort lands where it pays: exhaustive, fast, deterministic tests on
  the logic; realistic-environment tests on the edges.
- The 100% gate is strict by design — it forces domain code to stay small
  and pure, because every branch must be reachable from a unit test.
- Cost: two coverage invocations and a path convention to maintain; and
  ~85% overall can still hide untested adapter branches, which is why
  integration and contract suites are separate CI steps, not coverage
  substitutes.

## Alternatives considered

- **Flat 90%** — simpler, but erases the architectural signal the layered
  gate exists to broadcast.
- **Flat 100% with exclusions** — exclusion lists (`# pragma: no cover`,
  omit globs) accumulate silently and stop meaning anything.
- **No gate, coverage as information only** — honest in its own way, but
  gates are the repo's whole aesthetic: claims enforced in CI or not made.
