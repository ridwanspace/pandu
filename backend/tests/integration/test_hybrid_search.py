"""Hybrid retrieval against a real pgvector/FTS database — the showcase suite.

Embeddings are unit vectors at hand-chosen angles (see ``support.vector_at``),
so cosine similarity to the query vector is ``cos(angle)`` and every dense
ranking below is computable on paper. Lexical texts are crafted so that term
frequency, OR ranking, and phrase adjacency each decide exactly one case.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from uuid import UUID

import pytest

from app.modules.documents.domain.entities import Chunk, Document, DocumentStatus
from app.modules.documents.infrastructure.repositories import (
    PostgresChunkRepository,
    PostgresDocumentRepository,
)
from app.modules.retrieval.application.dto import RetrievalQuery
from app.modules.retrieval.application.use_cases import RetrieveContext
from app.modules.retrieval.infrastructure.pg_search_index import PostgresSearchIndex
from app.shared.infrastructure.ai.rerankers import NoopReranker
from app.shared.infrastructure.ai.tracing import NoopTracer
from tests.integration.support import (
    SessionFactory,
    StaticEmbedder,
    chunk_ids_by_seq,
    make_document,
    vector_at,
)

# One entry per seeded chunk: (text, embedding angle). The query vector sits at
# angle 0.0, so dense similarity is cos(angle): smaller angle = better match.
_DOC_A_CHUNKS = [
    # seq 0 — dense #1 AND lexical #1 for "vacuum" (three occurrences).
    ("Postgres vacuum reclaims dead tuples. Vacuum prevents bloat. Run vacuum weekly.", 0.1),
    # seq 1 — "autovacuum" does not stem to "vacuum": lexical miss by design.
    ("The autovacuum daemon schedules maintenance in the background.", 0.4),
    # seq 2 — contains both "index" and "tuning": outranks a partial match.
    ("Index tuning improves query performance in Postgres.", 0.8),
    # seq 3 — "exclusive lock" adjacent: matches the quoted-phrase query.
    ("An update statement acquires an exclusive lock on the modified row.", 1.2),
]
_DOC_B_CHUNKS = [
    # seq 0 — dense #2, no query keywords.
    ("Redis keeps its dataset in memory for fast lookups.", 0.2),
    # seq 1 — one "vacuum": ranks below doc A seq 0 by ts_rank_cd.
    ("A vacuum truck cleans the streets outside the office.", 1.4),
    # seq 2 — "exclusive ... lock" NOT adjacent: quoted phrase must skip it.
    ("The exclusive table lock blocks concurrent writers.", 1.0),
    # seq 3 — "index" without "tuning": a partial match, ranked but not top.
    ("Index rebuilds can be scheduled at night.", 0.6),
]
# Would win both arms if status filtering leaked non-ready documents.
_DOC_C_CHUNKS = [("Vacuum vacuum vacuum: the best vacuum chunk ever written.", 0.05)]

_QUERY_VECTOR = vector_at(0.0)


@dataclass(frozen=True)
class Corpus:
    doc_a: Document
    doc_b: Document
    doc_c: Document
    ids_a: dict[int, UUID]
    ids_b: dict[int, UUID]
    ids_c: dict[int, UUID]


async def _seed(
    session_factory: SessionFactory,
    document: Document,
    spec: list[tuple[str, float]],
) -> dict[int, UUID]:
    documents = PostgresDocumentRepository(session_factory)
    chunks = PostgresChunkRepository(session_factory)
    await documents.add(document)
    await chunks.replace_for_document(
        document.id,
        [
            Chunk(
                document_id=document.id,
                seq=seq,
                text=chunk_text,
                token_count=len(chunk_text.split()),
                heading_path=(document.filename, f"s{seq}"),
            )
            for seq, (chunk_text, _) in enumerate(spec)
        ],
        [vector_at(angle) for _, angle in spec],
    )
    return await chunk_ids_by_seq(session_factory, document.id)


@pytest.fixture
async def corpus(session_factory: SessionFactory) -> Corpus:
    doc_a = make_document(filename="postgres_guide.md")
    doc_b = make_document(filename="redis_notes.md")
    doc_c = make_document(filename="draft.md", status=DocumentStatus.EMBEDDING)
    return Corpus(
        doc_a=doc_a,
        doc_b=doc_b,
        doc_c=doc_c,
        ids_a=await _seed(session_factory, doc_a, _DOC_A_CHUNKS),
        ids_b=await _seed(session_factory, doc_b, _DOC_B_CHUNKS),
        ids_c=await _seed(session_factory, doc_c, _DOC_C_CHUNKS),
    )


class TestDenseSearch:
    async def test_orders_by_cosine_similarity(
        self, session_factory: SessionFactory, corpus: Corpus
    ) -> None:
        index = PostgresSearchIndex(session_factory)

        results = await index.dense_search(_QUERY_VECTOR, limit=10)

        # Angles ascending: a0(0.1), b0(0.2), a1(0.4), b3(0.6), a2(0.8),
        # b2(1.0), a3(1.2), b1(1.4). The non-ready c0(0.05) must not appear.
        expected = [
            corpus.ids_a[0],
            corpus.ids_b[0],
            corpus.ids_a[1],
            corpus.ids_b[3],
            corpus.ids_a[2],
            corpus.ids_b[2],
            corpus.ids_a[3],
            corpus.ids_b[1],
        ]
        assert [r.chunk_id for r in results] == expected
        angles = [0.1, 0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4]
        for result, angle in zip(results, angles, strict=True):
            assert result.score == pytest.approx(math.cos(angle), abs=1e-4)
        assert results[0].filename == "postgres_guide.md"
        assert results[0].heading_path == ("postgres_guide.md", "s0")

    async def test_respects_limit(self, session_factory: SessionFactory, corpus: Corpus) -> None:
        index = PostgresSearchIndex(session_factory)
        results = await index.dense_search(_QUERY_VECTOR, limit=3)
        assert [r.chunk_id for r in results] == [
            corpus.ids_a[0],
            corpus.ids_b[0],
            corpus.ids_a[1],
        ]

    async def test_document_ids_filter(
        self, session_factory: SessionFactory, corpus: Corpus
    ) -> None:
        index = PostgresSearchIndex(session_factory)

        results = await index.dense_search(_QUERY_VECTOR, limit=10, document_ids=[corpus.doc_b.id])

        assert {r.document_id for r in results} == {corpus.doc_b.id}
        assert [r.chunk_id for r in results] == [
            corpus.ids_b[0],
            corpus.ids_b[3],
            corpus.ids_b[2],
            corpus.ids_b[1],
        ]

    async def test_excludes_non_ready_documents(
        self, session_factory: SessionFactory, corpus: Corpus
    ) -> None:
        index = PostgresSearchIndex(session_factory)
        results = await index.dense_search(_QUERY_VECTOR, limit=10)
        # c0 sits closest to the query (angle 0.05) yet must be invisible.
        assert corpus.ids_c[0] not in {r.chunk_id for r in results}


class TestLexicalSearch:
    async def test_term_frequency_ranks_via_ts_rank_cd(
        self, session_factory: SessionFactory, corpus: Corpus
    ) -> None:
        index = PostgresSearchIndex(session_factory)

        results = await index.lexical_search("vacuum", limit=10)

        # a0 mentions vacuum three times, b1 once; c0 is non-ready; a1 only has
        # "autovacuum" which does not stem to "vacuum".
        assert [r.chunk_id for r in results] == [corpus.ids_a[0], corpus.ids_b[1]]
        assert results[0].score > results[1].score > 0.0

    async def test_multi_word_query_ranks_partial_matches_below_full_ones(
        self, session_factory: SessionFactory, corpus: Corpus
    ) -> None:
        index = PostgresSearchIndex(session_factory)

        results = await index.lexical_search("index tuning", limit=10)

        # The arm ranks rather than filters: a2 has both terms and wins, but b3
        # ("index" only) is still a candidate. Under the old AND semantics b3
        # was dropped outright — and a question containing one unmatched word
        # dropped *everything*, which is what silently disabled this arm.
        assert [r.chunk_id for r in results] == [corpus.ids_a[2], corpus.ids_b[3]]
        assert results[0].score > results[1].score > 0.0

    async def test_quoted_phrase_requires_adjacency(
        self, session_factory: SessionFactory, corpus: Corpus
    ) -> None:
        index = PostgresSearchIndex(session_factory)

        unquoted = await index.lexical_search("exclusive lock", limit=10)
        quoted = await index.lexical_search('"exclusive lock"', limit=10)

        # Relaxing ``&`` to ``|`` must NOT relax quoted phrases: websearch parses
        # a quoted phrase to ``<->`` adjacency, which contains no top-level
        # ``&`` to rewrite, so "exclusive table lock" still fails to match.
        assert {r.chunk_id for r in unquoted} == {corpus.ids_a[3], corpus.ids_b[2]}
        assert [r.chunk_id for r in quoted] == [corpus.ids_a[3]]

    async def test_document_ids_filter(
        self, session_factory: SessionFactory, corpus: Corpus
    ) -> None:
        index = PostgresSearchIndex(session_factory)

        results = await index.lexical_search("vacuum", limit=10, document_ids=[corpus.doc_b.id])

        assert [r.chunk_id for r in results] == [corpus.ids_b[1]]

    async def test_hostile_user_input_is_safe(
        self, session_factory: SessionFactory, corpus: Corpus
    ) -> None:
        index = PostgresSearchIndex(session_factory)
        # Raw tsquery operators would be syntax errors; websearch input is not.
        results = await index.lexical_search("vacuum & ) | !'", limit=10)
        assert corpus.ids_a[0] in {r.chunk_id for r in results}

    async def test_natural_language_question_still_returns_candidates(
        self, session_factory: SessionFactory, corpus: Corpus
    ) -> None:
        """The regression that made hybrid search dense-only in production.

        Real questions arrive as prose, not keywords. Under AND semantics every
        word had to co-occur in one chunk, so a question like this one returned
        ZERO rows — on 14 of 20 golden questions — and RRF silently fused an
        empty arm. Nothing failed; the arm just stopped contributing. Asserting
        a non-empty result for a full sentence is what pins that down.
        """
        index = PostgresSearchIndex(session_factory)

        results = await index.lexical_search(
            "How does vacuum reclaim dead tuples and prevent table bloat?", limit=10
        )

        assert results, "a natural-language question must not return an empty arm"
        # a0 is the only chunk about reclaiming dead tuples.
        assert results[0].chunk_id == corpus.ids_a[0]


class TestRetrieveContextEndToEnd:
    async def test_full_pipeline_fuses_both_arms(
        self, session_factory: SessionFactory, corpus: Corpus
    ) -> None:
        retrieve = RetrieveContext(
            embedder=StaticEmbedder(_QUERY_VECTOR),
            index=PostgresSearchIndex(session_factory),
            reranker=NoopReranker(),
            tracer=NoopTracer(),
            candidates=10,
            top_k=3,
            rrf_k=60,
        )

        context = await retrieve(RetrievalQuery(text="vacuum"))

        assert context.reranker == "none"
        # Dense arm returns all 8 ready chunks; lexical adds no new ids.
        assert context.candidate_count == 8
        assert len(context.chunks) == 3

        top, second, third = context.chunks
        # a0 is #1 in BOTH arms — agreement compounds under RRF.
        assert top.chunk_id == corpus.ids_a[0]
        assert top.dense_rank == 1
        assert top.lexical_rank == 1
        assert top.fused_score == pytest.approx(1 / 61 + 1 / 61)
        assert top.rerank_score is None  # noop reranker passes fusion through
        assert top.filename == "postgres_guide.md"

        # b1 is dense #8 but lexical #2: 1/68 + 1/62 beats b0's dense-only 1/62.
        assert second.chunk_id == corpus.ids_b[1]
        assert second.dense_rank == 8
        assert second.lexical_rank == 2
        assert second.fused_score == pytest.approx(1 / 68 + 1 / 62)

        assert third.chunk_id == corpus.ids_b[0]
        assert third.dense_rank == 2
        assert third.lexical_rank is None
        assert third.fused_score == pytest.approx(1 / 62)

    async def test_document_filter_applies_to_both_arms(
        self, session_factory: SessionFactory, corpus: Corpus
    ) -> None:
        retrieve = RetrieveContext(
            embedder=StaticEmbedder(_QUERY_VECTOR),
            index=PostgresSearchIndex(session_factory),
            reranker=NoopReranker(),
            tracer=NoopTracer(),
            candidates=10,
            top_k=5,
            rrf_k=60,
        )

        context = await retrieve(RetrievalQuery(text="vacuum", document_ids=(corpus.doc_b.id,)))

        assert context.candidate_count == 4
        assert {c.document_id for c in context.chunks} == {corpus.doc_b.id}
        # b1 wins: dense #4 (1/64) + lexical #1 (1/61) > b0's dense #1 (1/61).
        assert context.chunks[0].chunk_id == corpus.ids_b[1]
