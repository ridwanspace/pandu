"""Eval harness CLI.

Run from ``backend/``:

    uv run python -m evals.run --retrieval-only    # LLM-free, deterministic
    uv run python -m evals.run                     # + LLM-as-judge (costs tokens)
    uv run --group eval python -m evals.run --ragas  # + ragas generation metrics

This script is its own minimal composition root: it wires the *live* retrieval
pipeline (real Postgres, real embedding provider) because scoring anything
else would be scoring a different system than the one users hit. Tracing and
reranking are intentionally no-op here — eval scores must not depend on
optional observability infra, and the reranker is a quality knob evaluated by
sweeping config, not a baseline dependency.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from app.config import Settings, get_settings
from app.modules.evaluation.application.use_cases import RunJudgeEval, RunRetrievalEval
from app.modules.evaluation.infrastructure.dataset_files import golden_dataset_loader
from app.modules.evaluation.infrastructure.repositories import PostgresEvalRunRepository
from app.modules.retrieval.application.use_cases import RetrieveContext
from app.modules.retrieval.infrastructure.pg_search_index import PostgresSearchIndex
from app.shared.infrastructure.ai.factory import ProviderFactory
from app.shared.infrastructure.ai.rerankers import NoopReranker
from app.shared.infrastructure.ai.tracing import NoopTracer
from app.shared.infrastructure.db.engine import build_engine, build_session_factory

if TYPE_CHECKING:
    from app.modules.evaluation.domain.entities import EvalRun

# ── Thresholds — TIGHTENING-ONLY (blueprint §6) ──────────────────────────────
# These floors may only ever be RAISED, never lowered. If a change drops a
# metric below its floor, fix the pipeline or consciously revert the change;
# loosening a gate to make CI green defeats the point of having one.
RECALL_AT_K_MIN = 0.60  # retrieval recall@5 over golden_v1
FAITHFULNESS_MIN = 0.85  # LLM-judge / ragas faithfulness
CONTEXT_PRECISION_MIN = 0.75  # ragas context precision

GOLDEN_PATH = Path(__file__).resolve().parent / "golden" / "golden_v1.jsonl"
DATASET_VERSION = "golden_v1"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m evals.run",
        description="Score the retrieval pipeline against the golden dataset.",
    )
    parser.add_argument(
        "--retrieval-only",
        action="store_true",
        help="skip the LLM-as-judge run (retrieval metrics are LLM-free)",
    )
    parser.add_argument(
        "--ragas",
        action="store_true",
        help="also run the ragas generation-metric suite (requires --group eval)",
    )
    parser.add_argument("--k", type=int, default=5, help="recall horizon (default: 5)")
    return parser.parse_args(argv)


def _print_metrics(title: str, metrics: dict[str, float]) -> None:
    print(f"\n{title}")
    print(f"  {'metric':<24}{'value':>10}")
    for name, value in sorted(metrics.items()):
        print(f"  {name:<24}{value:>10.4f}")


def _gate(name: str, value: float, minimum: float, failures: list[str]) -> None:
    passed = value >= minimum
    print(f"  {name:<24}{value:>10.4f}  >= {minimum:.2f}  {'PASS' if passed else 'FAIL'}")
    if not passed:
        failures.append(name)


def _build_retrieve(
    settings: Settings, factory: ProviderFactory, index: PostgresSearchIndex, *, top_k: int
) -> RetrieveContext:
    return RetrieveContext(
        embedder=factory.build_embeddings(settings.ai_embed_model),
        index=index,
        reranker=NoopReranker(),
        tracer=NoopTracer(),
        candidates=settings.retrieval_candidates,
        top_k=top_k,
        rrf_k=settings.rrf_k,
    )


async def _amain(args: argparse.Namespace) -> int:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    failures: list[str] = []
    try:
        session_factory = build_session_factory(engine)
        factory = ProviderFactory(settings)
        loader = golden_dataset_loader(GOLDEN_PATH)
        runs = PostgresEvalRunRepository(session_factory)
        retrieve = _build_retrieve(
            settings, factory, PostgresSearchIndex(session_factory), top_k=args.k
        )
        config = {
            "embed_model": settings.ai_embed_model,
            "reranker": "none",
            "candidates": str(settings.retrieval_candidates),
            "rrf_k": str(settings.rrf_k),
        }

        retrieval_eval = RunRetrievalEval(
            retrieve=retrieve,
            runs=runs,
            dataset_loader=loader,
            k=args.k,
            dataset_version=DATASET_VERSION,
            config=config,
        )
        retrieval_run: EvalRun = await retrieval_eval()
        _print_metrics(f"Retrieval metrics ({DATASET_VERSION}, k={args.k})", retrieval_run.metrics)
        print("\nGates (tightening-only):")
        _gate(f"recall@{args.k}", retrieval_run.metrics["recall_at_k"], RECALL_AT_K_MIN, failures)

        if not args.retrieval_only:
            judge_model = settings.ai_judge_model or settings.ai_chat_model
            judge_eval = RunJudgeEval(
                judge=factory.build_llm(judge_model),
                retrieve=retrieve,
                runs=runs,
                dataset_loader=loader,
                dataset_version=DATASET_VERSION,
                config={**config, "judge_model": judge_model},
            )
            judge_run = await judge_eval()
            _print_metrics(f"Judge metrics ({judge_run.dataset_version})", judge_run.metrics)
            print("\nGates (tightening-only):")
            _gate("faithfulness", judge_run.metrics["faithfulness"], FAITHFULNESS_MIN, failures)

        if args.ragas:
            from evals.ragas_runner import run_ragas

            ragas_scores = await run_ragas(
                retrieve=retrieve,
                chat=factory.build_llm(settings.ai_chat_model),
                examples=loader(),
                judge_model=settings.ai_judge_model or settings.ai_chat_model,
                openai_api_key=settings.openai_api_key,
            )
            if ragas_scores is not None:
                _print_metrics("ragas metrics", ragas_scores)
                print("\nGates (tightening-only):")
                _gate("faithfulness", ragas_scores["faithfulness"], FAITHFULNESS_MIN, failures)
                _gate(
                    "context_precision",
                    ragas_scores["context_precision"],
                    CONTEXT_PRECISION_MIN,
                    failures,
                )
    finally:
        await engine.dispose()

    if failures:
        print(f"\nFAILED: {', '.join(failures)} below threshold", file=sys.stderr)
        return 1
    print("\nAll gates passed.")
    return 0


def main(argv: list[str] | None = None) -> None:
    raise SystemExit(asyncio.run(_amain(_parse_args(argv))))


if __name__ == "__main__":
    main()
