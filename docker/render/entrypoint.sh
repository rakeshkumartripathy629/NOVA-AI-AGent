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

echo "[entrypoint] Running database migrations..."
alembic upgrade head 2>&1 || echo "[entrypoint] WARNING: alembic migration failed (tables may already exist)"

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
