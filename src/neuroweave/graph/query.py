"""Structured query engine for the knowledge graph.

Provides a query_subgraph() function that filters the graph by entities,
relations, confidence thresholds, and hop traversal depth. Returns a
QueryResult with matching nodes, edges, and traversal metadata.

This is the "Tier 1" query path — deterministic, no LLM calls, fast.
The natural language query planner (Step 12) will translate NL questions
into calls to this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from neuroweave.graph.store import GraphStore
from neuroweave.logging import get_logger

log = get_logger("query")


@dataclass(frozen=True, slots=True)
class QueryResult:
    """Result of a structured graph query.

    Attributes:
        nodes: List of matching node dicts (id, name, node_type, properties, ...).
        edges: List of matching edge dicts (id, source_id, target_id, relation, confidence, ...).
        seed_node_ids: The node IDs that matched the initial entity filter (before hop traversal).
        hops_traversed: The actual max_hops value used.
        query_params: The original query parameters for transparency/debugging.
    """

    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    seed_node_ids: list[str] = field(default_factory=list)
    hops_traversed: int = 0
    query_params: dict[str, Any] = field(default_factory=dict)

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    @property
    def is_empty(self) -> bool:
        return not self.nodes and not self.edges

    def node_names(self) -> set[str]:
        """Convenience: set of all node names in the result."""
        return {n["name"] for n in self.nodes}

    def relation_types(self) -> set[str]:
        """Convenience: set of all relation types in the result."""
        return {e["relation"] for e in self.edges}

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON / API responses."""
        return {
            "nodes": self.nodes,
            "edges": self.edges,
            "seed_node_ids": self.seed_node_ids,
            "hops_traversed": self.hops_traversed,
            "stats": {
                "node_count": self.node_count,
                "edge_count": self.edge_count,
            },
        }


def query_subgraph(
    store: GraphStore,
    *,
    entities: list[str] | None = None,
    relations: list[str] | None = None,
    min_confidence: float = 0.0,
    max_hops: int = 1,
) -> QueryResult:
    """Query the graph for a filtered subgraph.

    The query works in two phases:

    1. **Seed resolution** — find nodes matching the `entities` names (case-insensitive).
       If no entities are specified, all nodes are seeds (whole-graph query).

    2. **Hop traversal** — starting from seed nodes, walk `max_hops` hops through
       the graph (following edges in either direction). Collect all reachable nodes.

    After traversal, edges are filtered:
    - Only edges between collected nodes are included.
    - If `relations` is specified, only edges with matching relation types are included.
    - If `min_confidence` > 0, only edges meeting the threshold are included.

    Args:
        store: The graph store to query.
        entities: Entity names to start from (case-insensitive match). None = all nodes.
        relations: Relation types to include. None = all relations.
        min_confidence: Minimum edge confidence threshold (0.0 to 1.0).
        max_hops: How many hops to traverse from seed nodes (0 = seeds only).

    Returns:
        QueryResult with matching nodes, edges, and metadata.
    """
    query_params = {
        "entities": entities,
        "relations": relations,
        "min_confidence": min_confidence,
        "max_hops": max_hops,
    }

    graph = store._graph  # Access the underlying NetworkX graph directly

    # --- Phase 1: Resolve seed nodes ---
    if entities:
        seed_ids = _resolve_entity_names(store, entities)
        if not seed_ids:
            log.info("query.no_seeds_found", entities=entities)
            return QueryResult(query_params=query_params)
    else:
        # No entity filter → all nodes are seeds
        seed_ids = list(graph.nodes())

    # --- Phase 2: Hop traversal ---
    if max_hops > 0 and entities:
        # Traverse from seeds using undirected view (follow edges both ways)
        reachable_ids = set()
        undirected = graph.to_undirected(as_view=True)
        for sid in seed_ids:
            if undirected.has_node(sid):
                paths = nx.single_source_shortest_path_length(undirected, sid, cutoff=max_hops)
                reachable_ids.update(paths.keys())
    else:
        # max_hops=0 or no entity filter → just the seeds
        reachable_ids = set(seed_ids)

    # --- Phase 3: Collect nodes ---
    result_nodes = []
    for nid in reachable_ids:
        if graph.has_node(nid):
            result_nodes.append(store._node_to_dict(nid))

    # --- Phase 4: Collect and filter edges ---
    result_edges = []
    for src, tgt, key, data in graph.edges(data=True, keys=True):
        # Both endpoints must be in the reachable set
        if src not in reachable_ids or tgt not in reachable_ids:
            continue

        # Relation type filter
        if relations and data.get("relation") not in relations:
            continue

        # Confidence filter
        if data.get("confidence", 0.0) < min_confidence:
            continue

        result_edges.append(store._edge_to_dict(src, tgt, key))

    log.info(
        "query.complete",
        seed_count=len(seed_ids),
        nodes_returned=len(result_nodes),
        edges_returned=len(result_edges),
        max_hops=max_hops,
    )

    return QueryResult(
        nodes=result_nodes,
        edges=result_edges,
        seed_node_ids=list(seed_ids),
        hops_traversed=max_hops,
        query_params=query_params,
    )


def _resolve_entity_names(store: GraphStore, names: list[str]) -> list[str]:
    """Resolve entity names to node IDs (case-insensitive).

    For each name, finds the first node whose name matches (case-insensitive).
    Returns a deduplicated list of node IDs.
    """
    resolved: list[str] = []
    seen: set[str] = set()

    for name in names:
        matches = store.find_nodes(name_contains=name)
        # Prefer exact case-insensitive match over substring match
        exact = [m for m in matches if m["name"].lower() == name.lower()]
        candidates = exact if exact else matches

        for match in candidates:
            nid = match["id"]
            if nid not in seen:
                resolved.append(nid)
                seen.add(nid)

    return resolved
