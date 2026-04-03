"""Bridge between the extraction pipeline and the graph store.

Takes ExtractionResult and materializes entities/relations into the graph.
Handles deduplication by name — if an entity with the same name exists, reuse it.
Cross-session dedup: checks the persistent store for existing nodes.
"""

from __future__ import annotations

from typing import Any

from neuroweave.extraction.pipeline import ExtractionResult
from neuroweave.graph.store import (
    NodeType,
    make_edge,
    make_node,
)
from neuroweave.logging import get_logger

log = get_logger("ingest")

# Map extraction entity_type strings to graph NodeType
_TYPE_MAP: dict[str, NodeType] = {
    # existing
    "person": NodeType.ENTITY,
    "organization": NodeType.ENTITY,
    "place": NodeType.ENTITY,
    "tool": NodeType.CONCEPT,
    "concept": NodeType.CONCEPT,
    "preference": NodeType.PREFERENCE,

    # scientific — map directly
    "theorem": NodeType.THEOREM,
    "lemma": NodeType.LEMMA,
    "conjecture": NodeType.CONJECTURE,
    "proof": NodeType.PROOF,
    "definition": NodeType.DEFINITION,
    "example": NodeType.EXAMPLE,
    "paper": NodeType.PAPER,
    "author": NodeType.AUTHOR,
    "domain": NodeType.DOMAIN,
    "math_object": NodeType.MATH_OBJECT,
    "open_problem": NodeType.OPEN_PROBLEM,
    "algorithm": NodeType.ALGORITHM,

    # fallback
    "entity": NodeType.ENTITY,
}


def _resolve_entity_name(
    name: str,
    store: Any,
    local_index: dict[str, str],
) -> str | None:
    """Return existing node ID for name, checking local index then store.

    Priority:
    1. local_index (built this ingestion pass)
    2. store.find_nodes(name_contains=name) — cross-session dedup
    Returns None if not found.
    """
    key = name.lower()
    if key in local_index:
        return local_index[key]
    matches = store.find_nodes(name_contains=name)
    exact = [m for m in matches if m.get("name", "").lower() == key]
    if exact:
        return exact[0]["id"]
    return None


def ingest_extraction(store: Any, result: ExtractionResult) -> dict[str, int]:
    """Materialize an ExtractionResult into the graph store.

    - Entities are deduplicated by lowercase name (cross-session via store lookup).
    - When an existing node is reused, its properties are merged (new wins on conflict).
    - Relations are added as edges between resolved entity nodes.
    - Entities referenced in relations but missing from the entities list
      are auto-created as CONCEPT nodes (handles inconsistent LLM output).

    Args:
        store: The graph store to write to.
        result: Extraction result from the pipeline.

    Returns:
        Dict with counts: {"nodes_added": N, "edges_added": N, "edges_skipped": N}
    """
    if not result.entities and not result.relations:
        return {"nodes_added": 0, "edges_added": 0, "edges_skipped": 0}

    # --- Phase 1: Ensure all entities exist as nodes ---
    # name_lower -> node_id mapping for relation resolution
    name_to_id: dict[str, str] = {}
    nodes_added = 0

    # First, index existing nodes so we can deduplicate
    for existing in store.find_nodes():
        name_to_id[existing["name"].lower()] = existing["id"]

    for entity in result.entities:
        key = entity.name.lower()
        existing_id = _resolve_entity_name(entity.name, store, name_to_id)
        if existing_id is not None:
            log.debug("ingest.entity_exists", name=entity.name, node_id=existing_id)
            name_to_id[key] = existing_id
            # Merge properties on existing node
            if entity.properties and hasattr(store, "update_node_properties"):
                store.update_node_properties(existing_id, entity.properties)
            continue

        node_type = _TYPE_MAP.get(entity.entity_type, NodeType.CONCEPT)
        # Strip keys that collide with explicit make_node() params
        extra = {k: v for k, v in entity.properties.items()
                 if k not in ("name", "node_type", "id")}
        node = make_node(
            name=entity.name,
            node_type=node_type,
            **extra,
        )
        store.add_node(node)
        name_to_id[key] = node.id
        nodes_added += 1

    # --- Phase 2: Add relations as edges ---
    edges_added = 0
    edges_skipped = 0

    for rel in result.relations:
        source_id = _resolve_entity_name(rel.source, store, name_to_id)
        target_id = _resolve_entity_name(rel.target, store, name_to_id)

        # Auto-create missing entities referenced in relations.
        if source_id is None:
            log.info("ingest.auto_create_entity", name=rel.source, reason="missing_source")
            node = make_node(name=rel.source, node_type=NodeType.CONCEPT)
            store.add_node(node)
            name_to_id[rel.source.lower()] = node.id
            source_id = node.id
            nodes_added += 1
        if target_id is None:
            log.info("ingest.auto_create_entity", name=rel.target, reason="missing_target")
            node = make_node(name=rel.target, node_type=NodeType.CONCEPT)
            store.add_node(node)
            name_to_id[rel.target.lower()] = node.id
            target_id = node.id
            nodes_added += 1

        # Strip keys that collide with explicit make_edge() params
        extra = {k: v for k, v in rel.properties.items()
                 if k not in ("source_id", "target_id", "relation", "confidence", "id")}
        edge = make_edge(
            source_id=source_id,
            target_id=target_id,
            relation=rel.relation,
            confidence=rel.confidence,
            **extra,
        )
        store.add_edge(edge)
        edges_added += 1

    log.info(
        "ingest.complete",
        nodes_added=nodes_added,
        edges_added=edges_added,
        edges_skipped=edges_skipped,
        total_nodes=store.node_count,
        total_edges=store.edge_count,
    )

    return {
        "nodes_added": nodes_added,
        "edges_added": edges_added,
        "edges_skipped": edges_skipped,
    }
