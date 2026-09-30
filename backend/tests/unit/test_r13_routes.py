"""R13 route-introspection test: every non-public router declares a role
(`RoleGuard`), and every `/conversations/{conversation_id}/...` route is
scoped to its owner (`get_owned_conversation`, D18).

Uses `create_app()` in `dev` -- `/test-idp` isn't mounted there (D8), so it
never needs an exemption entry of its own; the exemptions here are exactly
the routes `04` §3 documents as public: `/health`, `/auth/login`,
`/auth/refresh` and, since D4-B, `/auth/staff/login` (D3, D5): staff login
is CSRF-exempt the same way customer login is, for the same reason -- there
is no cookie yet to double-submit against.

`get_owned_conversation` lives in `app.api.v1.conversations` (T12 human
decision, not `conversation/deps.py`, which does not exist).

D4-B D5 adds two role-shape checks beyond "every non-public route has a
`RoleGuard`": every `/api/v1/staff/...` route is agent+admin (D22: the
`/staff/personas...` routes are admin only), and
`/auth/logout` (moved off `router` onto its own `logout_router`) accepts
both roles, since it is the one route a staff session also reaches.

See docs/specs/d2-a-login-read-tools-api.md D6, D18, "Test list" ->
test_r13_routes; docs/specs/d4-b-disputes-handoff-screens.md D5.
"""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI, routing
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from app.api.v1.conversations import get_owned_conversation
from app.api.v1.staff import get_any_conversation, get_claimed_conversation
from app.core.config import get_settings
from app.domains.identity.deps import RoleGuard

_EXEMPT_PATHS = frozenset(
    {
        "/api/v1/health",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/staff/login",
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


def _role_guards(ctx: routing.RouteContext) -> list[RoleGuard]:
    """Every `RoleGuard` instance declared on `ctx` (router or route level),
    so a test can check *which* roles it names, not just that one exists.
    """

    return [
        dependency.dependency
        for dependency in ctx.dependencies
        if isinstance(dependency.dependency, RoleGuard)
    ]


def _calls_somewhere(dependant: Dependant, target: object) -> bool:
    """Whether `target` appears anywhere in this `Dependant`'s own call or
    any sub-dependency's, recursively.
    """

    if dependant.call is target:
        return True
    return any(_calls_somewhere(sub, target) for sub in dependant.dependencies)


def _role_guard_roles(ctx: routing.RouteContext) -> list[tuple[str, ...]]:
    return [
        dependency.dependency.roles
        for dependency in ctx.dependencies
        if isinstance(dependency.dependency, RoleGuard)
    ]


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

        # D16: staff routes need agent/admin, admin routes admin only, and
        # every claimed-conversation route is scoped to the claimant.
        for ctx in contexts:
            if ctx.path is None:
                continue
            if ctx.path.startswith("/api/v1/staff/personas"):
                # D22: persona catalog and credentials are admin only.
                assert _role_guard_roles(ctx) == [("admin",)], ctx.path
            elif ctx.path.startswith("/api/v1/staff/"):
                assert ("agent", "admin") in _role_guard_roles(ctx), ctx.path
            if ctx.path.startswith("/api/v1/admin/"):
                assert ("admin",) in _role_guard_roles(ctx), ctx.path
        claimed_prefix = "/api/v1/staff/conversations/{conversation_id}"
        claimed_contexts = [
            ctx for ctx in contexts if ctx.path is not None and ctx.path.startswith(claimed_prefix)
        ]
        assert len(claimed_contexts) >= 3
        timeline_path = "/api/v1/staff/conversations/{conversation_id}/timeline"
        for ctx in claimed_contexts:
            if ctx.path == timeline_path:
                # D16: read-only, no claim needed; must not fall back to the claim scope.
                assert _calls_somewhere(ctx.dependant, get_any_conversation), ctx.path
                assert not _calls_somewhere(ctx.dependant, get_claimed_conversation), ctx.path
            else:
                assert _calls_somewhere(ctx.dependant, get_claimed_conversation), (
                    f"{ctx.path} doesn't depend on get_claimed_conversation"
                )
        assert timeline_path in {ctx.path for ctx in claimed_contexts}
        for ctx in contexts:
            if ctx.path != timeline_path:
                assert not _calls_somewhere(ctx.dependant, get_any_conversation), ctx.path
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
