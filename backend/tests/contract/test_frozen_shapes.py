"""Exact JSON shapes of the frozen HTTP contract (BRIEF §HTTP API contract).

These are literal assertions — key sets and values, not schema validation —
so any accidental rename or type drift in the public API fails loudly here.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest


def _assert_keys(payload: dict[str, object], expected: set[str]) -> None:
    assert set(payload) == expected


class TestHealthAndAuth:
    def test_health_requires_no_auth(self, anon_client: httpx.Client) -> None:
        response = anon_client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_missing_api_key_is_401(self, anon_client: httpx.Client) -> None:
        response = anon_client.get("/api/v1/documents")
        assert response.status_code == 401
        assert response.json() == {"detail": "invalid or missing API key"}
        assert response.headers["WWW-Authenticate"] == "ApiKey"

    def test_wrong_api_key_is_401(self, anon_client: httpx.Client) -> None:
        response = anon_client.get("/api/v1/documents", headers={"X-API-Key": "wrong-key"})
        assert response.status_code == 401


class TestConversations:
    def test_create_and_list_roundtrip(self, client: httpx.Client) -> None:
        created = client.post("/api/v1/conversations", json={"title": "Quarterly report"})
        assert created.status_code == 201
        body = created.json()
        _assert_keys(body, {"id", "title", "created_at"})
        assert body["title"] == "Quarterly report"
        conversation_id = UUID(body["id"])  # must be a valid uuid

        listed = client.get("/api/v1/conversations")
        assert listed.status_code == 200
        items = listed.json()["items"]
        assert str(conversation_id) in {item["id"] for item in items}
        for item in items:
            _assert_keys(item, {"id", "title", "created_at"})

    def test_create_without_title_uses_default(self, client: httpx.Client) -> None:
        response = client.post("/api/v1/conversations", json={})
        assert response.status_code == 201
        assert response.json()["title"] != ""

    def test_messages_of_new_conversation_are_empty(self, client: httpx.Client) -> None:
        conversation = client.post("/api/v1/conversations", json={"title": "empty"}).json()
        response = client.get(f"/api/v1/conversations/{conversation['id']}/messages")
        assert response.status_code == 200
        assert response.json() == {"items": []}

    def test_messages_of_unknown_conversation_is_404(self, client: httpx.Client) -> None:
        response = client.get(f"/api/v1/conversations/{uuid4()}/messages")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]


@pytest.mark.usefixtures("clean_db")
class TestDocuments:
    def test_list_empty(self, client: httpx.Client) -> None:
        response = client.get("/api/v1/documents")
        assert response.status_code == 200
        assert response.json() == {"items": []}

    def test_get_unknown_document_is_404(self, client: httpx.Client) -> None:
        response = client.get(f"/api/v1/documents/{uuid4()}")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    def test_delete_unknown_document_is_404(self, client: httpx.Client) -> None:
        assert client.delete(f"/api/v1/documents/{uuid4()}").status_code == 404

    def test_chunks_of_unknown_document_is_404(self, client: httpx.Client) -> None:
        assert client.get(f"/api/v1/documents/{uuid4()}/chunks").status_code == 404

    def test_upload_happy_path(self, client: httpx.Client) -> None:
        upload = client.post(
            "/api/v1/documents",
            files={"file": ("notes.md", b"# Notes\n\nSome body text.", "text/markdown")},
        )
        assert upload.status_code == 202
        accepted = upload.json()
        _assert_keys(accepted, {"id", "filename", "status"})
        assert accepted["filename"] == "notes.md"
        assert accepted["status"] == "queued"
        document_id = accepted["id"]

        fetched = client.get(f"/api/v1/documents/{document_id}")
        assert fetched.status_code == 200
        document = fetched.json()
        _assert_keys(
            document,
            {
                "id",
                "filename",
                "content_type",
                "size_bytes",
                "status",
                "error",
                "chunk_count",
                "created_at",
                "updated_at",
            },
        )
        assert document["content_type"] == "text/markdown"
        assert document["size_bytes"] == len(b"# Notes\n\nSome body text.")
        assert document["status"] == "queued"  # no worker runs in this suite
        assert document["error"] is None
        assert document["chunk_count"] == 0

        listed = client.get("/api/v1/documents").json()
        assert [item["id"] for item in listed["items"]] == [document_id]
        chunks = client.get(f"/api/v1/documents/{document_id}/chunks")
        assert chunks.status_code == 200
        assert chunks.json() == {"items": []}

        assert client.delete(f"/api/v1/documents/{document_id}").status_code == 204
        assert client.get(f"/api/v1/documents/{document_id}").status_code == 404

    def test_upload_rejects_unsupported_content_type(self, client: httpx.Client) -> None:
        response = client.post(
            "/api/v1/documents",
            files={"file": ("evil.exe", b"MZ...", "application/x-msdownload")},
        )
        assert response.status_code == 400
        assert "unsupported content type" in response.json()["detail"]


@pytest.mark.usefixtures("clean_db")
class TestEvalsAndStats:
    def test_eval_runs_empty_shape(self, client: httpx.Client) -> None:
        response = client.get("/api/v1/evals/runs")
        assert response.status_code == 200
        assert response.json() == {"items": []}

    def test_cost_stats_empty_shape(self, client: httpx.Client) -> None:
        response = client.get("/api/v1/stats/costs?days=30")
        assert response.status_code == 200
        assert response.json() == {"total_usd": "0.000000", "by_model": [], "daily": []}

    def test_cost_stats_days_is_validated(self, client: httpx.Client) -> None:
        assert client.get("/api/v1/stats/costs?days=0").status_code == 422
        assert client.get("/api/v1/stats/costs?days=9999").status_code == 422
