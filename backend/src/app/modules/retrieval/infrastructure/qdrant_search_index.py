"""Optional Qdrant SearchIndex adapter — proof that the port is honest (ADR-002).

Default OFF. Postgres stays the shipped default and the measured baseline;
this module exists so the ADR-002 claim ("a Qdrant adapter is a file, not a
rewrite") can be checked rather than believed.

**Honest limitation — Qdrant replaces only the DENSE arm.** Qdrant's core API
has no BM25/full-text ranking, so this adapter cannot implement a lexical arm.
It does not fake one and it does not silently return ``[]`` (which would quietly
halve hybrid recall while every dashboard still said "hybrid"). Instead it takes
a ``lexical_delegate: SearchIndex`` and forwards ``lexical_search`` to it —
Postgres FTS remains the lexical arm. A "Qdrant deployment" is therefore
Qdrant-dense + Postgres-lexical, not Qdrant-only. Saying otherwise would
misdescribe what was built.

**The ``ready`` invariant.** The Postgres adapter joins ``documents`` and filters
``d.status = 'ready'`` so a half-ingested document can never leak partial
context. Qdrant has no join, so the invariant moves into the payload: the
indexer must stamp each point with ``status`` and this adapter always ANDs
``status == "ready"`` into the query filter. Points written without that field
are invisible to search — fail-closed, which is the safe direction.

The client import is deferred to the constructor (like
``LocalCrossEncoderReranker``): the dependency lives behind the ``qdrant``
extra, so the base image never needs it and its absence fails with an
actionable message instead of an ImportError at startup.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.modules.retrieval.domain.entities import ScoredChunk
from app.shared.domain.errors import InvalidInputError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.modules.retrieval.domain.search_index import SearchIndex

_READY_STATUS = "ready"

_DEFAULT_TIMEOUT_SECONDS = 30.0


def _to_heading_path(raw: Any) -> tuple[str, ...]:
    """``heading_path`` arrives as a JSON array in the payload; tolerate a raw
    JSON string too (some indexers store it encoded)."""
    value = json.loads(raw) if isinstance(raw, str) else raw
    if value is None:
        return ()
    return tuple(str(part) for part in value)


def _to_uuid(value: Any) -> UUID:
    """Payload ids come back as ``UUID`` or ``str`` depending on the indexer."""
    return value if isinstance(value, UUID) else UUID(str(value))


def _to_scored_chunk(point: Any) -> ScoredChunk:
    """Map a Qdrant scored point onto the SAME ScoredChunk shape the Postgres
    adapter returns — the port's contract is the entity, not the row source."""
    payload: dict[str, Any] = point.payload or {}
    return ScoredChunk(
        chunk_id=_to_uuid(payload["chunk_id"]),
        document_id=_to_uuid(payload["document_id"]),
        seq=int(payload["seq"]),
        text=str(payload["text"]),
        filename=str(payload["filename"]),
        heading_path=_to_heading_path(payload.get("heading_path")),
        score=float(point.score),
    )


_MISSING_EXTRA = (
    "qdrant-client is not installed; SEARCH_INDEX=qdrant requires the "
    "'qdrant' extra (uv sync --extra qdrant)"
)


def _import_client() -> Any:
    """Deferred so the base image never needs the dependency, and its absence
    fails with an actionable message instead of an ImportError at startup."""
    try:
        from qdrant_client import AsyncQdrantClient
    except ImportError as exc:
        raise InvalidInputError(_MISSING_EXTRA) from exc
    return AsyncQdrantClient


def _import_models() -> Any:
    """The ``models`` namespace used to build payload filters."""
    try:
        from qdrant_client.http import models
    except ImportError as exc:
        raise InvalidInputError(_MISSING_EXTRA) from exc
    return models


class QdrantSearchIndex:
    """SearchIndex adapter: Qdrant for dense, an injected delegate for lexical.

    ``client`` (and the ``models`` namespace used to build filters) are
    injectable so unit tests can pass an in-memory fake — no network, no
    container, and no need for the extra to be installed. Without them the real
    ``qdrant_client`` is imported here and the client constructed.
    """

    def __init__(
        self,
        *,
        lexical_delegate: SearchIndex,
        collection: str,
        url: str = "http://localhost:6333",
        api_key: str = "",
        client: Any | None = None,
        models: Any | None = None,
    ) -> None:
        self._lexical_delegate = lexical_delegate
        self._collection = collection
        self._models: Any = models if models is not None else _import_models()
        if client is None:
            client = _import_client()(
                url=url, api_key=api_key or None, timeout=int(_DEFAULT_TIMEOUT_SECONDS)
            )
        self._client: Any = client

    async def dense_search(
        self,
        embedding: Sequence[float],
        *,
        limit: int,
        document_ids: Sequence[UUID] | None = None,
    ) -> list[ScoredChunk]:
        """Cosine ANN over the collection, always filtered to ready documents
        and optionally narrowed to a document subset."""
        points = await self._client.search(
            collection_name=self._collection,
            query_vector=list(embedding),
            query_filter=self._build_filter(document_ids),
            limit=limit,
            with_payload=True,
        )
        return [_to_scored_chunk(point) for point in points]

    async def lexical_search(
        self,
        query: str,
        *,
        limit: int,
        document_ids: Sequence[UUID] | None = None,
    ) -> list[ScoredChunk]:
        """Delegated verbatim — see the module docstring: Qdrant has no BM25, so
        the lexical arm stays on Postgres FTS rather than being faked."""
        return await self._lexical_delegate.lexical_search(
            query, limit=limit, document_ids=document_ids
        )

    def _build_filter(self, document_ids: Sequence[UUID] | None) -> Any:
        """``status == 'ready'`` always; ``document_id IN (...)`` when scoped."""
        models = self._models
        conditions = [
            models.FieldCondition(key="status", match=models.MatchValue(value=_READY_STATUS))
        ]
        if document_ids is not None:
            conditions.append(
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchAny(any=[str(doc_id) for doc_id in document_ids]),
                )
            )
        return models.Filter(must=conditions)
