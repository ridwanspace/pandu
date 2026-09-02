"""QdrantSearchIndex unit tests — a fake in-memory client, no network, no SDK.

The fake stands in for both the client and the ``models`` namespace the adapter
uses to build filters, so these tests run with the ``qdrant`` extra absent.
"""

from __future__ import annotations

import builtins
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

import pytest

from app.modules.retrieval.domain.entities import ScoredChunk
from app.modules.retrieval.domain.search_index import SearchIndex
from app.modules.retrieval.infrastructure.qdrant_search_index import QdrantSearchIndex
from app.shared.domain.errors import InvalidInputError

if TYPE_CHECKING:
    from collections.abc import Sequence

DOC_A = UUID(int=1001)
DOC_B = UUID(int=1002)


# ── Fake Qdrant SDK surface ──────────────────────────────────────────────────


@dataclass(frozen=True)
class FakeMatchValue:
    value: Any


@dataclass(frozen=True)
class FakeMatchAny:
    any: list[Any]


@dataclass(frozen=True)
class FakeFieldCondition:
    key: str
    match: FakeMatchValue | FakeMatchAny


@dataclass(frozen=True)
class FakeFilter:
    must: list[FakeFieldCondition]


class FakeModels:
    """Mirrors the ``qdrant_client.http.models`` names the adapter touches."""

    MatchValue = FakeMatchValue
    MatchAny = FakeMatchAny
    FieldCondition = FakeFieldCondition
    Filter = FakeFilter


@dataclass(frozen=True)
class FakePoint:
    payload: dict[str, Any]
    score: float


@dataclass
class SearchCall:
    collection_name: str
    query_vector: list[float]
    query_filter: FakeFilter
    limit: int


@dataclass
class FakeQdrantClient:
    """In-memory stand-in: applies the adapter's own filter to stored points, so
    filter construction is exercised rather than mocked away."""

    points: list[FakePoint] = field(default_factory=list)
    calls: list[SearchCall] = field(default_factory=list)

    async def search(
        self,
        *,
        collection_name: str,
        query_vector: list[float],
        query_filter: FakeFilter,
        limit: int,
        with_payload: bool,
    ) -> list[FakePoint]:
        self.calls.append(SearchCall(collection_name, query_vector, query_filter, limit))
        matched = [p for p in self.points if _matches(p, query_filter)]
        return sorted(matched, key=lambda p: p.score, reverse=True)[:limit]


def _matches(point: FakePoint, query_filter: FakeFilter) -> bool:
    for condition in query_filter.must:
        actual = point.payload.get(condition.key)
        if isinstance(condition.match, FakeMatchValue):
            if actual != condition.match.value:
                return False
        elif str(actual) not in {str(v) for v in condition.match.any}:
            return False
    return True


# ── Fake lexical delegate ────────────────────────────────────────────────────


@dataclass
class LexicalCall:
    query: str
    limit: int
    document_ids: tuple[UUID, ...] | None


class FakeLexicalIndex:
    """The Postgres arm, as far as these tests are concerned."""

    def __init__(self, results: list[ScoredChunk] | None = None) -> None:
        self._results = results or []
        self.calls: list[LexicalCall] = []

    async def dense_search(
        self,
        embedding: Sequence[float],
        *,
        limit: int,
        document_ids: Sequence[UUID] | None = None,
    ) -> list[ScoredChunk]:
        raise AssertionError("dense_search must be served by Qdrant, never the delegate")

    async def lexical_search(
        self,
        query: str,
        *,
        limit: int,
        document_ids: Sequence[UUID] | None = None,
    ) -> list[ScoredChunk]:
        self.calls.append(
            LexicalCall(query, limit, tuple(document_ids) if document_ids is not None else None)
        )
        return self._results[:limit]


# ── Helpers ──────────────────────────────────────────────────────────────────


def point(
    n: int,
    *,
    document_id: UUID = DOC_A,
    status: str = "ready",
    score: float = 0.9,
    heading_path: Any = ("Intro", "Scope"),
) -> FakePoint:
    return FakePoint(
        payload={
            "chunk_id": str(UUID(int=n)),
            "document_id": str(document_id),
            "seq": n,
            "text": f"chunk text {n}",
            "filename": "doc.md",
            "heading_path": heading_path,
            "status": status,
        },
        score=score,
    )


def build(
    points: list[FakePoint] | None = None,
    *,
    delegate: FakeLexicalIndex | None = None,
) -> tuple[QdrantSearchIndex, FakeQdrantClient, FakeLexicalIndex]:
    client = FakeQdrantClient(points=points or [])
    lexical = delegate or FakeLexicalIndex()
    index = QdrantSearchIndex(
        lexical_delegate=lexical,
        collection="pandu_chunks",
        client=client,
        models=FakeModels,
    )
    return index, client, lexical


class TestDenseSearch:
    async def test_maps_payload_onto_scored_chunk(self) -> None:
        index, _, _ = build([point(1, score=0.75)])

        [chunk] = await index.dense_search([0.1, 0.2], limit=5)

        assert chunk == ScoredChunk(
            chunk_id=UUID(int=1),
            document_id=DOC_A,
            seq=1,
            text="chunk text 1",
            filename="doc.md",
            heading_path=("Intro", "Scope"),
            score=0.75,
        )

    async def test_heading_path_accepts_json_string_and_missing(self) -> None:
        index, _, _ = build(
            [
                point(1, heading_path='["A", "B"]', score=0.9),
                point(2, heading_path=None, score=0.8),
            ]
        )

        results = await index.dense_search([0.1], limit=5)

        assert [c.heading_path for c in results] == [("A", "B"), ()]

    async def test_passes_collection_vector_and_limit_through(self) -> None:
        index, client, _ = build([point(i) for i in range(1, 6)])

        await index.dense_search([0.1, 0.2, 0.3], limit=3)

        call = client.calls[0]
        assert call.collection_name == "pandu_chunks"
        assert call.query_vector == [0.1, 0.2, 0.3]
        assert call.limit == 3

    async def test_only_ready_documents_are_returned(self) -> None:
        index, _, _ = build(
            [
                point(1, status="ready"),
                point(2, status="processing"),
                point(3, status="failed"),
            ]
        )

        results = await index.dense_search([0.1], limit=10)

        assert [c.chunk_id for c in results] == [UUID(int=1)]

    async def test_points_without_a_status_field_are_invisible(self) -> None:
        """Fail-closed: an indexer that forgot ``status`` must not leak chunks."""
        stray = FakePoint(payload={**point(9).payload}, score=0.99)
        del stray.payload["status"]
        index, _, _ = build([stray, point(1)])

        results = await index.dense_search([0.1], limit=10)

        assert [c.chunk_id for c in results] == [UUID(int=1)]

    async def test_no_document_filter_sends_only_the_status_condition(self) -> None:
        index, client, _ = build([point(1)])

        await index.dense_search([0.1], limit=5)

        conditions = client.calls[0].query_filter.must
        assert [c.key for c in conditions] == ["status"]
        assert conditions[0].match == FakeMatchValue(value="ready")

    async def test_document_ids_narrow_the_result_set(self) -> None:
        index, client, _ = build(
            [point(1, document_id=DOC_A), point(2, document_id=DOC_B)],
        )

        results = await index.dense_search([0.1], limit=10, document_ids=[DOC_B])

        assert [c.document_id for c in results] == [DOC_B]
        conditions = client.calls[0].query_filter.must
        assert [c.key for c in conditions] == ["status", "document_id"]
        assert conditions[1].match == FakeMatchAny(any=[str(DOC_B)])

    async def test_empty_document_id_sequence_matches_nothing(self) -> None:
        index, _, _ = build([point(1), point(2, document_id=DOC_B)])

        assert await index.dense_search([0.1], limit=10, document_ids=[]) == []

    async def test_empty_index_returns_empty_list(self) -> None:
        index, _, _ = build([])

        assert await index.dense_search([0.1], limit=5) == []


class TestLexicalDelegation:
    async def test_delegates_verbatim_and_never_touches_qdrant(self) -> None:
        expected = [
            ScoredChunk(
                chunk_id=UUID(int=7),
                document_id=DOC_A,
                seq=7,
                text="lexical hit",
                filename="doc.md",
                heading_path=(),
                score=0.42,
            )
        ]
        delegate = FakeLexicalIndex(expected)
        index, client, lexical = build([point(1)], delegate=delegate)

        results = await index.lexical_search("what is RRF?", limit=4, document_ids=[DOC_B])

        assert results == expected
        assert lexical.calls == [LexicalCall("what is RRF?", 4, (DOC_B,))]
        assert client.calls == []

    async def test_none_document_ids_pass_through_as_none(self) -> None:
        index, _, lexical = build(delegate=FakeLexicalIndex([]))

        assert await index.lexical_search("q", limit=2) == []
        assert lexical.calls[0].document_ids is None


@pytest.fixture
def no_qdrant_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate the ``qdrant`` extra not being installed."""
    real_import = builtins.__import__

    def blocked(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("qdrant_client"):
            raise ImportError("No module named 'qdrant_client'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)


@pytest.mark.usefixtures("no_qdrant_sdk")
class TestLazyImport:
    """Without injected doubles the SDK import happens in ``__init__``; its
    absence must surface as an actionable message, not a bare ImportError."""

    def test_missing_extra_raises_actionable_error(self) -> None:
        with pytest.raises(InvalidInputError, match="uv sync --extra qdrant"):
            QdrantSearchIndex(
                lexical_delegate=FakeLexicalIndex(),
                collection="pandu_chunks",
            )

    def test_injected_client_still_needs_the_models_namespace(self) -> None:
        """A fake client alone is not enough: filters need ``models`` too, so the
        same actionable error fires unless it is injected as well."""
        with pytest.raises(InvalidInputError, match="uv sync --extra qdrant"):
            QdrantSearchIndex(
                lexical_delegate=FakeLexicalIndex(),
                collection="pandu_chunks",
                client=FakeQdrantClient(),
            )

    def test_fully_injected_doubles_need_no_sdk_at_all(self) -> None:
        index, _, _ = build([point(1)])
        assert index is not None


def test_adapter_conforms_to_the_search_index_port() -> None:
    """Structural conformance, enforced by mypy on these assignments: both the
    adapter and the fake delegate must match the SearchIndex protocol."""
    delegate: SearchIndex = FakeLexicalIndex()
    index: SearchIndex = QdrantSearchIndex(
        lexical_delegate=delegate,
        collection="pandu_chunks",
        client=FakeQdrantClient(),
        models=FakeModels,
    )
    assert index is not None
