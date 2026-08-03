"""
Field-level encryption for sensitive attributes at rest.
"""
from __future__ import annotations

import base64
import hashlib
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

_fernet: Optional[Fernet] = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = settings.FIELD_ENCRYPTION_KEY
        if not key:
            # Derive a key from SECRET_KEY as a deterministic fallback
            key = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
            key = base64.urlsafe_b64encode(key)
        _fernet = Fernet(key)
    return _fernet


def encrypt_value(value: str) -> str:
    """Encrypt a string value."""
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_value(token: str) -> str:
    """Decrypt a string value."""
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Unable to decrypt value") from exc
