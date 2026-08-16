"""Documents module — HTTP endpoints.

``build_router`` is called by the composition root with wired use cases;
auth and rate-limit dependencies are attached at mount time, and the
``/api/v1`` prefix is added there too.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, UploadFile, status

from app.modules.documents.application.use_cases import (
    DeleteDocument,
    GetDocument,
    ListDocuments,
    PreviewChunks,
    UploadDocument,
)
from app.modules.documents.presentation.schemas import (
    ChunkListOut,
    ChunkOut,
    DocumentListOut,
    DocumentOut,
    UploadAcceptedOut,
)
from app.shared.domain.errors import InvalidInputError, NotFoundError


def build_router(
    *,
    upload_document: UploadDocument,
    list_documents: ListDocuments,
    get_document: GetDocument,
    delete_document: DeleteDocument,
    preview_chunks: PreviewChunks,
) -> APIRouter:
    router = APIRouter(prefix="/documents", tags=["documents"])

    @router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=UploadAcceptedOut)
    async def upload(file: UploadFile) -> UploadAcceptedOut:
        content = await file.read()
        try:
            document = await upload_document(
                filename=file.filename or "upload",
                content_type=file.content_type or "application/octet-stream",
                content=content,
            )
        except InvalidInputError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return UploadAcceptedOut.from_domain(document)

    @router.get("", response_model=DocumentListOut)
    async def list_all() -> DocumentListOut:
        documents = await list_documents()
        return DocumentListOut(items=[DocumentOut.from_domain(d) for d in documents])

    @router.get("/{document_id}", response_model=DocumentOut)
    async def get_one(document_id: UUID) -> DocumentOut:
        try:
            document = await get_document(document_id)
        except NotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return DocumentOut.from_domain(document)

    @router.get("/{document_id}/chunks", response_model=ChunkListOut)
    async def chunks(
        document_id: UUID,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> ChunkListOut:
        try:
            items = await preview_chunks(document_id, limit=limit)
        except NotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return ChunkListOut(items=[ChunkOut.from_domain(c) for c in items])

    @router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_one(document_id: UUID) -> Response:
        try:
            await delete_document(document_id)
        except NotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
