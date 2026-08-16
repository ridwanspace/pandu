"""Evals HTTP endpoints. The /api/v1 prefix is added at mount time by the
composition root; this router only owns /evals.

POST /evals/run triggers the retrieval-only eval synchronously — it is
LLM-free and cheap (one embedding call per golden question), so a blocking
request is honest UX; judge/ragas evals cost tokens and stay CLI/CI-only.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.modules.evaluation.application.use_cases import ListEvalRuns, RunRetrievalEval
from app.modules.evaluation.presentation.schemas import EvalRunListOut, EvalRunOut, RunEvalIn


def build_router(*, list_runs: ListEvalRuns, run_retrieval: RunRetrievalEval) -> APIRouter:
    router = APIRouter(prefix="/evals", tags=["evals"])

    @router.get("/runs", response_model=EvalRunListOut)
    async def get_runs(
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> EvalRunListOut:
        runs = await list_runs(limit=limit)
        return EvalRunListOut(items=[EvalRunOut.from_entity(run) for run in runs])

    @router.post("/run", response_model=EvalRunOut, status_code=201)
    async def post_run(payload: RunEvalIn | None = None) -> EvalRunOut:
        run = await run_retrieval(k=payload.k if payload is not None else None)
        return EvalRunOut.from_entity(run)

    return router
