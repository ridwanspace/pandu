# ADR-009: Biome for frontend lint and format

**Status:** Accepted 2026-08-16

## Context

The frontend (Next.js 16, TypeScript strict) needs linting and formatting.
The incumbent stack is ESLint 9 + Prettier: maximal ecosystem coverage,
including Next.js-specific rules (`eslint-config-next`) and TanStack Query
lint plugins, at the price of two tools, two configs, plugin-compatibility
churn (flat config migration), and noticeably slower runs.

Biome is a single Rust binary doing both jobs — format plus lint with React
hooks rules, a11y rules, and import sorting — orders of magnitude faster,
one config file.

## Decision

**Biome** is the only frontend lint/format tool. CI runs `biome check`;
type-level correctness is `tsc --noEmit`; framework-level mistakes are
caught by Vitest, Playwright, and `next build` rather than lint rules.

## Consequences

- One fast tool: near-instant pre-commit and CI feedback, no
  plugin-resolution debugging, and a modern-tooling signal consistent with
  the backend's ruff-only choice (same consolidation logic, same reasoning).
- Accepted tradeoff, stated plainly: **no Next.js-specific lint rules**
  (no `next/no-img-element`-class checks) and **no TanStack Query plugin**
  (no `exhaustive-deps`-for-queries). Those bug classes must be caught by
  review, tests, and `next build` warnings instead.
- If a lost rule class starts producing real bugs, the fallback is a
  minimal ESLint running *only* those plugins beside Biome — deliberately
  not done now to avoid reconciling two toolchains without evidence of
  need.

## Alternatives considered

- **ESLint 9 + Prettier** — full rule coverage, but slower, two configs,
  and ongoing flat-config/plugin churn; the coverage delta didn't justify
  the drag for a repo this size.
- **Biome + minimal ESLint hybrid** — best-of-both on paper, but two
  overlapping toolchains to keep from fighting each other; deferred until a
  concrete rule gap hurts.
