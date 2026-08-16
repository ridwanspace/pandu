"""API-key auth dependency (header ``X-API-Key``).

An empty ``API_KEYS`` setting disables auth entirely — the local/dev default.
Key comparison is constant-time per candidate; keys are never logged.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Header, HTTPException, status

from app.config import get_settings


async def require_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    accepted = get_settings().api_key_list
    if not accepted:
        return
    if x_api_key is not None and any(secrets.compare_digest(x_api_key, key) for key in accepted):
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid or missing API key",
        headers={"WWW-Authenticate": "ApiKey"},
    )
