"""
Domain event bus.

Modules publish domain events which are dispatched to registered handlers
in-process and optionally forwarded to webhooks and the audit service.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, DefaultDict, Dict, List, Optional
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


@dataclass
class DomainEvent:
    """Base domain event."""
    event_type: str
    payload: Dict[str, Any] = field(default_factory=dict)
    aggregate_id: Optional[UUID] = None
    aggregate_type: Optional[str] = None
    organization_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    occurred_at: datetime = field(default_factory=lambda: datetime.utcnow())
    event_id: UUID = field(default_factory=uuid4)


EventHandler = Callable[[DomainEvent], Awaitable[None]]


class EventBus:
    """Synchronous-in-event-loop dispatcher with per-type handlers."""

    def __init__(self) -> None:
        self._handlers: DefaultDict[str, List[EventHandler]] = defaultdict(list)

    def register(self, event_type: str, handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)

    def subscribe(self, *event_types: str):
        """Decorator to register a handler for one or more event types."""
        def decorator(func: EventHandler) -> EventHandler:
            for event_type in event_types:
                self.register(event_type, func)
            return func
        return decorator

    async def publish(self, event: DomainEvent) -> None:
        """Dispatch an event to all registered handlers."""
        handlers = self._handlers.get(event.event_type, []) + self._handlers.get("*", [])
        for handler in handlers:
            try:
                if inspect.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    result = handler(event)
                    if inspect.isawaitable(result):
                        await result
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Event handler failed for %s",
                    event.event_type,
                    extra={"event_id": str(event.event_id)},
                )


bus = EventBus()
