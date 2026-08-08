#!/bin/sh
set -e

# Render injects PORT (default 80 for local docker builds)
PORT="${PORT:-80}"
export PORT

# Render nginx config with the port substituted
envsubst '${PORT}' < /etc/nginx/conf.d/default.conf.template > /etc/nginx/conf.d/default.conf

# Start backend (uvicorn) in the background on localhost
uvicorn app.main:app --host 127.0.0.1 --port 8000 &
UVICORN_PID=$!

# Start nginx in the foreground
nginx -g 'daemon off;' &
NGINX_PID=$!

cleanup() {
    kill "$UVICORN_PID" 2>/dev/null || true
    kill "$NGINX_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait
