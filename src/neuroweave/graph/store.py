"""In-memory knowledge graph store backed by NetworkX.

This is the POC graph backend. The interface is designed so that swapping
in Neo4j later requires no changes to callers — only a new implementation
of the same methods.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

import networkx as nx

from neuroweave.logging import get_logger

log = get_logger("graph")


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

class NodeType(str, Enum):
    ENTITY = "entity"
    CONCEPT = "concept"
    PREFERENCE = "preference"
    EPISODE = "episode"
    EXPERIENCE = "experience"


@dataclass(frozen=True, slots=True)
class Node:
    """A node in the knowledge graph."""

    id: str
    name: str
    node_type: NodeType
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(frozen=True, slots=True)
class Edge:
    """A directed, typed, confidence-weighted edge."""

    id: str
    source_id: str
    target_id: str
    relation: str
    confidence: float
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Graph events — consumed by WebSocket broadcaster
# ---------------------------------------------------------------------------

class GraphEventType(str, Enum):
    NODE_ADDED = "node_added"
    EDGE_ADDED = "edge_added"
    NODE_UPDATED = "node_updated"
    EDGE_UPDATED = "edge_updated"


@dataclass(frozen=True, slots=True)
class GraphEvent:
    event_type: GraphEventType
    data: dict[str, Any]


# ---------------------------------------------------------------------------
# Graph store
# ---------------------------------------------------------------------------

class GraphStore:
    """In-memory knowledge graph with event emission.

    Events are dispatched through an EventBus (preferred) or a legacy
    asyncio.Queue. Since v0.1.0, NeuroWeave is fully async — the agent,
    extraction pipeline, and visualization server all share the same
    asyncio event loop.
    """

    def __init__(self) -> None:
        self._graph = nx.MultiDiGraph()
        self._event_queue: asyncio.Queue[GraphEvent] | None = None
        self._event_bus: Any | None = None  # EventBus (imported lazily to avoid circular)

    # -- Event wiring -------------------------------------------------------

    def set_event_bus(self, bus: Any) -> None:
        """Attach an EventBus to receive graph mutation events (preferred).

        When an EventBus is set, events are emitted through it. The legacy
        asyncio.Queue is still supported as a fallback.
        """
        self._event_bus = bus

    @property
    def event_bus(self) -> Any | None:
        return self._event_bus

    def set_event_queue(self, q: asyncio.Queue[GraphEvent]) -> None:
        """Attach an asyncio queue to receive graph mutation events (legacy)."""
        self._event_queue = q

    @property
    def event_queue(self) -> asyncio.Queue[GraphEvent] | None:
        return self._event_queue

    def _emit(self, event: GraphEvent) -> None:
        """Dispatch event through EventBus (preferred) or legacy queue."""
        if self._event_bus is not None:
            self._event_bus.emit(event)
        elif self._event_queue is not None:
            try:
                self._event_queue.put_nowait(event)
            except asyncio.QueueFull:
                log.warning("graph.event_queue_full", event_type=event.event_type.value)

    # -- Node operations ----------------------------------------------------

    def add_node(self, node: Node) -> Node:
        """Add a node to the graph. If a node with the same ID exists, update it."""
        is_update = self._graph.has_node(node.id)

        self._graph.add_node(
            node.id,
            name=node.name,
            node_type=node.node_type.value,
            properties=node.properties,
            created_at=node.created_at,
        )

        event_type = GraphEventType.NODE_UPDATED if is_update else GraphEventType.NODE_ADDED
        self._emit(GraphEvent(event_type=event_type, data=self._node_to_dict(node.id)))

        log.info(
            f"graph.node_{'updated' if is_update else 'added'}",
            node_id=node.id,
            name=node.name,
            node_type=node.node_type.value,
        )
        return node

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        """Return node data dict or None if not found."""
        if self._graph.has_node(node_id):
            return self._node_to_dict(node_id)
        return None

    def find_nodes(
        self,
        node_type: NodeType | None = None,
        name_contains: str | None = None,
    ) -> list[dict[str, Any]]:
        """Find nodes by type and/or name substring (case-insensitive)."""
        results = []
        for nid, data in self._graph.nodes(data=True):
            if node_type and data.get("node_type") != node_type.value:
                continue
            if name_contains and name_contains.lower() not in data.get("name", "").lower():
                continue
            results.append(self._node_to_dict(nid))
        return results

    # -- Edge operations ----------------------------------------------------

    def add_edge(self, edge: Edge) -> Edge:
        """Add a directed edge between two existing nodes.

        Raises:
            KeyError: If source or target node doesn't exist.
        """
        if not self._graph.has_node(edge.source_id):
            raise KeyError(f"Source node '{edge.source_id}' not found")
        if not self._graph.has_node(edge.target_id):
            raise KeyError(f"Target node '{edge.target_id}' not found")

        self._graph.add_edge(
            edge.source_id,
            edge.target_id,
            key=edge.id,
            relation=edge.relation,
            confidence=edge.confidence,
            properties=edge.properties,
            created_at=edge.created_at,
        )

        edge_dict = self._edge_to_dict(edge.source_id, edge.target_id, edge.id)
        self._emit(GraphEvent(event_type=GraphEventType.EDGE_ADDED, data=edge_dict))

        log.info(
            "graph.edge_added",
            edge_id=edge.id,
            source=edge.source_id,
            target=edge.target_id,
            relation=edge.relation,
            confidence=edge.confidence,
        )
        return edge

    def get_edges(
        self,
        source_id: str | None = None,
        target_id: str | None = None,
        relation: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query edges by source, target, and/or relation type."""
        results = []
        for src, tgt, key, data in self._graph.edges(data=True, keys=True):
            if source_id and src != source_id:
                continue
            if target_id and tgt != target_id:
                continue
            if relation and data.get("relation") != relation:
                continue
            results.append(self._edge_to_dict(src, tgt, key))
        return results

    def get_neighbors(self, node_id: str, depth: int = 1) -> list[dict[str, Any]]:
        """Get all nodes within `depth` hops of the given node."""
        if not self._graph.has_node(node_id):
            return []
        # Use underlying undirected view for reachability
        undirected = self._graph.to_undirected(as_view=True)
        neighbor_ids = nx.single_source_shortest_path_length(undirected, node_id, cutoff=depth)
        return [
            self._node_to_dict(nid)
            for nid in neighbor_ids
            if nid != node_id
        ]

    # -- Stats & serialization ----------------------------------------------

    @property
    def node_count(self) -> int:
        return self._graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self._graph.number_of_edges()

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full graph to a dict suitable for JSON/visualization."""
        nodes = [self._node_to_dict(nid) for nid in self._graph.nodes()]
        edges = [
            self._edge_to_dict(src, tgt, key)
            for src, tgt, key in self._graph.edges(keys=True)
        ]
        return {
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "node_count": self.node_count,
                "edge_count": self.edge_count,
            },
        }

    # -- Internal helpers ---------------------------------------------------

    def _node_to_dict(self, node_id: str) -> dict[str, Any]:
        data = self._graph.nodes[node_id]
        return {"id": node_id, **data}

    def _edge_to_dict(self, source_id: str, target_id: str, key: str) -> dict[str, Any]:
        data = self._graph.edges[source_id, target_id, key]
        return {"id": key, "source_id": source_id, "target_id": target_id, **data}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_node(
    name: str,
    node_type: NodeType,
    *,
    node_id: str | None = None,
    **properties: Any,
) -> Node:
    """Convenience factory for creating a Node with an auto-generated ID."""
    return Node(
        id=node_id or f"n_{uuid4().hex[:12]}",
        name=name,
        node_type=node_type,
        properties=properties,
    )


def make_edge(
    source_id: str,
    target_id: str,
    relation: str,
    confidence: float,
    *,
    edge_id: str | None = None,
    **properties: Any,
) -> Edge:
    """Convenience factory for creating an Edge with an auto-generated ID."""
    return Edge(
        id=edge_id or f"e_{uuid4().hex[:12]}",
        source_id=source_id,
        target_id=target_id,
        relation=relation,
        confidence=confidence,
        properties=properties,
    )
