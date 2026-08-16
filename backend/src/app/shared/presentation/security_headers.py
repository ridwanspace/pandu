"""Pure-ASGI middleware adding standard security headers to every response.

Defaults are tuned for a JSON API: nothing embeds it, nothing scripts it.
Existing headers set by a route win — the middleware only fills gaps.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.datastructures import MutableHeaders

if TYPE_CHECKING:
    from collections.abc import Mapping

    from starlette.types import ASGIApp, Message, Receive, Scope, Send

DEFAULT_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, headers: Mapping[str, str] | None = None) -> None:
        self._app = app
        self._headers = dict(headers) if headers is not None else DEFAULT_SECURITY_HEADERS

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in self._headers.items():
                    if name not in headers:
                        headers.append(name, value)
            await send(message)

        await self._app(scope, receive, send_with_headers)
