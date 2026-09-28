"""R13 route-introspection test: every non-public router declares a role
(`RoleGuard`), and every `/conversations/{conversation_id}/...` route is
scoped to its owner (`get_owned_conversation`, D18).

Uses `create_app()` in `dev` -- `/test-idp` isn't mounted there (D8), so it
never needs an exemption entry of its own; the exemptions here are exactly
the routes `04` §3 documents as public: `/health` and `/auth/login`.
`/auth/refresh` doesn't exist yet (a later task adds it) but stays in the
exemption list, matching the spec's contract row for it.

`get_owned_conversation` lives in `app.api.v1.conversations` (T12 human
decision, not `conversation/deps.py`, which does not exist).

See docs/specs/d2-a-login-read-tools-api.md D6, D18, "Test list" ->
test_r13_routes.
"""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI, routing
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from app.api.v1.conversations import get_owned_conversation
from app.core.config import get_settings
from app.domains.identity.deps import RoleGuard

_EXEMPT_PATHS = frozenset(
    {
        "/api/v1/health",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
    }
)


def _iter_api_route_contexts(app: FastAPI) -> Iterator[routing.RouteContext]:
    """Every mounted `APIRoute`, resolved through the effective-route layer
    `_IncludedRouter` adds (`app.routes` alone doesn't flatten sub-routers).
    """

    for ctx in routing.iter_route_contexts(app.routes):
        if isinstance(ctx.original_route, APIRoute):
            yield ctx


def _declares_role_guard(ctx: routing.RouteContext) -> bool:
    """`route.dependencies` carries the router/route-level `Depends(...)`
    markers (R13's `require_role(...)` is always declared there, never only
    as a function-parameter sub-dependency).
    """

    return any(isinstance(dependency.dependency, RoleGuard) for dependency in ctx.dependencies)


def _calls_somewhere(dependant: Dependant, target: object) -> bool:
    """Whether `target` appears anywhere in this `Dependant`'s own call or
    any sub-dependency's, recursively.
    """

    if dependant.call is target:
        return True
    return any(_calls_somewhere(sub, target) for sub in dependant.dependencies)


def test_every_route_declares_role_and_ownership(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    get_settings.cache_clear()
    try:
        from app.main import create_app

        app = create_app()
        contexts = list(_iter_api_route_contexts(app))

        for ctx in contexts:
            if ctx.path in _EXEMPT_PATHS:
                continue
            assert _declares_role_guard(ctx), f"{ctx.path} has no RoleGuard dependency"

        conversation_prefix = "/api/v1/conversations/{conversation_id}"
        conversation_contexts = [
            ctx
            for ctx in contexts
            if ctx.path is not None and ctx.path.startswith(conversation_prefix)
        ]
        assert len(conversation_contexts) >= 2
        for ctx in conversation_contexts:
            assert _calls_somewhere(ctx.dependant, get_owned_conversation), (
                f"{ctx.path} doesn't depend on get_owned_conversation"
            )
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
