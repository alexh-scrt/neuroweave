"""Abstract base for all graph storage backends."""

from __future__ import annotations

import abc
from typing import Any

from neuroweave.graph.store import Edge, Node


class AbstractGraphStore(abc.ABC):
    """Interface contract for all NeuroWeave graph backends.

    All data methods are async to support both in-memory (trivially async)
    and remote backends (Neo4j, etc.) without blocking the event loop.
    """

    @abc.abstractmethod
    async def initialize(self) -> None:
        """Create indexes and constraints. Called once on startup. Must be idempotent."""
        raise NotImplementedError

    @abc.abstractmethod
    async def set_event_queue(self, q: Any) -> None:
        """Attach an event queue. Events are pushed here on mutations."""
        raise NotImplementedError

    @abc.abstractmethod
    async def add_node(self, node: Node) -> Node:
        """Add a node. Returns the node (possibly with db-assigned id)."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_node(self, node_id: str) -> dict[str, Any] | None:
        """Return node dict by id, or None if not found."""
        raise NotImplementedError

    @abc.abstractmethod
    async def find_nodes(
        self,
        node_type: str | None = None,
        name_contains: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return all nodes matching the given filters."""
        raise NotImplementedError

    @abc.abstractmethod
    async def add_edge(self, edge: Edge) -> Edge:
        """Add a directed edge. Returns the edge."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_edges(
        self,
        source_id: str | None = None,
        target_id: str | None = None,
        relation: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return edges matching any combination of source, target, relation."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_neighbors(self, node_id: str, depth: int = 1) -> list[dict[str, Any]]:
        """Return all nodes within `depth` hops of node_id via BFS."""
        raise NotImplementedError

    @abc.abstractmethod
    async def update_node_properties(self, node_id: str, properties: dict[str, Any]) -> None:
        """Merge new properties into an existing node. Existing keys are preserved;
        new keys are added. Conflicts: new value wins."""
        raise NotImplementedError

    @abc.abstractmethod
    async def to_dict(self) -> dict[str, Any]:
        """Full serialization: {"nodes": [...], "edges": [...], "stats": {...}}."""
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def node_count(self) -> int: ...

    @property
    @abc.abstractmethod
    def edge_count(self) -> int: ...
