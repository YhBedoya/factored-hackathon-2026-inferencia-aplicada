"""FastAPI app factory.

`create_app()` builds the app fresh (needed by tests that want an isolated
instance); the module-level `app` is the one process instance uvicorn serves
and the one `make client` introspects for its OpenAPI schema. OpenAPI is
served at `/api/v1/openapi.json`, not the FastAPI default `/openapi.json`,
because it lives under the versioned prefix everything else does.
"""

from fastapi import FastAPI

from app.api.router import api_router
from app.core.logging import RequestIDMiddleware, configure_logging
from app.core.telemetry import instrument_app

__all__ = ["app", "create_app"]


def create_app() -> FastAPI:
    """Build the FastAPI app with the versioned API router mounted."""
    configure_logging()
    app = FastAPI(openapi_url="/api/v1/openapi.json")
    # OTel wraps the whole ASGI app one layer further out than any
    # `add_middleware`d class, so the request span is active before
    # `RequestIDMiddleware.dispatch` reads `trace_id` (D16).
    instrument_app(app)
    app.add_middleware(RequestIDMiddleware)
    app.include_router(api_router)
    return app


app = create_app()
