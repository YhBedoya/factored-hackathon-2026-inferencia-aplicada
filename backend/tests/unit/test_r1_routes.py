"""R1 route-introspection test: no route accepts `customer_id` as an
argument, except the one deliberate eval-only exception, `/test-idp/sessions`
(D8).

Walks every mounted `APIRoute`'s `dependant` tree -- the route's own path,
query, header, cookie and body params, plus every sub-dependency's, plus the
fields of every body model, recursed into nested pydantic models -- and
collects every parameter name reachable from it. A test that only asserted
"customer_id not in these routes" without ever proving the walker can find
one would pass even if the walker were broken (missed a sub-dependency,
missed a nested model, ...); the non-vacuity check at the end rebuilds the
app with `APP_ENV=eval` and confirms the very same walker flags
`/test-idp/sessions`, whose body genuinely has a `customer_id` field (D8).

`create_app()` is called directly, with no `TestClient` and no lifespan: this
is pure route introspection, so it never needs a DB, Redis or LLM key.

See docs/specs/d2-a-login-read-tools-api.md D8, "Test list" -> test_r1_routes.
"""

from collections.abc import Iterable, Iterator
from inspect import isclass
from typing import Any, get_args

import pytest
from fastapi import FastAPI, routing
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from pydantic import BaseModel

from app.core.config import get_settings


def _iter_api_route_contexts(app: FastAPI) -> Iterator[routing.RouteContext]:
    """Every mounted `APIRoute`, resolved through the effective-route layer
    `_IncludedRouter` adds (`app.routes` alone doesn't flatten sub-routers).
    """

    for ctx in routing.iter_route_contexts(app.routes):
        if isinstance(ctx.original_route, APIRoute):
            yield ctx


def _models_in(annotation: Any) -> Iterator[type[BaseModel]]:
    """Every pydantic model reachable from a type annotation: itself, or one
    found inside a typing construct like `X | None` or `list[X]`.
    """

    if isclass(annotation) and issubclass(annotation, BaseModel):
        yield annotation
        return
    for arg in get_args(annotation):
        yield from _models_in(arg)


def _model_field_names(annotation: Any, seen: set[type[BaseModel]]) -> Iterator[str]:
    """Every field name on every pydantic model reachable from `annotation`,
    recursing into nested models so a `customer_id` buried two levels deep
    can't hide from the walker.
    """

    for model in _models_in(annotation):
        if model in seen:
            continue
        seen.add(model)
        for name, field in model.model_fields.items():
            yield name
            yield from _model_field_names(field.annotation, seen)


def _dependant_param_names(dependant: Dependant, seen: set[type[BaseModel]]) -> Iterator[str]:
    """Every path, query, header, cookie and body parameter name on this
    `Dependant` and every sub-dependency it pulls in (recursively) -- a
    `customer_id` accepted only by a nested `Depends(...)` still counts.
    """

    params: Iterable[Any] = (
        *dependant.path_params,
        *dependant.query_params,
        *dependant.header_params,
        *dependant.cookie_params,
        *dependant.body_params,
    )
    for param in params:
        yield param.name
        yield from _model_field_names(param.field_info.annotation, seen)
    for sub_dependant in dependant.dependencies:
        yield from _dependant_param_names(sub_dependant, seen)


def _route_param_names(app: FastAPI) -> dict[str, set[str]]:
    """Path -> the set of every parameter name reachable from that route's
    full dependency tree.
    """

    return {
        ctx.path: set(_dependant_param_names(ctx.dependant, set()))
        for ctx in _iter_api_route_contexts(app)
        if ctx.path is not None
    }


def test_no_route_accepts_customer_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    get_settings.cache_clear()
    try:
        from app.main import create_app

        app = create_app()
        names_by_path = _route_param_names(app)

        for path, names in names_by_path.items():
            assert "customer_id" not in names, f"{path} accepts customer_id"

        assert not any(path.startswith("/api/v1/test-idp") for path in names_by_path)
        assert "/api/v1/auth/login" in names_by_path
        assert "/api/v1/conversations/{conversation_id}/messages" in names_by_path

        # Non-vacuity (D8): with APP_ENV=eval, the same walker must flag the
        # one route that genuinely takes a `customer_id` -- proving the
        # assertions above aren't vacuously true.
        monkeypatch.setenv("APP_ENV", "eval")
        get_settings.cache_clear()
        eval_names_by_path = _route_param_names(create_app())
        assert "customer_id" in eval_names_by_path["/api/v1/test-idp/sessions"]
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
