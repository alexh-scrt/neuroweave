"""Tests for the EventBus pub/sub system."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from neuroweave.events import EventBus
from neuroweave.graph.store import (
    GraphEvent,
    GraphEventType,
    GraphStore,
    NodeType,
    make_edge,
    make_node,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _drain() -> None:
    """Yield control so that all pending tasks can run.

    EventBus.emit() fires handlers via create_task(). This helper
    gives them a chance to execute before we assert.
    """
    await asyncio.sleep(0)
    await asyncio.sleep(0)  # Two yields for nested task scheduling


# ---------------------------------------------------------------------------
# Subscription lifecycle
# ---------------------------------------------------------------------------


class TestSubscribeUnsubscribe:
    def test_subscribe_increases_count(self):
        bus = EventBus()
        handler = AsyncMock()
        bus.subscribe(handler)
        assert bus.subscriber_count == 1

    def test_unsubscribe_decreases_count(self):
        bus = EventBus()
        handler = AsyncMock()
        bus.subscribe(handler)
        bus.unsubscribe(handler)
        assert bus.subscriber_count == 0

    def test_unsubscribe_unknown_handler_is_noop(self):
        bus = EventBus()
        handler = AsyncMock()
        bus.unsubscribe(handler)  # Should not raise
        assert bus.subscriber_count == 0

    def test_duplicate_subscribe_is_ignored(self):
        bus = EventBus()
        handler = AsyncMock()
        bus.subscribe(handler)
        bus.subscribe(handler)  # Duplicate
        assert bus.subscriber_count == 1

    def test_multiple_handlers(self):
        bus = EventBus()
        h1 = AsyncMock()
        h2 = AsyncMock()
        h3 = AsyncMock()
        bus.subscribe(h1)
        bus.subscribe(h2)
        bus.subscribe(h3)
        assert bus.subscriber_count == 3

    def test_unsubscribe_only_removes_target(self):
        bus = EventBus()
        h1 = AsyncMock()
        h2 = AsyncMock()
        bus.subscribe(h1)
        bus.subscribe(h2)
        bus.unsubscribe(h1)
        assert bus.subscriber_count == 1


# ---------------------------------------------------------------------------
# Event emission & delivery
# ---------------------------------------------------------------------------


class TestEmitDelivery:
    async def test_handler_receives_event(self):
        bus = EventBus()
        received: list[GraphEvent] = []

        async def handler(event: GraphEvent) -> None:
            received.append(event)

        bus.subscribe(handler)
        event = GraphEvent(GraphEventType.NODE_ADDED, data={"id": "n1", "name": "Test"})
        bus.emit(event)
        await _drain()

        assert len(received) == 1
        assert received[0] is event

    async def test_multiple_handlers_all_receive(self):
        bus = EventBus()
        r1: list[GraphEvent] = []
        r2: list[GraphEvent] = []

        async def h1(event: GraphEvent) -> None:
            r1.append(event)

        async def h2(event: GraphEvent) -> None:
            r2.append(event)

        bus.subscribe(h1)
        bus.subscribe(h2)

        event = GraphEvent(GraphEventType.EDGE_ADDED, data={"id": "e1"})
        bus.emit(event)
        await _drain()

        assert len(r1) == 1
        assert len(r2) == 1

    async def test_emit_count_tracks(self):
        bus = EventBus()
        bus.subscribe(AsyncMock())

        bus.emit(GraphEvent(GraphEventType.NODE_ADDED, data={}))
        bus.emit(GraphEvent(GraphEventType.EDGE_ADDED, data={}))
        bus.emit(GraphEvent(GraphEventType.NODE_UPDATED, data={}))

        assert bus.emit_count == 3

    async def test_no_subscribers_emit_is_noop(self):
        bus = EventBus()
        bus.emit(GraphEvent(GraphEventType.NODE_ADDED, data={}))
        assert bus.emit_count == 1  # Counted but no error

    async def test_unsubscribed_handler_not_called(self):
        bus = EventBus()
        handler = AsyncMock()
        bus.subscribe(handler)
        bus.unsubscribe(handler)

        bus.emit(GraphEvent(GraphEventType.NODE_ADDED, data={}))
        await _drain()

        handler.assert_not_called()


# ---------------------------------------------------------------------------
# Event type filtering
# ---------------------------------------------------------------------------


class TestEventTypeFilter:
    async def test_filter_receives_matching_type(self):
        bus = EventBus()
        received: list[GraphEvent] = []

        async def handler(event: GraphEvent) -> None:
            received.append(event)

        bus.subscribe(handler, event_types={GraphEventType.NODE_ADDED})

        bus.emit(GraphEvent(GraphEventType.NODE_ADDED, data={"match": True}))
        bus.emit(GraphEvent(GraphEventType.EDGE_ADDED, data={"match": False}))
        await _drain()

        assert len(received) == 1
        assert received[0].data["match"] is True

    async def test_filter_multiple_types(self):
        bus = EventBus()
        received: list[GraphEvent] = []

        async def handler(event: GraphEvent) -> None:
            received.append(event)

        bus.subscribe(
            handler,
            event_types={GraphEventType.NODE_ADDED, GraphEventType.EDGE_ADDED},
        )

        bus.emit(GraphEvent(GraphEventType.NODE_ADDED, data={}))
        bus.emit(GraphEvent(GraphEventType.EDGE_ADDED, data={}))
        bus.emit(GraphEvent(GraphEventType.NODE_UPDATED, data={}))
        await _drain()

        assert len(received) == 2

    async def test_no_filter_receives_all(self):
        bus = EventBus()
        received: list[GraphEvent] = []

        async def handler(event: GraphEvent) -> None:
            received.append(event)

        bus.subscribe(handler)  # No event_types filter

        bus.emit(GraphEvent(GraphEventType.NODE_ADDED, data={}))
        bus.emit(GraphEvent(GraphEventType.EDGE_ADDED, data={}))
        bus.emit(GraphEvent(GraphEventType.NODE_UPDATED, data={}))
        bus.emit(GraphEvent(GraphEventType.EDGE_UPDATED, data={}))
        await _drain()

        assert len(received) == 4

    async def test_mixed_filtered_and_unfiltered(self):
        bus = EventBus()
        filtered: list[GraphEvent] = []
        unfiltered: list[GraphEvent] = []

        async def h_filtered(event: GraphEvent) -> None:
            filtered.append(event)

        async def h_unfiltered(event: GraphEvent) -> None:
            unfiltered.append(event)

        bus.subscribe(h_filtered, event_types={GraphEventType.NODE_ADDED})
        bus.subscribe(h_unfiltered)

        bus.emit(GraphEvent(GraphEventType.NODE_ADDED, data={}))
        bus.emit(GraphEvent(GraphEventType.EDGE_ADDED, data={}))
        await _drain()

        assert len(filtered) == 1
        assert len(unfiltered) == 2


# ---------------------------------------------------------------------------
# Slow handler timeout
# ---------------------------------------------------------------------------


class TestHandlerTimeout:
    async def test_slow_handler_triggers_timeout_count(self):
        bus = EventBus(handler_timeout=0.05)  # 50ms timeout

        async def slow_handler(event: GraphEvent) -> None:
            await asyncio.sleep(1.0)  # Way over timeout

        bus.subscribe(slow_handler)
        bus.emit(GraphEvent(GraphEventType.NODE_ADDED, data={}))

        # Wait enough for the timeout to fire
        await asyncio.sleep(0.15)

        assert bus.handler_timeout_count == 1

    async def test_fast_handler_no_timeout(self):
        bus = EventBus(handler_timeout=1.0)

        async def fast_handler(event: GraphEvent) -> None:
            pass  # Instant

        bus.subscribe(fast_handler)
        bus.emit(GraphEvent(GraphEventType.NODE_ADDED, data={}))
        await _drain()

        assert bus.handler_timeout_count == 0

    async def test_slow_handler_does_not_block_others(self):
        bus = EventBus(handler_timeout=0.05)
        fast_received: list[GraphEvent] = []

        async def slow_handler(event: GraphEvent) -> None:
            await asyncio.sleep(1.0)

        async def fast_handler(event: GraphEvent) -> None:
            fast_received.append(event)

        bus.subscribe(slow_handler)
        bus.subscribe(fast_handler)

        bus.emit(GraphEvent(GraphEventType.NODE_ADDED, data={}))
        await _drain()

        # Fast handler should have already received the event
        assert len(fast_received) == 1


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestHandlerErrors:
    async def test_handler_exception_does_not_propagate(self):
        bus = EventBus()

        async def bad_handler(event: GraphEvent) -> None:
            raise ValueError("something went wrong")

        bus.subscribe(bad_handler)
        bus.emit(GraphEvent(GraphEventType.NODE_ADDED, data={}))
        await _drain()

        assert bus.handler_error_count == 1

    async def test_error_in_one_handler_doesnt_affect_others(self):
        bus = EventBus()
        received: list[GraphEvent] = []

        async def bad_handler(event: GraphEvent) -> None:
            raise RuntimeError("boom")

        async def good_handler(event: GraphEvent) -> None:
            received.append(event)

        bus.subscribe(bad_handler)
        bus.subscribe(good_handler)

        bus.emit(GraphEvent(GraphEventType.NODE_ADDED, data={}))
        await _drain()

        assert len(received) == 1
        assert bus.handler_error_count == 1


# ---------------------------------------------------------------------------
# GraphStore ↔ EventBus integration
# ---------------------------------------------------------------------------


class TestGraphStoreIntegration:
    async def test_node_added_fires_event(self):
        bus = EventBus()
        store = GraphStore()
        store.set_event_bus(bus)

        received: list[GraphEvent] = []

        async def handler(event: GraphEvent) -> None:
            received.append(event)

        bus.subscribe(handler, event_types={GraphEventType.NODE_ADDED})

        store.add_node(make_node("Alice", NodeType.ENTITY, node_id="alice"))
        await _drain()

        assert len(received) == 1
        assert received[0].event_type == GraphEventType.NODE_ADDED
        assert received[0].data["name"] == "Alice"

    async def test_edge_added_fires_event(self):
        bus = EventBus()
        store = GraphStore()
        store.set_event_bus(bus)

        received: list[GraphEvent] = []

        async def handler(event: GraphEvent) -> None:
            received.append(event)

        bus.subscribe(handler, event_types={GraphEventType.EDGE_ADDED})

        store.add_node(make_node("A", NodeType.ENTITY, node_id="a"))
        store.add_node(make_node("B", NodeType.ENTITY, node_id="b"))
        store.add_edge(make_edge("a", "b", "knows", 0.9, edge_id="e1"))
        await _drain()

        assert len(received) == 1
        assert received[0].event_type == GraphEventType.EDGE_ADDED
        assert received[0].data["relation"] == "knows"

    async def test_node_update_fires_update_event(self):
        bus = EventBus()
        store = GraphStore()
        store.set_event_bus(bus)

        received: list[GraphEvent] = []

        async def handler(event: GraphEvent) -> None:
            received.append(event)

        bus.subscribe(handler, event_types={GraphEventType.NODE_UPDATED})

        node = make_node("Alice", NodeType.ENTITY, node_id="alice")
        store.add_node(node)  # First add → NODE_ADDED
        store.add_node(node)  # Second add → NODE_UPDATED (same ID)
        await _drain()

        assert len(received) == 1
        assert received[0].event_type == GraphEventType.NODE_UPDATED

    async def test_multiple_mutations_fire_multiple_events(self):
        bus = EventBus()
        store = GraphStore()
        store.set_event_bus(bus)

        all_events: list[GraphEvent] = []

        async def handler(event: GraphEvent) -> None:
            all_events.append(event)

        bus.subscribe(handler)  # Receive all events

        store.add_node(make_node("A", NodeType.ENTITY, node_id="a"))
        store.add_node(make_node("B", NodeType.ENTITY, node_id="b"))
        store.add_edge(make_edge("a", "b", "knows", 0.9, edge_id="e1"))
        await _drain()

        assert len(all_events) == 3
        types = [e.event_type for e in all_events]
        assert types.count(GraphEventType.NODE_ADDED) == 2
        assert types.count(GraphEventType.EDGE_ADDED) == 1

    async def test_event_bus_takes_priority_over_queue(self):
        """When both EventBus and queue are set, only EventBus receives events."""
        bus = EventBus()
        queue: asyncio.Queue[GraphEvent] = asyncio.Queue()
        store = GraphStore()
        store.set_event_queue(queue)
        store.set_event_bus(bus)

        bus_events: list[GraphEvent] = []

        async def handler(event: GraphEvent) -> None:
            bus_events.append(event)

        bus.subscribe(handler)

        store.add_node(make_node("X", NodeType.ENTITY, node_id="x"))
        await _drain()

        assert len(bus_events) == 1
        assert queue.empty()  # Queue should NOT have received the event

    async def test_no_bus_falls_back_to_queue(self):
        """Without EventBus, events still go to the legacy queue."""
        queue: asyncio.Queue[GraphEvent] = asyncio.Queue()
        store = GraphStore()
        store.set_event_queue(queue)
        # No event_bus set

        store.add_node(make_node("X", NodeType.ENTITY, node_id="x"))

        assert not queue.empty()
        event = queue.get_nowait()
        assert event.event_type == GraphEventType.NODE_ADDED

    async def test_no_bus_no_queue_is_silent(self):
        """Without either, mutations still work — events are just dropped."""
        store = GraphStore()
        store.add_node(make_node("X", NodeType.ENTITY, node_id="x"))
        assert store.node_count == 1  # Mutation still succeeded


# ---------------------------------------------------------------------------
# Label and metadata
# ---------------------------------------------------------------------------


class TestLabels:
    def test_custom_label(self):
        bus = EventBus()
        handler = AsyncMock()
        bus.subscribe(handler, label="my_custom_label")
        # Just verify it doesn't error — label is for logging

    def test_auto_label_from_function_name(self):
        bus = EventBus()

        async def my_named_handler(event: GraphEvent) -> None:
            pass

        bus.subscribe(my_named_handler)
        assert bus.subscriber_count == 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    async def test_emit_with_no_matching_subscribers(self):
        bus = EventBus()

        async def node_only(event: GraphEvent) -> None:
            pass

        bus.subscribe(node_only, event_types={GraphEventType.NODE_ADDED})

        # Emit an edge event — no subscriber matches
        bus.emit(GraphEvent(GraphEventType.EDGE_ADDED, data={}))
        await _drain()

        assert bus.emit_count == 1  # Still counted

    async def test_rapid_fire_events(self):
        bus = EventBus()
        count = 0

        async def counter(event: GraphEvent) -> None:
            nonlocal count
            count += 1

        bus.subscribe(counter)

        for i in range(100):
            bus.emit(GraphEvent(GraphEventType.NODE_ADDED, data={"i": i}))

        # Give all 100 tasks a chance to run
        for _ in range(10):
            await asyncio.sleep(0)

        assert count == 100

    async def test_subscribe_during_emit_does_not_crash(self):
        """Subscribing new handlers while events are being processed."""
        bus = EventBus()
        late_received: list[GraphEvent] = []

        async def late_handler(event: GraphEvent) -> None:
            late_received.append(event)

        async def first_handler(event: GraphEvent) -> None:
            # Subscribe a new handler during event processing
            bus.subscribe(late_handler, label="late")

        bus.subscribe(first_handler)
        bus.emit(GraphEvent(GraphEventType.NODE_ADDED, data={}))
        await _drain()

        # Late handler was subscribed but shouldn't have received THIS event
        assert bus.subscriber_count == 2

    async def test_unsubscribe_during_emit_does_not_crash(self):
        """Unsubscribing while events are being dispatched."""
        bus = EventBus()
        received: list[GraphEvent] = []

        async def self_removing_handler(event: GraphEvent) -> None:
            received.append(event)
            bus.unsubscribe(self_removing_handler)

        bus.subscribe(self_removing_handler)
        bus.emit(GraphEvent(GraphEventType.NODE_ADDED, data={}))
        await _drain()

        assert len(received) == 1
        assert bus.subscriber_count == 0

        # Second emit should not deliver to removed handler
        bus.emit(GraphEvent(GraphEventType.NODE_ADDED, data={}))
        await _drain()
        assert len(received) == 1
