"""`POST /admin/demo/reset` is a 404 with `DEMO_RESET_ENABLED=false` (prod,
where quick access makes admin public), and touches nothing before it."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.v1 import admin
from app.core.config import get_settings


def test_reset_is_404_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_RESET_ENABLED", "false")
    get_settings.cache_clear()
    close_host = AsyncMock()
    monkeypatch.setattr(admin, "close_host", close_host)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(turn_host=object())))
    try:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(admin.demo_reset(request))  # type: ignore[arg-type]
    finally:
        get_settings.cache_clear()
    assert exc.value.status_code == 404
    close_host.assert_not_called()
