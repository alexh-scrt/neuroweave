"""Event bus — async pub/sub for graph mutation events.

Replaces the raw asyncio.Queue approach with a proper subscription system.
Any component can subscribe to specific event types with async callbacks.

Callbacks are invoked concurrently via asyncio.create_task() — one slow
handler doesn't block others or the emitter. A per-handler timeout (default
5 seconds) logs a warning if exceeded but does not cancel the handler.

Usage:
    bus = EventBus()

    async def on_node(event: GraphEvent):
        print(f"New node: {event.data}")

    bus.subscribe(on_node, event_types={GraphEventType.NODE_ADDED})
    bus.emit(GraphEvent(GraphEventType.NODE_ADDED, data={...}))
    bus.unsubscribe(on_node)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from neuroweave.graph.store import GraphEvent, GraphEventType
from neuroweave.logging import get_logger

log = get_logger("events")

# Type alias for event handler callbacks
EventHandler = Callable[[GraphEvent], Awaitable[None]]

# Default timeout for handler invocations (seconds)
DEFAULT_HANDLER_TIMEOUT = 5.0


@dataclass
class _Subscription:
    """Internal record of a registered handler."""

    handler: EventHandler
    event_types: set[GraphEventType] | None  # None = all events
    label: str  # Human-readable label for logging


class EventBus:
    """Async pub/sub event bus for graph mutation events.

    Thread-safety: This class is designed for single-threaded async use
    within one asyncio event loop. All operations are synchronous except
    handler invocation (which uses create_task).

    Attributes:
        handler_timeout: Seconds before a slow handler triggers a warning.
    """

    def __init__(self, *, handler_timeout: float = DEFAULT_HANDLER_TIMEOUT) -> None:
        self._subscriptions: list[_Subscription] = []
        self._handler_timeout = handler_timeout
        self._emit_count: int = 0
        self._handler_timeout_count: int = 0
        self._handler_error_count: int = 0

    def subscribe(
        self,
        handler: EventHandler,
        *,
        event_types: set[GraphEventType] | None = None,
        label: str | None = None,
    ) -> None:
        """Register an async callback to receive events.

        Args:
            handler: Async function that takes a GraphEvent.
            event_types: Set of event types to filter on. None = receive all events.
            label: Optional human-readable label for logging. Defaults to the
                   function name.
        """
        # Prevent duplicate subscriptions of the same handler
        for sub in self._subscriptions:
            if sub.handler is handler:
                log.warning("events.duplicate_subscribe", label=label or handler.__name__)
                return

        sub_label = label or getattr(handler, "__name__", repr(handler))
        self._subscriptions.append(
            _Subscription(handler=handler, event_types=event_types, label=sub_label)
        )
        log.info(
            "events.subscribed",
            label=sub_label,
            event_types=[et.value for et in event_types] if event_types else "all",
            total_subscribers=len(self._subscriptions),
        )

    def unsubscribe(self, handler: EventHandler) -> None:
        """Remove a previously registered handler.

        If the handler is not registered, this is a no-op.

        Args:
            handler: The same function object passed to subscribe().
        """
        before = len(self._subscriptions)
        self._subscriptions = [s for s in self._subscriptions if s.handler is not handler]
        removed = before - len(self._subscriptions)

        if removed:
            log.info(
                "events.unsubscribed",
                label=getattr(handler, "__name__", repr(handler)),
                total_subscribers=len(self._subscriptions),
            )

    def emit(self, event: GraphEvent) -> None:
        """Fire an event to all matching subscribers.

        Each handler is invoked in its own asyncio.Task — non-blocking.
        The emit call returns immediately.

        Args:
            event: The graph event to broadcast.
        """
        self._emit_count += 1

        matching = self._get_matching_subscriptions(event.event_type)
        if not matching:
            return

        for sub in matching:
            asyncio.create_task(
                self._invoke_handler(sub, event),
                name=f"event_handler_{sub.label}_{self._emit_count}",
            )

    @property
    def subscriber_count(self) -> int:
        """Number of currently registered handlers."""
        return len(self._subscriptions)

    @property
    def emit_count(self) -> int:
        """Total number of events emitted since creation."""
        return self._emit_count

    @property
    def handler_timeout_count(self) -> int:
        """Number of handler invocations that exceeded the timeout."""
        return self._handler_timeout_count

    @property
    def handler_error_count(self) -> int:
        """Number of handler invocations that raised exceptions."""
        return self._handler_error_count

    # -- Internal -----------------------------------------------------------

    def _get_matching_subscriptions(
        self, event_type: GraphEventType
    ) -> list[_Subscription]:
        """Return subscriptions whose filters match the event type."""
        return [
            sub
            for sub in self._subscriptions
            if sub.event_types is None or event_type in sub.event_types
        ]

    async def _invoke_handler(self, sub: _Subscription, event: GraphEvent) -> None:
        """Invoke a handler with timeout monitoring.

        - If the handler completes within the timeout: success.
        - If the handler exceeds the timeout: log a warning, but do NOT cancel.
        - If the handler raises: log the error, do not propagate.
        """
        try:
            await asyncio.wait_for(
                self._call_handler(sub.handler, event),
                timeout=self._handler_timeout,
            )
        except asyncio.TimeoutError:
            self._handler_timeout_count += 1
            log.warning(
                "events.handler_timeout",
                label=sub.label,
                event_type=event.event_type.value,
                timeout_seconds=self._handler_timeout,
            )
        except Exception as exc:
            self._handler_error_count += 1
            log.error(
                "events.handler_error",
                label=sub.label,
                event_type=event.event_type.value,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    @staticmethod
    async def _call_handler(handler: EventHandler, event: GraphEvent) -> None:
        """Call the handler. Separated for testability."""
        await handler(event)
