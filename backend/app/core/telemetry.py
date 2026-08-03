"""
OpenTelemetry tracing setup and lightweight Prometheus metric helpers.
"""
from __future__ import annotations

import time
from typing import Callable

from prometheus_client import Counter, Histogram
from opentelemetry import trace

from app.core.config import settings


def setup_telemetry(app=None) -> None:
    """Configure OpenTelemetry tracing and instrument FastAPI if enabled."""
    if not settings.OTEL_ENABLED or not settings.OTEL_EXPORTER_ENDPOINT:
        return

    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource

    resource = Resource.create({SERVICE_NAME: f"{settings.APP_NAME}-{settings.ENVIRONMENT}"})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_ENDPOINT))
    )
    trace.set_tracer_provider(provider)

    if app is not None:
        FastAPIInstrumentor.instrument_app(app)

    SQLAlchemyInstrumentor().instrument()


def time_metric(counter: Counter, histogram: Histogram, labels: dict):
    """Decorator recording a metric for the wrapped async function."""
    def decorator(func: Callable):
        async def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                counter.labels(**labels, status="success").inc()
                return result
            except Exception:
                counter.labels(**labels, status="error").inc()
                raise
            finally:
                histogram.labels(**labels).observe(time.perf_counter() - start)
        return wrapper
    return decorator
