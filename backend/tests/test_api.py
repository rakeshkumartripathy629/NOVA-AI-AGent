"""Smoke tests for the FastAPI app: health, metrics, and OpenAPI surface."""
from __future__ import annotations

import pytest

EXPECTED_MIN_PATHS = 100


@pytest.mark.asyncio
async def test_health_live(api_client):
    resp = await api_client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "alive"}


@pytest.mark.asyncio
async def test_health_endpoint_reports_database(api_client):
    resp = await api_client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in ("healthy", "degraded")
    assert "version" in body


@pytest.mark.asyncio
async def test_openapi_has_expected_surface(api_client):
    resp = await api_client.get("/openapi.json")
    assert resp.status_code == 200
    spec = resp.json()
    paths = spec["paths"]
    assert len(paths) >= EXPECTED_MIN_PATHS
    assert "/auth/login" in paths or any(p.endswith("/auth/login") for p in paths)


@pytest.mark.asyncio
async def test_openapi_defines_models(api_client):
    resp = await api_client.get("/openapi.json")
    spec = resp.json()
    schemas = spec.get("components", {}).get("schemas", {})
    assert len(schemas) > 0
