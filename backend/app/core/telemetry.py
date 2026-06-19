"""
OpenTelemetry distributed tracing setup for AIRRA.

Instruments FastAPI routes, SQLAlchemy queries, and Redis calls so every
incident analysis can be traced end-to-end from HTTP request through Celery
task through DB query through LLM call.

Jaeger receives traces at AIRRA_OTEL_ENDPOINT (default: localhost:4317).
Set AIRRA_OTEL_ENABLED=false to disable (e.g. in unit tests).
"""
import logging

logger = logging.getLogger(__name__)


def setup_telemetry(service_name: str = "airra-backend", endpoint: str = "") -> None:
    """
    Configure OpenTelemetry with OTLP gRPC exporter pointing at Jaeger.

    Instruments:
    - FastAPI (auto-instrument on app startup via middleware)
    - SQLAlchemy (traces every DB query with statement text)
    - Redis (traces cache hits/misses and Celery broker calls)

    Silently skips instrumentation if opentelemetry packages are not installed,
    so the backend still starts cleanly without OTel in stripped environments.
    """
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning(
            "opentelemetry packages not installed — tracing disabled. "
            "Install: opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc"
        )
        return

    resource = Resource.create({"service.name": service_name, "service.version": "0.1.0"})
    provider = TracerProvider(resource=resource)

    otlp_endpoint = endpoint or "http://jaeger:4317"
    exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)

    _instrument_sqlalchemy()
    _instrument_redis()

    logger.info(f"OpenTelemetry tracing enabled → {otlp_endpoint} (service={service_name})")


def _instrument_sqlalchemy() -> None:
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        SQLAlchemyInstrumentor().instrument()
        logger.debug("SQLAlchemy OTel instrumentation enabled")
    except ImportError:
        logger.debug("SQLAlchemy OTel instrumentor not available — skipping")


def _instrument_redis() -> None:
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        RedisInstrumentor().instrument()
        logger.debug("Redis OTel instrumentation enabled")
    except ImportError:
        logger.debug("Redis OTel instrumentor not available — skipping")


def instrument_fastapi(app) -> None:
    """
    Instrument a FastAPI app with OTel. Call this after app creation.

    Must be called after trace provider is configured (i.e. after setup_telemetry).
    Separating this from setup_telemetry allows the app object to be created first.
    """
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
        logger.debug("FastAPI OTel instrumentation enabled")
    except ImportError:
        logger.debug("FastAPI OTel instrumentor not available — skipping")
