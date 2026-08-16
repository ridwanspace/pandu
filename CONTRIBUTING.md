# Contributing

Pandu is a portfolio project, but it is run like a production repo: every
change goes through the same gates CI enforces. PRs are welcome; small,
focused ones get reviewed fastest.

## Dev loop

```bash
cp .env.example .env          # add at least one provider API key
make infra                    # postgres + redis in docker
make dev                      # migrations + uvicorn --reload on :8000
make worker                   # arq ingestion worker (second terminal)
make web                      # next dev on :3000 (third terminal)
```

`make up` runs the fully containerized stack instead. `make help` lists
everything.

## Quality gates

`make test` is the fast gate (run it before pushing); CI runs the full set:

| Gate | Command | What it enforces |
|---|---|---|
| Lint/format | `make lint` / `make fmt` | ruff check + format, bandit |
| Types | `make type` | `mypy --strict`, no exceptions |
| Architecture | `make arch` | import-linter contracts: layer order, module independence, SDKs only in `shared/infrastructure/ai` |
| Unit | `make unit` | No I/O; fakes implement the ports, never mocks of SQLAlchemy |
| Integration | `make integration` | testcontainers against real `pgvector/pgvector:pg17` |
| Contract | `make contract` | schemathesis against the OpenAPI schema |
| Coverage | `make coverage` | Layered: 100% on `domain/` + `application/`, 85% overall |
| Evals | `make evals` | Retrieval metrics + ragas on the golden set (costs tokens; nightly in CI) |

Conventions that reviews will hold you to: Python 3.13, full type hints,
`from __future__ import annotations`, frozen dataclasses in `domain/`,
Pydantic only at the edges, async everywhere, structlog with counts/ids
only (never prompt or document text), `Decimal` for money.

## ADR process

Any decision that changes architecture, a dependency on the credential
path, a quality gate, or a public contract gets an ADR:

1. Copy `docs/adr/ADR-000-template.md` to the next number
   (`ADR-011-short-title.md`).
2. Write Context / Decision / Consequences / Alternatives considered.
   Honest tradeoffs required — an ADR with no downsides gets bounced.
3. Open it in the same PR as the change it justifies. Status starts
   `Proposed`, flips to `Accepted <date>` on merge.
4. Never edit an accepted ADR's decision; supersede it with a new one and
   cross-link.

Eval thresholds follow a **tightening-only rule**: PRs may raise them, never
lower them. If a change drops a score below the gate, fix the change.
