"""
Main FastAPI application entry point.
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from sqlalchemy.exc import SQLAlchemyError
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from fastapi.openapi.utils import get_openapi
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.middleware.sessions import SessionMiddleware
from app.core.config import settings
from app.core.security import rate_limiter, get_client_ip
from app.db.session import init_db, close_db, check_db_connection
from app.api.v1.router import api_router
from app.api.v1.websocket import router as ws_router
import traceback
import logging


# Prometheus metrics
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"]
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager."""
    from app.core.logging import setup_logging, get_logger
    from app.core.telemetry import setup_telemetry
    from app.core.storage import storage_service

    setup_logging()
    logger = get_logger("main")

    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Check database connection
    if await check_db_connection():
        logger.info("Database connection OK")
    else:
        logger.warning("Database connection failed")

    # Ensure storage bucket exists
    try:
        await storage_service.ensure_bucket()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Storage initialization failed: %s", exc)

    # OpenTelemetry
    setup_telemetry(app)

    yield

    # Shutdown
    logger.info("Shutting down...")
    from app.db.redis import close_redis
    from app.db.qdrant import close_qdrant
    await close_db()
    await close_redis()
    await close_qdrant()
    logger.info("Connections closed")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title=settings.APP_NAME,
        description=settings.APP_DESCRIPTION,
        version=settings.APP_VERSION,
        docs_url=None if settings.is_production else settings.API_DOCS_URL,
        redoc_url=None if settings.is_production else settings.API_REDOC_URL,
        openapi_url=None if settings.is_production else settings.API_OPENAPI_URL,
        lifespan=lifespan,
    )
    
    # Add middleware
    add_middleware(app)
    
    # Add exception handlers
    add_exception_handlers(app)
    
    # Add routes
    add_routes(app)
    
    # Add metrics endpoint
    if settings.PROMETHEUS_ENABLED:
        add_metrics_endpoint(app)
    
    return app


def add_middleware(app: FastAPI) -> None:
    """Add middleware to the application."""
    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
        allow_methods=settings.CORS_ALLOW_METHODS,
        allow_headers=settings.CORS_ALLOW_HEADERS,
        expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
    )
    
    # GZip compression
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    
    # Session middleware
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.SECRET_KEY,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        https_only=settings.is_production,
        same_site="lax",
    )
    
    # Custom middleware
    @app.middleware("http")
    async def add_process_time_header(request: Request, call_next):
        import time
        import uuid as _uuid

        start_time = time.time()
        request_id = request.headers.get("X-Request-ID") or str(_uuid.uuid4())
        request.state.request_id = request_id

        # Rate limiting
        if settings.RATE_LIMIT_ENABLED:
            client_ip = get_client_ip(request)
            if not rate_limiter.is_allowed(
                f"rate_limit:{client_ip}",
                settings.RATE_LIMIT_REQUESTS,
                settings.RATE_LIMIT_WINDOW,
            ):
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": {
                            "code": "rate_limit_exceeded",
                            "message": "Rate limit exceeded",
                            "type": "rate_limit_exceeded",
                        }
                    },
                    headers={
                        "X-Request-ID": request_id,
                        "X-RateLimit-Limit": str(settings.RATE_LIMIT_REQUESTS),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(settings.RATE_LIMIT_WINDOW),
                    },
                )

        response = await call_next(request)

        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        response.headers["X-Request-ID"] = request_id
        
        # Record metrics
        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=request.url.path,
            status=response.status_code,
        ).inc()
        REQUEST_LATENCY.labels(
            method=request.method,
            endpoint=request.url.path,
        ).observe(process_time)
        
        return response


def _safe_error_value(value):
    """Recursively convert pydantic validation error details to JSON-safe values."""
    from datetime import date, datetime, time
    from uuid import UUID
    from pydantic import BaseModel
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _safe_error_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_error_value(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return str(value)
    except Exception:
        return f"<{type(value).__name__} at 0x{id(value):x}>"


def add_exception_handlers(app: FastAPI) -> None:
    """Add exception handlers to the application."""
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from sqlalchemy.exc import SQLAlchemyError
    from pydantic import ValidationError
    from app.core.exceptions import AppError
    
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.status_code,
                    "message": exc.detail,
                    "type": "http_error",
                }
            },
        )

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_dict(),
        )
    
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": 422,
                    "message": "Validation error",
                    "type": "validation_error",
                    "details": _safe_error_value(exc.errors()),
                }
            },
        )
    
    @app.exception_handler(ValidationError)
    async def pydantic_validation_exception_handler(request: Request, exc: ValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": 422,
                    "message": "Validation error",
                    "type": "validation_error",
                    "details": _safe_error_value(exc.errors()),
                }
            },
        )
    
    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
        # Print the complete traceback in the terminal
        traceback.print_exc()

        # Log the exception
        logging.exception("SQLAlchemy Exception")

        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": 500,
                    "message": str(exc),
                    "type": exc.__class__.__name__,
                }
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        traceback.print_exc()
        logging.exception("Unhandled exception")

        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": 500,
                    "message": str(exc),
                    "type": exc.__class__.__name__,
                }
            },
        )


def add_routes(app: FastAPI) -> None:
    """Add routes to the application."""
    # Health check
    @app.get("/health", tags=["Health"])
    async def health_check():
        db_ok = await check_db_connection()
        return {
            "status": "healthy" if db_ok else "degraded",
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "database": "connected" if db_ok else "disconnected",
        }
    
    @app.get("/health/ready", tags=["Health"])
    async def readiness_check():
        db_ok = await check_db_connection()
        if not db_ok:
            return JSONResponse(
                status_code=503,
                content={"status": "not ready", "database": "disconnected"},
            )
        return {"status": "ready"}
    
    @app.get("/health/live", tags=["Health"])
    async def liveness_check():
        return {"status": "alive"}
    
    # API documentation (custom)
    if not settings.is_production:
        @app.get(settings.API_DOCS_URL, include_in_schema=False)
        async def custom_swagger_ui_html():
            return get_swagger_ui_html(
                openapi_url=settings.API_OPENAPI_URL,
                title=f"{settings.APP_NAME} - API Documentation",
                swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js",
                swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css",
            )
        
        @app.get(settings.API_REDOC_URL, include_in_schema=False)
        async def redoc_html():
            return get_redoc_html(
                openapi_url=settings.API_OPENAPI_URL,
                title=f"{settings.APP_NAME} - API Documentation",
                redoc_js_url="https://cdn.jsdelivr.net/npm/redoc@next/bundles/redoc.standalone.js",
            )
    
    # Include API router
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)
    
    # Include WebSocket router
    app.include_router(ws_router)

    # Public read-only share page
    from fastapi.responses import HTMLResponse

    @app.get("/share/{token}", response_class=HTMLResponse, include_in_schema=False)
    async def shared_conversation_page(token: str):
        return SHARE_PAGE_HTML


def add_metrics_endpoint(app: FastAPI) -> None:
    """Add Prometheus metrics endpoint."""
    @app.get("/metrics", tags=["Monitoring"])
    async def metrics():
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# Create app instance
app = create_app()

SHARE_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Shared conversation</title>
<style>
  body { margin:0; background:#0f1115; color:#e6e8ee; font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; }
  .wrap { max-width:760px; margin:0 auto; padding:32px 20px 80px; }
  h1 { font-size:22px; font-weight:600; margin:0 0 24px; }
  .msg { padding:14px 16px; border-radius:12px; margin:0 0 14px; line-height:1.55; font-size:14.5px; white-space:pre-wrap; word-wrap:break-word; }
  .user { background:#1e2430; }
  .assistant { background:#161b24; border:1px solid #262d3a; }
  .label { display:inline-block; font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:.08em; opacity:.55; margin-bottom:6px; }
  .empty { opacity:.6; }
  code { background:#0b0e13; border:1px solid #262d3a; border-radius:6px; padding:2px 6px; font-family:Consolas,Menlo,monospace; font-size:13px; }
  pre { background:#0b0e13; border:1px solid #262d3a; border-radius:10px; padding:14px; overflow-x:auto; }
  pre code { border:0; padding:0; }
</style>
</head>
<body>
<div class="wrap">
  <h1 id="title">Shared conversation</h1>
  <div id="messages"><div class="empty">Loading...</div></div>
</div>
<script>
const token = window.location.pathname.split("/").pop();
async function load() {
  try {
    const res = await fetch("/api/v1/conversations/public/" + token);
    if (!res.ok) throw new Error("Not found");
    const data = await res.json();
    document.getElementById("title").textContent = data.title;
    const box = document.getElementById("messages");
    if (!data.messages || !data.messages.length) {
      box.innerHTML = '<div class="empty">This conversation has no messages.</div>';
      return;
    }
    box.innerHTML = data.messages.map(function (m) {
      const role = m.role === "user" ? "You" : "Assistant";
      const content = escapeHtml(m.content || "");
      const withCode = content.replace(/```(\\w*)\\n?([\\s\\S]*?)```/g, '<pre><code>$2</code></pre>');
      return '<div class="msg ' + (m.role === "user" ? "user" : "assistant") + '"><div class="label">' + role + '</div>' + withCode + '</div>';
    }).join("");
  } catch (e) {
    document.getElementById("messages").innerHTML = '<div class="empty">This shared conversation is no longer available.</div>';
  }
}
function escapeHtml(s) {
  return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
load();
</script>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        workers=settings.WORKERS if not settings.DEBUG else 1,
    )