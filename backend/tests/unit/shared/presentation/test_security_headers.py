"""SecurityHeadersMiddleware over a bare ASGI app (no server, no FastAPI)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from app.shared.presentation.security_headers import (
    DEFAULT_SECURITY_HEADERS,
    SecurityHeadersMiddleware,
)

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send


def _plain_app(headers: list[tuple[bytes, bytes]]) -> ASGIApp:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json"), *headers],
            }
        )
        await send({"type": "http.response.body", "body": b"{}"})

    return app


async def _get(app: SecurityHeadersMiddleware) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/")


async def test_adds_all_default_headers() -> None:
    response = await _get(SecurityHeadersMiddleware(_plain_app([])))
    for name, value in DEFAULT_SECURITY_HEADERS.items():
        assert response.headers[name] == value


async def test_does_not_override_headers_set_by_the_app() -> None:
    app = _plain_app([(b"x-frame-options", b"SAMEORIGIN")])
    response = await _get(SecurityHeadersMiddleware(app))
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


async def test_custom_header_set_replaces_defaults() -> None:
    middleware = SecurityHeadersMiddleware(_plain_app([]), headers={"X-Custom": "1"})
    response = await _get(middleware)
    assert response.headers["X-Custom"] == "1"
    assert "X-Frame-Options" not in response.headers
