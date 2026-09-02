"""Configuration sweep — turn retrieval knobs into measured evidence.

ADR-010 defers the reranker to a no-op default and promises the eval suite
will quantify what turning it on buys. This is that harness. It replays the
golden set through the live retrieval pipeline once per configuration and
prints one comparison table.

Run from ``backend/``::

    uv run python -m evals.sweep                      # arms: hybrid vs dense vs lexical
    uv run python -m evals.sweep --rerankers none,cohere,jina
    uv run python -m evals.sweep --k 1,3,5,10         # recall horizon sweep

Two things this exists to expose that a single-number eval cannot:

- **Whether reranking earns its latency.** The rerank arm costs a network hop
  per query; the table prints ``rerank_ms`` next to the quality delta so the
  trade is visible rather than assumed.
- **Whether hybrid actually beats its own arms.** Fusing dense and lexical is
  a hypothesis, not a law: RRF weights both arms equally, so a strong embedder
  paired with a weak lexical arm can score *worse* fused than dense alone.
  Isolating the arms is the only way to find that out on this corpus.

Every row is a real run against real Postgres and the configured embedding
provider — the same pipeline the chat endpoint uses.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from app.config import Settings, get_settings
from app.modules.evaluation.domain.matching import matched_source
from app.modules.evaluation.domain.metrics import aggregate
from app.modules.evaluation.infrastructure.dataset_files import golden_dataset_loader
from app.modules.retrieval.application.dto import RetrievalQuery
from app.modules.retrieval.application.use_cases import RetrieveContext
from app.modules.retrieval.domain.search_index import SearchIndex
from app.modules.retrieval.infrastructure.pg_search_index import PostgresSearchIndex
from app.shared.infrastructure.ai.factory import ProviderFactory
from app.shared.infrastructure.ai.tracing import NoopTracer
from app.shared.infrastructure.db.engine import build_engine, build_session_factory

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from app.modules.evaluation.domain.entities import GoldenExample
    from app.modules.retrieval.domain.entities import RankedChunk, ScoredChunk

GOLDEN_PATH = Path(__file__).resolve().parent / "golden" / "golden_v2.jsonl"


class _SingleArmIndex:
    """Wraps a SearchIndex, silencing one arm so the other can be scored alone.

    Returning an empty list is exactly what RRF sees when an arm finds nothing,
    so the fusion code path stays identical — this isolates the *arm*, not the
    pipeline.
    """

    def __init__(self, inner: SearchIndex, *, arm: str) -> None:
        self._inner = inner
        self._arm = arm

    async def dense_search(
        self,
        embedding: Sequence[float],
        *,
        limit: int,
        document_ids: Sequence[UUID] | None = None,
    ) -> list[ScoredChunk]:
        if self._arm == "lexical":
            return []
        return await self._inner.dense_search(embedding, limit=limit, document_ids=document_ids)

    async def lexical_search(
        self,
        query: str,
        *,
        limit: int,
        document_ids: Sequence[UUID] | None = None,
    ) -> list[ScoredChunk]:
        if self._arm == "dense":
            return []
        return await self._inner.lexical_search(query, limit=limit, document_ids=document_ids)


@dataclass(frozen=True, slots=True)
class SweepRow:
    """One configuration's scores, ready to print."""

    arm: str
    reranker: str
    k: int
    recall: float
    precision: float
    mrr: float
    ndcg: float
    hit_rate: float
    mean_latency_ms: float


def _retrieved_ids(example: GoldenExample, chunks: Sequence[RankedChunk]) -> tuple[str, ...]:
    """Mirror of the eval use case's id mapping (misses consume rank slots)."""
    ids: list[str] = []
    for position, chunk in enumerate(chunks):
        matched = matched_source(
            filename=chunk.filename,
            text=chunk.text,
            heading_path=chunk.heading_path,
            source_files=example.source_files,
            source_hints=example.source_hints,
        )
        ids.append(matched if matched is not None else f"__miss_{position}")
    return tuple(ids)


async def _score_config(
    *,
    examples: tuple[GoldenExample, ...],
    settings: Settings,
    factory: ProviderFactory,
    index: SearchIndex,
    arm: str,
    reranker_kind: str,
    k: int,
    rerank_rpm: int = 0,
) -> SweepRow:
    retrieve = RetrieveContext(
        embedder=factory.build_embeddings(settings.ai_embed_model),
        index=_SingleArmIndex(index, arm=arm) if arm != "hybrid" else index,
        reranker=factory.build_reranker(reranker_kind),
        tracer=NoopTracer(),
        candidates=settings.retrieval_candidates,
        top_k=k,
        rrf_k=settings.rrf_k,
    )
    results: list[tuple[frozenset[str], tuple[str, ...]]] = []
    latencies: list[int] = []
    # Throttling only matters when a hosted reranker is in play; the LLM-free
    # arms are limited by Postgres, not by anyone's quota.
    min_gap = 60.0 / rerank_rpm if (rerank_rpm > 0 and reranker_kind != "none") else 0.0
    for position, example in enumerate(examples):
        if min_gap and position:
            await asyncio.sleep(min_gap)
        context = await retrieve(RetrievalQuery(text=example.question))
        results.append((frozenset(example.source_files), _retrieved_ids(example, context.chunks)))
        latencies.append(
            context.embed_latency_ms + context.search_latency_ms + context.rerank_latency_ms
        )
    scores = aggregate(results, k=k)
    return SweepRow(
        arm=arm,
        reranker=reranker_kind,
        k=k,
        recall=scores.recall_at_k,
        precision=scores.precision_at_k,
        mrr=scores.mrr,
        ndcg=scores.ndcg_at_k,
        hit_rate=scores.hit_rate_at_k,
        mean_latency_ms=sum(latencies) / len(latencies),
    )


def _print_table(rows: Sequence[SweepRow]) -> None:
    header = (
        f"{'arm':<9}{'reranker':<10}{'k':>3}"
        f"{'recall':>9}{'prec':>8}{'MRR':>8}{'nDCG':>8}{'hit':>7}{'ms':>8}"
    )
    print("\n" + header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row.arm:<9}{row.reranker:<10}{row.k:>3}"
            f"{row.recall:>9.3f}{row.precision:>8.3f}{row.mrr:>8.3f}"
            f"{row.ndcg:>8.3f}{row.hit_rate:>7.3f}{row.mean_latency_ms:>8.0f}"
        )


def _print_verdict(rows: Sequence[SweepRow]) -> None:
    """State the comparison in words, so the table cannot be read wishfully."""
    baseline = next((r for r in rows if r.arm == "hybrid" and r.reranker == "none"), None)
    if baseline is None:
        return
    print("\nVerdict (vs hybrid/none baseline):")
    for row in rows:
        if row is baseline or row.k != baseline.k:
            continue
        delta = row.ndcg - baseline.ndcg
        cost = row.mean_latency_ms - baseline.mean_latency_ms
        direction = "better" if delta > 0 else "worse" if delta < 0 else "no change"
        print(
            f"  {row.arm}/{row.reranker:<8} nDCG {delta:+.3f} ({direction}), latency {cost:+.0f} ms"
        )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m evals.sweep",
        description="Sweep retrieval configurations over the golden dataset.",
    )
    parser.add_argument(
        "--arms", default="hybrid,dense,lexical", help="comma-separated: hybrid,dense,lexical"
    )
    parser.add_argument(
        "--rerankers", default="none", help="comma-separated: none,cohere,jina,local"
    )
    parser.add_argument("--k", default="5", help="comma-separated recall horizons (default: 5)")
    parser.add_argument(
        "--rerank-rpm",
        type=int,
        default=0,
        help=(
            "throttle reranker calls to N per minute (0 = no throttle). "
            "Hosted free tiers are strict — Cohere's trial key allows 10/min, "
            "which a 15-example sweep exceeds"
        ),
    )
    return parser.parse_args(argv)


async def _amain(args: argparse.Namespace) -> int:
    settings = get_settings()
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    rerankers = [r.strip() for r in args.rerankers.split(",") if r.strip()]
    ks = [int(k.strip()) for k in args.k.split(",") if k.strip()]

    engine = build_engine(settings.database_url)
    try:
        session_factory = build_session_factory(engine)
        factory = ProviderFactory(settings)
        index = PostgresSearchIndex(session_factory)
        # Negatives have no source files, so rank metrics are undefined for
        # them; the sweep measures ranking only.
        examples = tuple(e for e in golden_dataset_loader(GOLDEN_PATH)() if e.answerable)

        print(
            f"Sweeping {len(arms) * len(rerankers) * len(ks)} configurations "
            f"over {len(examples)} answerable examples "
            f"(embed={settings.ai_embed_model}, candidates={settings.retrieval_candidates}, "
            f"rrf_k={settings.rrf_k})"
        )
        rows: list[SweepRow] = []
        for k in ks:
            for arm in arms:
                for reranker_kind in rerankers:
                    rows.append(
                        await _score_config(
                            examples=examples,
                            settings=settings,
                            factory=factory,
                            index=index,
                            arm=arm,
                            reranker_kind=reranker_kind,
                            k=k,
                            rerank_rpm=args.rerank_rpm,
                        )
                    )
        _print_table(rows)
        _print_verdict(rows)
    finally:
        await engine.dispose()
    return 0


def main(argv: list[str] | None = None) -> None:
    raise SystemExit(asyncio.run(_amain(_parse_args(argv))))


if __name__ == "__main__":
    main()
