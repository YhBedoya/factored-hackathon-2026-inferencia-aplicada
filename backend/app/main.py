"""FastAPI app factory.

`create_app()` builds the app fresh (needed by tests that want an isolated
instance); the module-level `app` is the one process instance uvicorn serves
and the one `make client` introspects for its OpenAPI schema. OpenAPI is
served at `/api/v1/openapi.json`, not the FastAPI default `/openapi.json`,
because it lives under the versioned prefix everything else does; the docs
UI follows it to `/api/v1/docs`.

The lifespan (D16) refuses to start with an empty `JWT_SECRET`,
`IDENTITY_HMAC_KEY` or `PII_VAULT_KEY` (D21), naming only the variable(s) that are actually
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
every other router. `demo_access.router` (ADR-036) follows the same
pattern, gated on `DEMO_QUICK_LOGIN` instead of `APP_ENV`; under
`APP_ENV=prod` the lifespan refuses to start with that flag on and an empty
`DEMO_ACCESS_CODE`.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.api.v1.demo_access import router as demo_access_router
from app.api.v1.test_idp import router as test_idp_router
from app.core.config import get_settings
from app.core.llm import get_llm_client
from app.core.logging import RequestIDMiddleware, configure_logging
from app.core.telemetry import instrument_app
from app.domains.audit.service import AuditLLMCallSink
from app.domains.conversation.classifier import load_classifier
from app.domains.conversation.flows.card_select import load_card_select_policy
from app.domains.conversation.hosting import close_host, open_host
from app.domains.policy.registry import get_policies

_logger = structlog.get_logger()

__all__ = ["app", "create_app"]

# The keys of FastAPI's default per-error dict this app-wide handler keeps
# (R5-style, but for a response rather than an LLM prompt): `input` echoes
# the submitted body verbatim -- document number, password, whatever the
# request carried -- and `ctx`/`url` can nest more of it. `type`, `loc` and
# `msg` are enough to say what was wrong without saying what was sent.
_KEPT_ERROR_KEYS = ("type", "loc", "msg")


def _require_secrets(*, jwt_secret: str, identity_hmac_key: str, pii_vault_key: str) -> None:
    """Refuse to start with an empty `JWT_SECRET`/`IDENTITY_HMAC_KEY`/`PII_VAULT_KEY`
    (D21), naming only the variable(s) that are actually empty.
    """
    empty = [
        name
        for name, value in (
            ("JWT_SECRET", jwt_secret),
            ("IDENTITY_HMAC_KEY", identity_hmac_key),
            ("PII_VAULT_KEY", pii_vault_key),
        )
        if not value
    ]
    if empty:
        raise RuntimeError(f"refusing to start: empty {', '.join(empty)}")


def _require_eval_for_baseline(*, agent_system: str, app_env: str) -> None:
    """Refuse to start the LLM-free baseline graph (D17) outside `APP_ENV=eval`."""
    if agent_system == "baseline" and app_env != "eval":
        raise RuntimeError(
            "refusing to start: AGENT_SYSTEM=baseline is only allowed under APP_ENV=eval"
        )


def _refuse_faults_in_prod(*, faults: frozenset[str], app_env: str) -> None:
    """Refuse to start with fault injection (`FAULTS`) enabled under `APP_ENV=prod`."""
    if faults and app_env == "prod":
        raise RuntimeError("refusing to start: FAULTS is set under APP_ENV=prod")


def _require_demo_code_in_prod(
    *, demo_quick_login: bool, demo_access_code: str, app_env: str
) -> None:
    """Refuse to start with the judges' quick access open to anyone (ADR-036):
    under `APP_ENV=prod`, `DEMO_QUICK_LOGIN` needs a `DEMO_ACCESS_CODE`.
    """
    if demo_quick_login and not demo_access_code.strip() and app_env == "prod":
        raise RuntimeError(
            "refusing to start: DEMO_QUICK_LOGIN is on under APP_ENV=prod with an empty "
            "DEMO_ACCESS_CODE"
        )


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
    _require_secrets(
        jwt_secret=settings.jwt_secret,
        identity_hmac_key=settings.identity_hmac_key,
        pii_vault_key=settings.pii_vault_key,
    )
    _require_eval_for_baseline(agent_system=settings.agent_system, app_env=settings.app_env)
    _refuse_faults_in_prod(faults=settings.faults, app_env=settings.app_env)
    _require_demo_code_in_prod(
        demo_quick_login=settings.demo_quick_login,
        demo_access_code=settings.demo_access_code,
        app_env=settings.app_env,
    )
    # Fails the whole startup on a header-less or malformed policy file (D1);
    # the combined hash below is what every audit event's `policy_version`
    # carries for the rest of the process's life (D2).
    bundle = get_policies()
    _logger.info("policy.loaded", hash=bundle.hash, files=bundle.files)
    load_card_select_policy()
    # The app starts with or without a classifier; without one, a failing LLM
    # still ends in the fixed fallback + handoff (ADR-032).
    classifier, reason = load_classifier(settings.intent_model_dir)
    if classifier is not None:
        _logger.info(
            "intent_classifier.loaded",
            classifier_version=classifier.version,
            label_set_version=classifier.label_set_version,
        )
    else:
        _logger.error("intent_classifier.unavailable", reason=reason)
    app.state.turn_host = await open_host(
        settings.database_url,
        get_llm_client(sink=AuditLLMCallSink()),
        system=settings.agent_system,
        classifier=classifier,
    )
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
    if get_settings().demo_quick_login:
        app.include_router(demo_access_router, prefix="/api/v1")
    return app


app = create_app()
