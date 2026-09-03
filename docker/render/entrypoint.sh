#!/bin/sh
set -eu

echo "[entrypoint] Starting Nova AI container (PID $$)"

PORT="${PORT:-}"
if [ -z "$PORT" ]; then
    echo "[entrypoint] FATAL: PORT env var is not set. Render must inject PORT." >&2
    exit 1
fi
echo "[entrypoint] PORT=$PORT"

# Remove the Debian default nginx site so it cannot conflict on :80
rm -f /etc/nginx/sites-enabled/default

echo "[entrypoint] Rendering nginx config with PORT=$PORT"
envsubst '${PORT}' < /etc/nginx/conf.d/default.conf.template > /etc/nginx/conf.d/default.conf

echo "[entrypoint] Creating database tables..."
python -c "
import os, asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

url = os.environ.get('DATABASE_URL', '')
if not url:
    print('[entrypoint] WARNING: DATABASE_URL not set, skipping table creation')
else:
    async def create_tables():
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            # Import all models to register them with metadata
            from app.models import Base
            from app.models import user, conversation, message, organization  # noqa
            from app.models import memory, agent, knowledge_base, file  # noqa
            from app.models import notification, webhook, api_key  # noqa
            await conn.run_sync(Base.metadata.create_all)
            print('[entrypoint] Tables created successfully')
        await engine.dispose()
    asyncio.run(create_tables())
" 2>&1 || echo "[entrypoint] WARNING: table creation had issues (continuing anyway)"

echo "[entrypoint] Starting backend (uvicorn) on 127.0.0.1:8000"
uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info &
UVICORN_PID=$!

# Wait for the backend to accept connections before starting nginx
echo "[entrypoint] Waiting for backend on 127.0.0.1:8000 ..."
BACKEND_READY=0
i=0
while [ "$i" -lt 60 ]; do
    if curl -sf http://127.0.0.1:8000/health/live >/dev/null 2>&1; then
        BACKEND_READY=1
        break
    fi
    if ! kill -0 "$UVICORN_PID" 2>/dev/null; then
        echo "[entrypoint] FATAL: uvicorn exited during startup" >&2
        wait "$UVICORN_PID"
        exit 1
    fi
    i=$((i + 1))
    sleep 1
done

if [ "$BACKEND_READY" -ne 1 ]; then
    echo "[entrypoint] FATAL: backend did not become ready within 60s" >&2
    kill "$UVICORN_PID" 2>/dev/null || true
    wait "$UVICORN_PID" 2>/dev/null || true
    exit 1
fi
echo "[entrypoint] Backend is ready"

echo "[entrypoint] Starting nginx on 0.0.0.0:$PORT"
nginx -g 'daemon off;' &
NGINX_PID=$!

cleanup() {
    echo "[entrypoint] Shutting down (SIGTERM)"
    kill "$UVICORN_PID" 2>/dev/null || true
    kill "$NGINX_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Supervise: if either process dies, exit so Render restarts the container
# with a visible error in the logs.
while :; do
    if ! kill -0 "$UVICORN_PID" 2>/dev/null; then
        echo "[entrypoint] uvicorn exited; terminating container" >&2
        kill "$NGINX_PID" 2>/dev/null || true
        exit 1
    fi
    if ! kill -0 "$NGINX_PID" 2>/dev/null; then
        echo "[entrypoint] nginx exited; terminating container" >&2
        kill "$UVICORN_PID" 2>/dev/null || true
        exit 1
    fi
    sleep 2
done
