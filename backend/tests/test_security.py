"""Unit tests for security primitives (bcrypt hashing, JWT tokens)."""
from __future__ import annotations

import pytest

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    verify_password,
)


def test_password_hash_roundtrip():
    hashed = get_password_hash("correct-horse-battery-staple")
    assert hashed != "correct-horse-battery-staple"
    assert verify_password("correct-horse-battery-staple", hashed)
    assert not verify_password("wrong-password", hashed)


def test_password_hash_truncates_to_72_bytes():
    long_password = "a" * 100
    hashed = get_password_hash(long_password)
    assert verify_password("a" * 100, hashed)


@pytest.mark.asyncio
async def test_access_token_roundtrip(superuser):
    user = await superuser()
    token = create_access_token(user)
    payload = decode_token(token)
    assert payload.sub == str(user.id)
    assert payload.type == "access"


@pytest.mark.asyncio
async def test_refresh_token_type(superuser):
    user = await superuser()
    token = create_refresh_token(user)
    payload = decode_token(token)
    assert payload.sub == str(user.id)
    assert payload.type == "refresh"
