"""Structured JSON logging (D16): one JSON object per line, on stdlib `logging`.

`configure_logging()` routes structlog through a `ProcessorFormatter` on a
stdout handler, rather than structlog's own `PrintLogger`, so a later task
can attach an OTel logging handler to the same root logger without touching
this module. `RequestIDMiddleware` binds `request_id` and `trace_id` into
structlog's contextvars for the duration of a request and emits the single
access line; `bind_conversation_id()` lets a route add `conversation_id` once
it is known (nothing calls it yet).
"""

import logging
import sys
import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.telemetry import get_trace_id

__all__ = ["RequestIDMiddleware", "bind_conversation_id", "configure_logging"]

_REQUEST_ID_HEADER = "X-Request-ID"

_access_logger = structlog.get_logger("app.access")


def configure_logging() -> None:
    """Configure structlog + stdlib `logging` to emit one JSON line per record."""
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(logging.INFO)

    # uvicorn logs through stdlib `logging` too; let its error log flow
    # through the same JSON handler, but silence its own access line so
    # every request produces exactly one JSON line, ours.
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("uvicorn.error").handlers = []
    logging.getLogger("uvicorn.error").propagate = True


def bind_conversation_id(conversation_id: str) -> None:
    """Bind `conversation_id` into the current request's log context."""
    structlog.contextvars.bind_contextvars(conversation_id=conversation_id)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Binds `request_id`/`trace_id` and logs one access line per request.

    `app.core.telemetry.instrument_app` wraps the whole ASGI app one layer
    further out than any `add_middleware`d class, so the OTel request span
    is already active by the time `get_trace_id()` runs here.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(_REQUEST_ID_HEADER) or uuid.uuid4().hex

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id, trace_id=get_trace_id())

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        response.headers[_REQUEST_ID_HEADER] = request_id
        _access_logger.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
        )
        return response
