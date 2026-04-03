"""In-memory graph backend — wraps the existing GraphStore as MemoryGraphStore."""

from __future__ import annotations

from typing import Any

from neuroweave.graph.backends.base import AbstractGraphStore
from neuroweave.graph.store import (
    GraphEvent,
    GraphEventType,
    GraphStore,
)


class MemoryGraphStore(GraphStore, AbstractGraphStore):
    """In-memory graph backend using NetworkX.

    This is the original GraphStore with the AbstractGraphStore interface.
    All existing functionality is inherited from GraphStore.
    """

    def __init__(self) -> None:
        GraphStore.__init__(self)

    def update_node_properties(self, node_id: str, properties: dict[str, Any]) -> None:
        """Merge new properties into an existing node. New value wins on conflict."""
        if node_id not in self._graph.nodes:
            return
        existing = self._graph.nodes[node_id].get("properties", {})
        merged = {**existing, **properties}
        self._graph.nodes[node_id]["properties"] = merged
        self._emit(GraphEvent(
            event_type=GraphEventType.NODE_UPDATED,
            data={"id": node_id, "properties": merged},
        ))
