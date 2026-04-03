"""In-memory graph backend — wraps the existing GraphStore as MemoryGraphStore."""

from __future__ import annotations

from typing import Any

from neuroweave.graph.backends.base import AbstractGraphStore
from neuroweave.graph.store import (
    Edge,
    GraphEvent,
    GraphEventType,
    GraphStore,
    Node,
)


class MemoryGraphStore(GraphStore, AbstractGraphStore):
    """In-memory graph backend using NetworkX.

    All methods are async to satisfy the AbstractGraphStore interface.
    NetworkX operations are synchronous and fast — no actual await needed.
    """

    def __init__(self) -> None:
        GraphStore.__init__(self)

    async def initialize(self) -> None:
        """No-op for in-memory backend."""
        pass

    async def add_node(self, node: Node) -> Node:
        return GraphStore.add_node(self, node)

    async def get_node(self, node_id: str) -> dict[str, Any] | None:
        return GraphStore.get_node(self, node_id)

    async def find_nodes(
        self,
        node_type: str | None = None,
        name_contains: str | None = None,
    ) -> list[dict[str, Any]]:
        return GraphStore.find_nodes(self, node_type=node_type, name_contains=name_contains)

    async def add_edge(self, edge: Edge) -> Edge:
        return GraphStore.add_edge(self, edge)

    async def get_edges(
        self,
        source_id: str | None = None,
        target_id: str | None = None,
        relation: str | None = None,
    ) -> list[dict[str, Any]]:
        return GraphStore.get_edges(self, source_id=source_id, target_id=target_id, relation=relation)

    async def get_neighbors(self, node_id: str, depth: int = 1) -> list[dict[str, Any]]:
        return GraphStore.get_neighbors(self, node_id, depth=depth)

    async def update_node_properties(self, node_id: str, properties: dict[str, Any]) -> None:
        if node_id not in self._graph.nodes:
            return
        existing = self._graph.nodes[node_id].get("properties", {})
        merged = {**existing, **properties}
        self._graph.nodes[node_id]["properties"] = merged
        self._emit(GraphEvent(
            event_type=GraphEventType.NODE_UPDATED,
            data={"id": node_id, "properties": merged},
        ))

    async def to_dict(self) -> dict[str, Any]:
        return GraphStore.to_dict(self)
