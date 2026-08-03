"""
Application exception hierarchy.

All domain and infrastructure errors derive from ``AppError`` so middleware
can translate them into a consistent ``{"error": {...}}`` envelope.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


class AppError(Exception):
    """Base application error."""

    status_code: int = 500
    code: str = "internal_error"
    message: str = "Internal server error"
    details: Optional[Dict[str, Any]] = None

    def __init__(
        self,
        message: Optional[str] = None,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "type": self.code,
        }
        if self.details:
            payload["details"] = self.details
        return payload


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "Resource not found"


class PermissionDeniedError(AppError):
    status_code = 403
    code = "permission_denied"
    message = "Permission denied"


class AuthenticationError(AppError):
    status_code = 401
    code = "authentication_error"
    message = "Authentication required"


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"
    message = "Validation failed"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    message = "Resource conflict"


class RateLimitError(AppError):
    status_code = 429
    code = "rate_limit_exceeded"
    message = "Rate limit exceeded"


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"
    message = "Service unavailable"


class BadRequestError(AppError):
    status_code = 400
    code = "bad_request"
    message = "Bad request"


class QuotaExceededError(AppError):
    status_code = 402
    code = "quota_exceeded"
    message = "Quota exceeded"


class AIProviderError(AppError):
    """Raised when an upstream AI provider fails."""
    status_code = 502
    code = "ai_provider_error"
    message = "AI provider error"


class ConfigurationError(AppError):
    status_code = 500
    code = "configuration_error"
    message = "Server configuration error"
