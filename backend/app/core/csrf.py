"""
CSRF protection for cookie-authenticated flows.

Stateful session/CSRF tokens are issued as httpOnly cookies and validated
via a custom header. Stateless JWT (Authorization header) flows are exempt.
"""
from __future__ import annotations

import hmac
import secrets
from typing import Optional

from fastapi import HTTPException, Request, status

from app.core.config import settings


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def _sign(value: str) -> str:
    return hmac.new(settings.CSRF_SECRET.encode(), value.encode(), "sha256").hexdigest()


def issue_csrf_cookie(response) -> None:
    """Set a signed CSRF cookie on the response."""
    token = generate_csrf_token()
    response.set_cookie(
        key=settings.CSRF_COOKIE_NAME,
        value=f"{token}.{_sign(token)}",
        httponly=True,
        secure=settings.is_production,
        samesite="strict",
    )


def validate_csrf(request: Request) -> None:
    """Validate the CSRF cookie against the X-CSRF-Token header."""
    # Skip for token-based (Authorization) requests
    if request.headers.get("Authorization"):
        return

    if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
        return

    cookie = request.cookies.get(settings.CSRF_COOKIE_NAME)
    header = request.headers.get(settings.CSRF_HEADER_NAME)
    if not cookie or not header:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token missing",
        )

    value, _, signature = cookie.partition(".")
    if not hmac.compare_digest(_sign(value), signature):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid CSRF token",
        )
    if not hmac.compare_digest(value, header):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token mismatch",
        )
