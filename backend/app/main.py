"""FastAPI app factory.

`create_app()` builds the app fresh (needed by tests that want an isolated
instance); the module-level `app` is the one process instance uvicorn serves
and the one `make client` introspects for its OpenAPI schema. OpenAPI is
served at `/api/v1/openapi.json`, not the FastAPI default `/openapi.json`,
because it lives under the versioned prefix everything else does; the docs
UI follows it to `/api/v1/docs`.

The lifespan (D16) refuses to start with an empty `JWT_SECRET` or
`IDENTITY_HMAC_KEY` (D21), naming only the variable(s) that are actually
empty, then opens the turn host -- the checkpointer pool and compiled graph
`start_turn` (`conversation/runner.py`) runs turns against -- and closes it
on shutdown. `tests/unit/test_health.py` builds `TestClient(app)` without a
`with` block on purpose: the ASGI lifespan protocol only fires inside that
context manager, so its fakes-only test never needs a real DB, Redis or LLM
key to pass.

`create_app()` mounts `test_idp.router` (D8) only when
`get_settings().app_env == "eval"`, checked fresh on every call rather than
baked into the always-built `api_router` -- a test that flips `APP_ENV` and
clears `get_settings`'s cache between two `create_app()` calls must see the
route appear and disappear, not just once at import time. It is
`include_router`ed under the same `/api/v1` prefix as `api_router`, same as
every other router.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.api.v1.test_idp import router as test_idp_router
from app.core.config import get_settings
from app.core.llm import get_llm_client
from app.core.logging import RequestIDMiddleware, configure_logging
from app.core.telemetry import instrument_app
from app.domains.conversation.hosting import close_host, open_host

__all__ = ["app", "create_app"]

# The keys of FastAPI's default per-error dict this app-wide handler keeps
# (R5-style, but for a response rather than an LLM prompt): `input` echoes
# the submitted body verbatim -- document number, password, whatever the
# request carried -- and `ctx`/`url` can nest more of it. `type`, `loc` and
# `msg` are enough to say what was wrong without saying what was sent.
_KEPT_ERROR_KEYS = ("type", "loc", "msg")


def _require_secrets(*, jwt_secret: str, identity_hmac_key: str) -> None:
    """Refuse to start with an empty `JWT_SECRET`/`IDENTITY_HMAC_KEY` (D21),
    naming only the variable(s) that are actually empty.
    """
    empty = [
        name
        for name, value in (("JWT_SECRET", jwt_secret), ("IDENTITY_HMAC_KEY", identity_hmac_key))
        if not value
    ]
    if empty:
        raise RuntimeError(f"refusing to start: empty {', '.join(empty)}")


async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI's usual `422 {"detail": [...]}` shape, but every error item
    keeps only `type`/`loc`/`msg` (D2): a request body that fails validation
    -- `/auth/login` with a missing `password`, for one -- must never come
    back with its own `input` inside the error, since that field is a raw
    copy of what was submitted, document number included.
    """
    errors = [
        {key: value for key, value in error.items() if key in _KEPT_ERROR_KEYS}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    _require_secrets(jwt_secret=settings.jwt_secret, identity_hmac_key=settings.identity_hmac_key)
    app.state.turn_host = await open_host(settings.database_url, get_llm_client())
    try:
        yield
    finally:
        await close_host(app.state.turn_host)


def create_app() -> FastAPI:
    """Build the FastAPI app with the versioned API router mounted."""
    configure_logging()
    app = FastAPI(
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        lifespan=_lifespan,
    )
    # OTel wraps the whole ASGI app one layer further out than any
    # `add_middleware`d class, so the request span is active before
    # `RequestIDMiddleware.dispatch` reads `trace_id` (D16).
    instrument_app(app)
    app.add_middleware(RequestIDMiddleware)
    # Starlette's stub types every handler as `(Request, Exception) -> ...`,
    # contravariant in the narrower `RequestValidationError` this one
    # actually takes -- same category of stub gap as `events.py`'s
    # `aclose()` ignore.
    app.add_exception_handler(
        RequestValidationError,
        _validation_error_handler,  # type: ignore[arg-type]
    )
    app.include_router(api_router)
    if get_settings().app_env == "eval":
        app.include_router(test_idp_router, prefix="/api/v1")
    return app


app = create_app()
