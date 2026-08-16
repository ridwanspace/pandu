"""Retrieval HTTP surface — a transparency endpoint that exposes the hybrid
pipeline's internals (per-arm ranks, fused and rerank scores) for the demo UI
and for debugging retrieval quality. Mounted under /api/v1 by the bootstrap."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, status

from app.modules.retrieval.application.dto import RetrievalQuery
from app.modules.retrieval.presentation.schemas import SearchItem, SearchRequest, SearchResponse
from app.shared.domain.errors import InvalidInputError

if TYPE_CHECKING:
    from app.modules.retrieval.application.use_cases import RetrieveContext


def build_router(retrieve: RetrieveContext) -> APIRouter:
    router = APIRouter(prefix="/retrieval", tags=["retrieval"])

    @router.post("/search", response_model=SearchResponse)
    async def search(payload: SearchRequest) -> SearchResponse:
        query = RetrievalQuery(
            text=payload.query,
            document_ids=tuple(payload.document_ids) if payload.document_ids else None,
        )
        try:
            context = await retrieve(query)
        except InvalidInputError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        return SearchResponse(items=[SearchItem.from_domain(chunk) for chunk in context.chunks])

    return router
