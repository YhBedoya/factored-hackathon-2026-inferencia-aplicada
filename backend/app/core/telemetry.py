"""OTel SDK wiring (D16): a `TracerProvider` plus FastAPI auto-instrumentation.

`instrument_app()` always installs a `TracerProvider` and wraps `app`, so the
SDK samples and assigns a real random trace id to every request span even
with no exporter (the default root sampler is `ParentBased(AlwaysOn)`), which
is all the access log needs.

When `Settings.otel_exporter_otlp_endpoint` (D5, T1) is non-empty, this module
additionally exports traces, metrics and logs over OTLP/HTTP to that
collector, and turns on asyncpg/Redis instrumentation. With the endpoint
unset (the default), none of that runs and no network call is made — this is
T3's original, exporter-less behavior, unchanged.

`opentelemetry-*` imports must stay in `app.core` (06 §2); nothing outside
this module imports them.
"""

import logging
from collections.abc import Mapping

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry._logs import LogRecord
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.core.config import get_settings

__all__ = ["get_trace_id", "instrument_app", "setup_log_export"]

_SERVICE_NAME = "card-support-backend"

# Short enough that a request never waits on an unreachable collector: the
# batch processors and periodic reader export on their own background
# threads, but a slow/absent collector must not delay startup or shutdown.
_EXPORT_TIMEOUT_SECONDS = 5

# The scalar types this app's log fields actually use; anything else (e.g. a
# live `Logger`) is dropped rather than handed to the SDK, which would
# otherwise warn. `bytes` is deliberately excluded: it renders as `b'...'`
# in the `key=value` body line, which no field here is expected to be.
_ATTRIBUTE_SCALAR_TYPES = (bool, str, int, float)

# structlog's `BoundLogger` stamps these onto every stdlib `LogRecord` to
# let `ProcessorFormatter` find the original logger later; they are never
# part of the actual event and one of them (`_logger`) is a live `Logger`
# instance, not an OTel-attribute-safe scalar.
_STRUCTLOG_INTERNAL_KEYS = frozenset({"_logger", "_name", "_record", "_from_structlog"})


class _StructlogAwareLoggingHandler(LoggingHandler):
    """Bridges this app's structlog records into clean OTel log records.

    `configure_logging()`'s `ProcessorFormatter.wrap_for_formatter` leaves
    the whole event dict as `record.msg` (not stdlib `%`-args), so the stock
    `LoggingHandler._translate` exports `body` as that raw mapping —
    `request_id`/`status`/etc. buried inside it, not searchable as
    first-class VictoriaLogs fields — and turns the structlog-internal
    `_logger` extra (a live `Logger` instance) into an attribute, which the
    OTel SDK rejects with an "Invalid type" warning on every single record.

    This override promotes the event dict's scalar keys to top-level OTel
    attributes (so VictoriaLogs indexes `request_id`, `status`, etc. as
    fields) and renders `body` as a `key=value` line built from those same
    keys, so a bare phrase search for a value (e.g. a `request_id`) still
    matches. Non-structlog records (no mapping `msg`) fall back to the
    stock translation, only stripped of the same structlog-internal/
    non-scalar keys.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # The OTel SDK's own loggers (e.g. an exporter warning about a
        # failed export) must never be exported through this handler: doing
        # so would feed that failure straight back into another export call.
        if record.name == "opentelemetry" or record.name.startswith("opentelemetry."):
            return False
        # typeshed types `Filterer.filter` as `bool | LogRecord` (a filter
        # may rewrite the record in place); this handler never does that.
        return bool(super().filter(record))

    def _translate(self, record: logging.LogRecord) -> LogRecord:
        log_record = super()._translate(record)
        # `code.*` diagnostics (file/function/line) come from the base
        # translation; keep them as attributes, but never let them leak
        # into `body` — the event fields alone read as one clean line.
        base_attributes = {
            key: value
            for key, value in (log_record.attributes or {}).items()
            if key not in _STRUCTLOG_INTERNAL_KEYS and isinstance(value, _ATTRIBUTE_SCALAR_TYPES)
        }
        if isinstance(record.msg, Mapping):
            event_attributes = {
                key: value
                for key, value in record.msg.items()
                if key not in _STRUCTLOG_INTERNAL_KEYS
                and isinstance(value, _ATTRIBUTE_SCALAR_TYPES)
            }
            log_record.body = " ".join(f"{key}={value}" for key, value in event_attributes.items())
            log_record.attributes = {**base_attributes, **event_attributes}
        else:
            log_record.attributes = base_attributes
        return log_record


def _install_log_export(base: str, resource: Resource) -> None:
    """Attach an OTLP log exporter and the structlog-aware handler to the root logger."""
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(
            OTLPLogExporter(endpoint=f"{base}/v1/logs", timeout=_EXPORT_TIMEOUT_SECONDS)
        )
    )
    # Added after `configure_logging()` has already set the root logger's
    # stdout handler, so this appends rather than replacing it: the same event
    # (`request_id`/`trace_id`/etc.) goes to both stdout (as T3's untouched JSON
    # line) and the collector (as a clean OTel record via
    # `_StructlogAwareLoggingHandler`, see above).
    logging.getLogger().addHandler(_StructlogAwareLoggingHandler(logger_provider=logger_provider))


def setup_log_export(service_name: str) -> None:
    """Ship this process's logs to the collector under `service_name`.

    For processes with no FastAPI app (the analytics worker). A no-op with
    `otel_exporter_otlp_endpoint` unset. Call after `configure_logging()`.
    """
    endpoint = get_settings().otel_exporter_otlp_endpoint
    if endpoint:
        _install_log_export(endpoint.rstrip("/"), Resource.create({SERVICE_NAME: service_name}))


def instrument_app(app: FastAPI) -> None:
    """Install the SDK `TracerProvider` and wrap `app` in a request span.

    Call once, on the app instance a process actually serves. A second
    provider install is a no-op noisy warning from the OTel API, not an
    error, so tests that build a fresh app still work.
    """
    resource = Resource.create({SERVICE_NAME: _SERVICE_NAME})
    tracer_provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(tracer_provider)

    endpoint = get_settings().otel_exporter_otlp_endpoint
    if endpoint:
        base = endpoint.rstrip("/")
        tracer_provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=f"{base}/v1/traces", timeout=_EXPORT_TIMEOUT_SECONDS)
            )
        )

        meter_provider = MeterProvider(
            resource=resource,
            metric_readers=[
                PeriodicExportingMetricReader(
                    OTLPMetricExporter(
                        endpoint=f"{base}/v1/metrics", timeout=_EXPORT_TIMEOUT_SECONDS
                    )
                )
            ],
        )
        metrics.set_meter_provider(meter_provider)

        _install_log_export(base, resource)

        # `opentelemetry-instrumentation-asyncpg` 0.66b0 ships no `py.typed`
        # and its `__init__`/`instrument()` are unannotated upstream.
        AsyncPGInstrumentor().instrument()  # type: ignore[no-untyped-call]
        RedisInstrumentor().instrument()

    FastAPIInstrumentor.instrument_app(app)


def get_trace_id() -> str:
    """Return the active span's 32-hex trace id, or 32 zeros with no span."""
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return "0" * 32
    return format(span_context.trace_id, "032x")
