"""require_api_key: disabled mode, accepted keys, and 401 behavior."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.config import Settings
from app.shared.presentation import auth


def _settings(api_keys: str) -> Settings:
    return Settings(_env_file=None, api_keys=api_keys)


@pytest.fixture
def use_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "get_settings", lambda: _settings("key-one, key-two"))


async def test_auth_disabled_when_no_keys_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "get_settings", lambda: _settings(""))
    assert await auth.require_api_key(None) is None
    assert await auth.require_api_key("anything") is None


@pytest.mark.usefixtures("use_keys")
async def test_valid_key_passes() -> None:
    assert await auth.require_api_key("key-one") is None
    assert await auth.require_api_key("key-two") is None


@pytest.mark.usefixtures("use_keys")
async def test_missing_key_rejected() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await auth.require_api_key(None)
    assert exc_info.value.status_code == 401
    assert exc_info.value.headers is not None
    assert "WWW-Authenticate" in exc_info.value.headers


@pytest.mark.usefixtures("use_keys")
async def test_wrong_key_rejected() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await auth.require_api_key("key-three")
    assert exc_info.value.status_code == 401
