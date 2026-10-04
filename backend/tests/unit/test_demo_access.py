"""Judges' quick access (ADR-036): the routes exist only behind
`DEMO_QUICK_LOGIN`, take no `customer_id` (R1), refuse any persona outside
the demo catalog, and the staff door opens only the seeded admin.

No DB, Redis or LLM: the catalog checks read the repo's YAML files, the
route test fails before any query, and the staff session uses a fake store.
"""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
import structlog
from fastapi import FastAPI, routing
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.core.errors import NotFound
from app.domains.identity import demo_access
from app.domains.identity import service as identity_service
from app.domains.identity.passwords import hash_password, staff_login_key
from app.domains.identity.repository import AccountRow
from app.domains.identity.service import InvalidCredentials, mint_session_for_staff
from app.main import create_app

_REPO = Path(__file__).resolve().parents[3]
_SETTINGS = Settings(identity_hmac_key="k" * 32, _env_file=None)


@pytest.fixture
def demo_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("DEMO_QUICK_LOGIN", "true")
    monkeypatch.setenv("PERSONAS_PATH", str(_REPO / "eval" / "personas.yaml"))
    monkeypatch.setenv("DEMO_PERSONAS_PATH", str(_REPO / "eval" / "demo_personas.yaml"))
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def _demo_paths(app: FastAPI) -> set[str]:
    return {
        ctx.path
        for ctx in routing.iter_route_contexts(app.routes)
        if ctx.path is not None and ctx.path.startswith("/api/v1/demo")
    }


def test_routes_mounted_only_behind_flag(demo_env: pytest.MonkeyPatch) -> None:
    assert _demo_paths(create_app()) == {
        "/api/v1/demo/catalog",
        "/api/v1/demo/sessions/customer",
        "/api/v1/demo/sessions/staff",
    }
    demo_env.setenv("DEMO_QUICK_LOGIN", "false")
    get_settings.cache_clear()
    assert _demo_paths(create_app()) == set()


def test_catalog_is_ten_dev_personas(demo_env: pytest.MonkeyPatch) -> None:
    pairs = demo_access.load_demo_catalog()
    assert len(pairs) == 10
    assert all(persona.split == "dev" for _, persona in pairs)


def test_catalog_refuses_non_dev_persona(demo_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bad = tmp_path / "demo_personas.yaml"
    bad.write_text(
        "personas:\n"
        "  - customer_id: CLI-NOT-A-PERSONA\n"
        "    purpose: {es: x, pt: x}\n"
        "    prompts: {es: [x], pt: [x]}\n",
        encoding="utf-8",
    )
    demo_env.setenv("DEMO_PERSONAS_PATH", str(bad))
    get_settings.cache_clear()
    with pytest.raises(demo_access.InvalidDemoCatalog):
        demo_access.load_demo_catalog()


def test_unknown_persona_is_404(demo_env: pytest.MonkeyPatch) -> None:
    with pytest.raises(NotFound):
        demo_access.resolve_customer_id("CLI-1IKY4D1AV8A7")  # dev, but not a demo persona
    response = TestClient(create_app()).post(
        "/api/v1/demo/sessions/customer", json={"persona_id": "CLI-NOT-A-PERSONA"}
    )
    assert response.status_code == 404
    assert "session" not in response.cookies


def _fresh_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    """`service._logger` caches itself on first use (structlog
    `cache_logger_on_first_use`), which would break a later
    `capture_logs()` in `test_login_pii.py`; use a throwaway one here.
    """
    monkeypatch.setattr(identity_service, "_logger", structlog.get_logger())


class _FakeStaffStore:
    def __init__(self, role: str) -> None:
        self._key = staff_login_key("admin", hmac_key=_SETTINGS.identity_hmac_key)
        self._account = AccountRow(
            account_id=uuid4(),
            role=role,
            customer_id=None,
            password_hash=hash_password("p" * 12),
            status="active",
            username="admin",
        )

    async def get_account_by_login_key(self, login_key: str) -> AccountRow | None:
        return self._account if login_key == self._key else None

    async def get_account_by_customer_id(self, customer_id: str) -> AccountRow | None:
        raise NotImplementedError

    async def revoke_token(self, jti: str, expires_at: object) -> None:
        raise NotImplementedError

    async def is_revoked(self, jti: str) -> bool:
        raise NotImplementedError


def test_staff_session_is_admin_without_customer(monkeypatch: pytest.MonkeyPatch) -> None:
    _fresh_logger(monkeypatch)
    session = asyncio.run(
        mint_session_for_staff("admin", store=_FakeStaffStore("admin"), settings=_SETTINGS)
    )
    assert session.role == "admin"
    assert session.customer_id is None


def test_staff_session_refuses_customer_account(monkeypatch: pytest.MonkeyPatch) -> None:
    _fresh_logger(monkeypatch)
    with pytest.raises(InvalidCredentials):
        asyncio.run(
            mint_session_for_staff("admin", store=_FakeStaffStore("customer"), settings=_SETTINGS)
        )
