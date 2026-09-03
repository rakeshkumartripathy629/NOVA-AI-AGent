"""
Circuit Breaker pattern for external services.

Prevents cascade failures by stopping calls to a failing service and
periodically testing recovery. States:
  CLOSED  → normal operation, failures counted
  OPEN    → calls blocked, waiting for cooldown
  HALF_OPEN → single probe call allowed; success → CLOSED, failure → OPEN
"""
from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Any, Callable, Dict, Optional

from app.core.logging import get_logger

logger = get_logger("circuit_breaker")


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Per-service circuit breaker with configurable thresholds."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max: int = 1,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max = half_open_max

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0
        self._half_open_calls = 0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time > self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                logger.info("Circuit breaker [%s] transitioning to HALF_OPEN", self.name)
        return self._state

    def allow_request(self) -> bool:
        """Return True if a request is allowed through."""
        state = self.state
        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.HALF_OPEN:
            if self._half_open_calls < self.half_open_max:
                self._half_open_calls += 1
                return True
            return False
        return False  # OPEN

    def record_success(self) -> None:
        """Record a successful call."""
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            logger.info("Circuit breaker [%s] CLOSED (recovered)", self.name)
        elif self._state == CircuitState.CLOSED:
            self._failure_count = 0

    def record_failure(self) -> None:
        """Record a failed call."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                "Circuit breaker [%s] OPEN (failures=%d, threshold=%d)",
                self.name,
                self._failure_count,
                self.failure_threshold,
            )

    def get_status(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "last_failure": self._last_failure_time,
        }


# ── Global circuit breakers for each external service ───────────────────
BREAKERS: Dict[str, CircuitBreaker] = {}


def get_breaker(name: str, **kwargs: Any) -> CircuitBreaker:
    """Get or create a named circuit breaker."""
    if name not in BREAKERS:
        BREAKERS[name] = CircuitBreaker(name, **kwargs)
    return BREAKERS[name]


def all_breakers_status() -> Dict[str, Dict[str, Any]]:
    """Return status of all circuit breakers."""
    return {name: cb.get_status() for name, cb in BREAKERS.items()}


async def call_with_breaker(
    name: str,
    func: Callable,
    *args: Any,
    fallback: Any = None,
    **kwargs: Any,
) -> Any:
    """Execute a function protected by a circuit breaker.

    If the circuit is OPEN, returns ``fallback`` immediately.
    On failure, records it and returns ``fallback``.
    """
    cb = get_breaker(name)
    if not cb.allow_request():
        logger.warning("Circuit breaker [%s] OPEN — using fallback", name)
        return fallback
    try:
        result = await func(*args, **kwargs)
        cb.record_success()
        return result
    except Exception as exc:
        cb.record_failure()
        logger.warning("Circuit breaker [%s] call failed: %s", name, exc)
        return fallback
