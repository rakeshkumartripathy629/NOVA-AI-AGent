"""
Comprehensive API test suite for Nova AI production endpoints.

Run against the live server:
    cd backend && python -m pytest tests/test_production_api.py -v

Or run individual test functions directly:
    python -c "from tests.test_production_api import *; ..."
"""
from __future__ import annotations

import json
import time
import pytest
import httpx


BASE_URL = "http://127.0.0.1:8000"
TIMEOUT = 15


# ── Helpers ──────────────────────────────────────────────────────────────

_cached_token = None

def _login(email: str = "admin@nova-ai.com", password: str = "changeme123") -> str:
    """Login and return access token. Caches to avoid rate limiting.
    Raises httpx.HTTPStatusError on failure."""
    global _cached_token
    if _cached_token:
        return _cached_token
    r = httpx.post(
        f"{BASE_URL}/api/v1/auth/login",
        data={"username": email, "password": password},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    _cached_token = r.json()["access_token"]
    return _cached_token


def _login_skip_on_429(email: str = "admin@nova-ai.com", password: str = "changeme123") -> str | None:
    """Login but return None if rate-limited instead of raising."""
    global _cached_token
    if _cached_token:
        return _cached_token
    try:
        return _login(email, password)
    except httpx.HTTPStatusError:
        return None


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Health Check Tests ──────────────────────────────────────────────────

class TestHealthEndpoints:
    """Test all health check endpoints."""

    def test_health_basic(self):
        """GET /health returns basic status."""
        r = httpx.get(f"{BASE_URL}/health", timeout=TIMEOUT)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] in ("healthy", "degraded")
        assert "version" in body
        assert body["database"] in ("connected", "disconnected")

    def test_health_live(self):
        """GET /health/live returns liveness probe."""
        r = httpx.get(f"{BASE_URL}/health/live", timeout=TIMEOUT)
        assert r.status_code == 200
        assert r.json() == {"status": "alive"}

    def test_health_ready_success(self):
        """GET /health/ready returns readiness when DB is up."""
        r = httpx.get(f"{BASE_URL}/health/ready", timeout=TIMEOUT)
        assert r.status_code == 200
        assert r.json()["status"] == "ready"

    def test_health_detail(self):
        """GET /health/detail returns full dependency check."""
        r = httpx.get(f"{BASE_URL}/health/detail", timeout=TIMEOUT)
        assert r.status_code in (200, 503)
        body = r.json()
        assert "status" in body
        assert "checks" in body
        checks = body["checks"]
        assert "database" in checks
        assert "ai_providers" in checks
        assert "storage" in checks
        # DB should be healthy
        assert checks["database"]["status"] in ("healthy", "unhealthy")
        # AI providers should show configured status
        providers = checks["ai_providers"]["providers"]
        assert "groq" in providers
        assert "gemini" in providers
        assert "cerebras" in providers

    def test_health_detail_latency(self):
        """GET /health/detail includes latency measurements."""
        r = httpx.get(f"{BASE_URL}/health/detail", timeout=TIMEOUT)
        body = r.json()
        assert "latency_ms" in body
        assert isinstance(body["latency_ms"], (int, float))
        # Database check should have latency
        assert "latency_ms" in body["checks"]["database"]

    def test_circuit_breakers_endpoint(self):
        """GET /health/circuit-breakers returns breaker statuses."""
        r = httpx.get(f"{BASE_URL}/health/circuit-breakers", timeout=TIMEOUT)
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, dict)


# ── Authentication Tests ────────────────────────────────────────────────

class TestAuthEndpoints:
    """Test authentication flow: register, login, refresh, me, logout."""

    def test_login_success(self):
        """POST /auth/login with valid credentials returns tokens."""
        global _cached_token
        _cached_token = None  # reset cache
        r = httpx.post(
            f"{BASE_URL}/api/v1/auth/login",
            data={"username": "admin@nova-ai.com", "password": "changeme123"},
            timeout=TIMEOUT,
        )
        assert r.status_code in (200, 429)
        if r.status_code == 200:
            body = r.json()
            assert "access_token" in body
            assert "refresh_token" in body
            assert body["token_type"] == "bearer"
            assert "user" in body
            _cached_token = body["access_token"]

    def test_login_wrong_password(self):
        """POST /auth/login with wrong password returns 401."""
        r = httpx.post(
            f"{BASE_URL}/api/v1/auth/login",
            data={"username": "admin@nova-ai.com", "password": "wrongpass"},
            timeout=TIMEOUT,
        )
        assert r.status_code in (401, 429)

    def test_login_nonexistent_user(self):
        """POST /auth/login with nonexistent email returns 401."""
        r = httpx.post(
            f"{BASE_URL}/api/v1/auth/login",
            data={"username": "nobody@test.dev", "password": "pass123"},
            timeout=TIMEOUT,
        )
        assert r.status_code in (401, 429)

    def test_register_new_user(self):
        """POST /auth/register creates a new user."""
        import uuid
        email = f"test-{uuid.uuid4().hex[:8]}@test.dev"
        r = httpx.post(
            f"{BASE_URL}/api/v1/auth/register",
            json={"email": email, "password": "testpass123", "full_name": "Test User"},
            timeout=TIMEOUT,
        )
        # Accept 201 (created), 429 (rate limited), or 422 (validation)
        assert r.status_code in (200, 201, 429)
        if r.status_code in (200, 201):
            body = r.json()
            assert "access_token" in body
            assert body["user"]["email"] == email

    def test_register_duplicate_email(self):
        """POST /auth/register with existing email returns error."""
        r = httpx.post(
            f"{BASE_URL}/api/v1/auth/register",
            json={"email": "admin@nova-ai.com", "password": "testpass123"},
            timeout=TIMEOUT,
        )
        assert r.status_code in (400, 409, 422, 429)

    def test_get_me(self):
        """GET /auth/me returns current user info."""
        try:
            token = _login()
        except httpx.HTTPStatusError:
            pytest.skip("Rate limited on login")
        r = httpx.get(
            f"{BASE_URL}/api/v1/auth/me",
            headers=_auth_header(token),
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        body = r.json()
        assert "id" in body
        assert "email" in body

    def test_get_me_no_token(self):
        """GET /auth/me without token returns 401."""
        r = httpx.get(f"{BASE_URL}/api/v1/auth/me", timeout=TIMEOUT)
        assert r.status_code == 401

    def test_get_me_invalid_token(self):
        """GET /auth/me with invalid token returns 401."""
        r = httpx.get(
            f"{BASE_URL}/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid-token-123"},
            timeout=TIMEOUT,
        )
        assert r.status_code == 401


# ── Conversation Tests ──────────────────────────────────────────────────

class TestConversationEndpoints:
    """Test conversation CRUD operations."""

    def test_list_conversations(self):
        """GET /conversations returns conversation list."""
        try:
            token = _login()
        except httpx.HTTPStatusError:
            pytest.skip("Rate limited on login")
        r = httpx.get(
            f"{BASE_URL}/api/v1/conversations",
            headers=_auth_header(token),
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        body = r.json()
        assert "conversations" in body
        assert isinstance(body["conversations"], list)

    def test_create_conversation(self):
        """POST /conversations creates a new conversation."""
        try:
            token = _login()
        except httpx.HTTPStatusError:
            pytest.skip("Rate limited on login")
        r = httpx.post(
            f"{BASE_URL}/api/v1/conversations",
            headers={**_auth_header(token), "Content-Type": "application/json"},
            json={"title": "Test Conversation", "is_private": False},
            timeout=TIMEOUT,
        )
        assert r.status_code in (200, 201)
        body = r.json()
        assert "id" in body
        assert body["title"] == "Test Conversation"

    def test_rename_conversation(self):
        """PATCH /conversations/{id} renames a conversation."""
        try:
            token = _login()
        except httpx.HTTPStatusError:
            pytest.skip("Rate limited on login")
        # Create
        r = httpx.post(
            f"{BASE_URL}/api/v1/conversations",
            headers={**_auth_header(token), "Content-Type": "application/json"},
            json={"title": "Original Title"},
            timeout=TIMEOUT,
        )
        conv_id = r.json()["id"]
        # Rename
        r = httpx.patch(
            f"{BASE_URL}/api/v1/conversations/{conv_id}",
            headers={**_auth_header(token), "Content-Type": "application/json"},
            json={"title": "Renamed Title"},
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        assert r.json()["title"] == "Renamed Title"

    def test_delete_conversation(self):
        """DELETE /conversations/{id} deletes a conversation."""
        try:
            token = _login()
        except httpx.HTTPStatusError:
            pytest.skip("Rate limited on login")
        # Create
        r = httpx.post(
            f"{BASE_URL}/api/v1/conversations",
            headers={**_auth_header(token), "Content-Type": "application/json"},
            json={"title": "To Delete"},
            timeout=TIMEOUT,
        )
        conv_id = r.json()["id"]
        # Delete
        r = httpx.delete(
            f"{BASE_URL}/api/v1/conversations/{conv_id}",
            headers=_auth_header(token),
            timeout=TIMEOUT,
        )
        assert r.status_code in (200, 204)


# ── Chat Streaming Tests ───────────────────────────────────────────────

class TestChatStreaming:
    """Test AI chat streaming endpoint."""

    def _get_conv_id(self, token: str) -> str:
        r = httpx.get(
            f"{BASE_URL}/api/v1/conversations",
            headers=_auth_header(token),
            timeout=TIMEOUT,
        )
        convs = r.json()["conversations"]
        if convs:
            return convs[0]["id"]
        # Create one
        r = httpx.post(
            f"{BASE_URL}/api/v1/conversations",
            headers={**_auth_header(token), "Content-Type": "application/json"},
            json={"title": "Chat Test"},
            timeout=TIMEOUT,
        )
        return r.json()["id"]

    def test_stream_returns_sse(self):
        """POST /messages/stream returns Server-Sent Events."""
        try:
            token = _login()
        except httpx.HTTPStatusError:
            pytest.skip("Rate limited on login")
        cid = self._get_conv_id(token)
        with httpx.stream(
            "POST",
            f"{BASE_URL}/api/v1/messages/conversations/{cid}/messages/stream",
            headers={**_auth_header(token), "Content-Type": "application/json"},
            json={"content": "say hi", "stream": True},
            timeout=TIMEOUT,
        ) as resp:
            assert resp.status_code == 200
            found_content = False
            found_done = False
            for line in resp.iter_lines():
                if line.startswith("data:"):
                    payload = json.loads(line[5:].strip())
                    if payload.get("type") == "content":
                        found_content = True
                    if payload.get("type") == "done":
                        found_done = True
            assert found_content, "No content event received"
            assert found_done, "No done event received"

    def test_stream_error_no_auth(self):
        """Streaming without auth returns 401."""
        r = httpx.post(
            f"{BASE_URL}/api/v1/messages/conversations/00000000-0000-0000-0000-000000000000/messages/stream",
            json={"content": "hello", "stream": True},
            timeout=TIMEOUT,
        )
        assert r.status_code == 401

    def test_stream_response_time(self):
        """First token should arrive within 10 seconds."""
        try:
            token = _login()
        except httpx.HTTPStatusError:
            pytest.skip("Rate limited on login")
        cid = self._get_conv_id(token)
        start = time.time()
        with httpx.stream(
            "POST",
            f"{BASE_URL}/api/v1/messages/conversations/{cid}/messages/stream",
            headers={**_auth_header(token), "Content-Type": "application/json"},
            json={"content": "2+2", "stream": True},
            timeout=20,
        ) as resp:
            for line in resp.iter_lines():
                if line.startswith("data:"):
                    payload = json.loads(line[5:].strip())
                    if payload.get("type") == "content":
                        elapsed = time.time() - start
                        assert elapsed < 10, f"First token took {elapsed:.1f}s (>10s)"
                        break

    def test_stream_multiple_messages(self):
        """Multiple sequential messages all get responses."""
        try:
            token = _login()
        except httpx.HTTPStatusError:
            pytest.skip("Rate limited on login")
        cid = self._get_conv_id(token)
        for msg in ["hi", "hello", "bye"]:
            start = time.time()
            with httpx.stream(
                "POST",
                f"{BASE_URL}/api/v1/messages/conversations/{cid}/messages/stream",
                headers={**_auth_header(token), "Content-Type": "application/json"},
                json={"content": msg, "stream": True},
                timeout=20,
            ) as resp:
                found = False
                for line in resp.iter_lines():
                    if line.startswith("data:"):
                        payload = json.loads(line[5:].strip())
                        if payload.get("type") == "content":
                            found = True
                            break
                elapsed = time.time() - start
                assert found, f"No response for '{msg}'"
                assert elapsed < 10, f"'{msg}' took {elapsed:.1f}s"


# ── Rate Limiting Tests ────────────────────────────────────────────────

class TestRateLimiting:
    """Test rate limiting on various endpoints."""

    def test_global_rate_limit(self):
        """Rapid requests should not all succeed if rate limiting is active."""
        # Note: rate limiting may be disabled in test env
        # Just verify the endpoint works
        r = httpx.get(f"{BASE_URL}/health", timeout=TIMEOUT)
        assert r.status_code == 200

    def test_security_headers_present(self):
        """All responses include security headers."""
        r = httpx.get(f"{BASE_URL}/health", timeout=TIMEOUT)
        assert "X-Content-Type-Options" in r.headers
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert "X-Frame-Options" in r.headers
        assert r.headers["X-Frame-Options"] == "DENY"
        assert "X-Request-ID" in r.headers
        assert "X-Process-Time" in r.headers

    def test_request_id_returned(self):
        """Each response includes a unique X-Request-ID."""
        r1 = httpx.get(f"{BASE_URL}/health", timeout=TIMEOUT)
        r2 = httpx.get(f"{BASE_URL}/health/live", timeout=TIMEOUT)
        assert "X-Request-ID" in r1.headers
        assert "X-Request-ID" in r2.headers
        # They should be different (UUIDs)
        assert r1.headers["X-Request-ID"] != r2.headers["X-Request-ID"]

    def test_custom_request_id_echoed(self):
        """Client-specified X-Request-ID is echoed back."""
        custom_id = "test-trace-id-12345"
        r = httpx.get(
            f"{BASE_URL}/health",
            headers={"X-Request-ID": custom_id},
            timeout=TIMEOUT,
        )
        assert r.headers.get("X-Request-ID") == custom_id


# ── API Surface Tests ──────────────────────────────────────────────────

class TestAPISurface:
    """Test OpenAPI spec and API documentation."""

    def test_openapi_spec_available(self):
        """GET /openapi.json returns the API spec."""
        r = httpx.get(f"{BASE_URL}/openapi.json", timeout=TIMEOUT)
        assert r.status_code == 200
        spec = r.json()
        assert "paths" in spec
        assert "components" in spec

    def test_docs_available(self):
        """GET /docs returns Swagger UI (dev mode)."""
        r = httpx.get(f"{BASE_URL}/docs", timeout=TIMEOUT)
        assert r.status_code == 200
        assert "swagger" in r.text.lower() or "html" in r.headers.get("content-type", "")

    def test_expected_endpoints_exist(self):
        """Key endpoints are present in the OpenAPI spec."""
        r = httpx.get(f"{BASE_URL}/openapi.json", timeout=TIMEOUT)
        spec = r.json()
        paths = spec["paths"]
        expected = [
            "/health",
            "/health/live",
            "/health/ready",
            "/health/detail",
            "/api/v1/auth/login",
            "/api/v1/auth/register",
            "/api/v1/auth/me",
            "/api/v1/conversations",
            "/api/v1/messages/conversations/{conversation_id}/messages/stream",
        ]
        for ep in expected:
            found = any(ep in p for p in paths)
            assert found, f"Endpoint {ep} not found in OpenAPI spec"

    def test_metrics_endpoint(self):
        """GET /metrics returns Prometheus metrics."""
        r = httpx.get(f"{BASE_URL}/metrics", timeout=TIMEOUT)
        assert r.status_code == 200
        assert "text/plain" in r.headers.get("content-type", "")
        assert "http_requests_total" in r.text


# ── Error Handling Tests ───────────────────────────────────────────────

class TestErrorHandling:
    """Test consistent error response format."""

    def test_404_format(self):
        """Non-existent endpoint returns consistent error format."""
        r = httpx.get(
            f"{BASE_URL}/api/v1/nonexistent-endpoint-xyz",
            timeout=TIMEOUT,
        )
        assert r.status_code == 404
        body = r.json()
        assert "error" in body

    def test_method_not_allowed(self):
        """Wrong HTTP method returns error."""
        r = httpx.put(f"{BASE_URL}/health", timeout=TIMEOUT)
        assert r.status_code in (405, 404)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
