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

from neuroweave.graph.store import NodeType
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


async def query_subgraph(
    store: Any,
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
        store: The graph store to query (async interface).
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

    # --- Phase 1: Resolve seed nodes ---
    if entities:
        seed_ids = await _resolve_entity_names(store, entities)
        if not seed_ids:
            log.info("query.no_seeds_found", entities=entities)
            return QueryResult(query_params=query_params)
        resolved_nodes = []
        for name in entities:
            matches = await store.find_nodes(name_contains=name)
            resolved_nodes.extend(matches)
    else:
        # No entity filter → all nodes are seeds
        all_nodes = await store.find_nodes()
        seed_ids = [n["id"] for n in all_nodes]
        resolved_nodes = all_nodes

    # --- Phase 2: Hop traversal ---
    if max_hops > 0 and entities:
        all_neighbors = []
        for sid in seed_ids:
            neighbors = await store.get_neighbors(sid, depth=max_hops)
            all_neighbors.extend(neighbors)
        reachable_ids = set(seed_ids) | {n["id"] for n in all_neighbors}
        result_nodes = list({n["id"]: n for n in [*resolved_nodes, *all_neighbors]}.values())
    else:
        reachable_ids = set(seed_ids)
        result_nodes = list({n["id"]: n for n in resolved_nodes}.values())

    # --- Phase 3: Collect and filter edges ---
    all_edges = await store.get_edges()
    result_edges = []
    for e in all_edges:
        if e.get("source_id") not in reachable_ids or e.get("target_id") not in reachable_ids:
            continue
        if relations and e.get("relation") not in relations:
            continue
        if e.get("confidence", 0.0) < min_confidence:
            continue
        result_edges.append(e)

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


async def _resolve_entity_names(store: Any, names: list[str]) -> list[str]:
    """Resolve entity names to node IDs (case-insensitive).

    For each name, finds the first node whose name matches (case-insensitive).
    Returns a deduplicated list of node IDs.
    """
    resolved: list[str] = []
    seen: set[str] = set()

    for name in names:
        matches = await store.find_nodes(name_contains=name)
        # Prefer exact case-insensitive match over substring match
        exact = [m for m in matches if m["name"].lower() == name.lower()]
        candidates = exact if exact else matches

        for match in candidates:
            nid = match["id"]
            if nid not in seen:
                resolved.append(nid)
                seen.add(nid)

    return resolved


# ---------------------------------------------------------------------------
# Typed query helpers (NW-002)
# ---------------------------------------------------------------------------


async def query_by_type(
    store: Any,
    entity_type: NodeType,
    relations: list[str] | None = None,
    max_hops: int = 1,
) -> QueryResult:
    """Return all nodes of the given type, optionally filtered by relation.

    Example:
        await query_by_type(store, NodeType.THEOREM, relations=["proves"])
    """
    nodes = await store.find_nodes(node_type=entity_type)
    if not nodes:
        return QueryResult(nodes=[], edges=[])
    node_ids = {n["id"] for n in nodes}
    all_edges = []
    for node_id in node_ids:
        edges = await store.get_edges(source_id=node_id)
        if relations:
            edges = [e for e in edges if e.get("relation") in relations]
        all_edges.extend(edges)
    return QueryResult(nodes=nodes, edges=all_edges)


async def get_proof_chain(
    store: Any,
    theorem_name: str,
    max_hops: int = 3,
) -> QueryResult:
    """Return the full dependency chain for a theorem: theorem -> lemmas -> definitions.

    Traverses USES, FOLLOWS_FROM, and PROVES relations up to max_hops deep.
    """
    proof_relations = {"uses", "follows_from", "proves", "verified_by"}
    nodes = await store.find_nodes(name_contains=theorem_name)
    if not nodes:
        return QueryResult(nodes=[], edges=[])
    root_id = nodes[0]["id"]
    neighbors = await store.get_neighbors(root_id, depth=max_hops)
    all_edges = await store.get_edges()
    relevant_ids = {root_id} | {n["id"] for n in neighbors}
    relevant_edges = [
        e for e in all_edges
        if e.get("source_id") in relevant_ids
        and e.get("target_id") in relevant_ids
        and e.get("relation") in proof_relations
    ]
    return QueryResult(nodes=[*nodes, *neighbors], edges=relevant_edges)


async def get_domain_graph(
    store: Any,
    domain_name: str,
) -> QueryResult:
    """Return all entities belonging to a mathematical domain."""
    domain_nodes = await store.find_nodes(node_type=NodeType.DOMAIN, name_contains=domain_name)
    if not domain_nodes:
        return QueryResult(nodes=[], edges=[])
    domain_ids = {n["id"] for n in domain_nodes}
    all_edges = await store.get_edges()
    member_edges = [
        e for e in all_edges
        if e.get("target_id") in domain_ids and e.get("relation") == "belongs_to"
    ]
    member_ids = {e["source_id"] for e in member_edges}
    member_nodes = []
    for nid in member_ids:
        node = await store.get_node(nid)
        if node:
            member_nodes.append(node)
    return QueryResult(
        nodes=[*domain_nodes, *member_nodes],
        edges=member_edges,
    )
