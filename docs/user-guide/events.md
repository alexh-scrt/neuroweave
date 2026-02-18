# Event Subscription

NeuroWeave provides an async event system for real-time notifications when the knowledge graph is mutated. This is useful for agent integrations that need to react to new knowledge as it's discovered.

## Basic Usage

```python
from neuroweave import NeuroWeave, EventType
from neuroweave.graph.store import GraphEvent

async def on_new_entity(event: GraphEvent) -> None:
    print(f"New entity: {event.data['name']}")

async with NeuroWeave(llm_provider="mock") as nw:
    nw.subscribe(on_new_entity, event_types={EventType.NODE_ADDED})

    await nw.process("My wife Lena loves sushi")
    # Prints: New entity: Lena
    # Prints: New entity: sushi
```

## Event Types

| Event Type | Emitted When |
|------------|-------------|
| `EventType.NODE_ADDED` | A new node is created in the graph |
| `EventType.NODE_UPDATED` | An existing node's properties are updated |
| `EventType.EDGE_ADDED` | A new edge is created in the graph |
| `EventType.EDGE_UPDATED` | An existing edge's properties are updated |

## Subscribing

```python
# Subscribe to specific event types
nw.subscribe(handler, event_types={EventType.NODE_ADDED, EventType.EDGE_ADDED})

# Subscribe to ALL events (no filter)
nw.subscribe(handler)

# Unsubscribe
nw.unsubscribe(handler)
```

Subscribing the same handler twice is a no-op. Unsubscribing a handler that isn't subscribed is also safe.

## Event Data

Each event is a `GraphEvent` with:

```python
async def handler(event: GraphEvent) -> None:
    event.event_type   # EventType enum value
    event.data         # dict with node/edge data
    event.timestamp    # when the event occurred
```

For `NODE_ADDED` / `NODE_UPDATED`, `event.data` contains node fields (`name`, `node_type`, `node_id`, etc.). For `EDGE_ADDED` / `EDGE_UPDATED`, it contains edge fields (`source_id`, `target_id`, `relation`, `confidence`, etc.).

## Error Isolation

Handler exceptions are caught, logged, and counted — they never propagate to the emitter or affect other handlers. A slow handler (>5s by default) triggers a warning but is not cancelled.

```python
async def unreliable_handler(event: GraphEvent) -> None:
    raise ValueError("oops")  # Won't crash the system

nw.subscribe(unreliable_handler)  # Safe — errors are isolated
```

## Advanced: Direct EventBus Access

For advanced use cases, you can access the `EventBus` directly:

```python
bus = nw.event_bus
print(bus.emit_count)          # Total events emitted
print(bus.subscriber_count)    # Number of active subscribers
print(bus.error_count)         # Handler errors caught
print(bus.timeout_count)       # Slow handler warnings
```
