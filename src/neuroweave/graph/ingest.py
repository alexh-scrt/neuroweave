"""Bridge between the extraction pipeline and the graph store.

Takes ExtractionResult and materializes entities/relations into the graph.
Handles deduplication by name — if an entity with the same name exists, reuse it.
"""

from __future__ import annotations

from neuroweave.extraction.pipeline import ExtractionResult
from neuroweave.graph.store import GraphStore, NodeType, make_edge, make_node
from neuroweave.logging import get_logger

log = get_logger("ingest")

# Map extraction entity_type strings to graph NodeType
_TYPE_MAP: dict[str, NodeType] = {
    "person": NodeType.ENTITY,
    "organization": NodeType.ENTITY,
    "place": NodeType.ENTITY,
    "tool": NodeType.CONCEPT,
    "concept": NodeType.CONCEPT,
    "preference": NodeType.PREFERENCE,
}


def ingest_extraction(store: GraphStore, result: ExtractionResult) -> dict[str, int]:
    """Materialize an ExtractionResult into the graph store.

    - Entities are deduplicated by lowercase name.
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
        if key in name_to_id:
            log.debug("ingest.entity_exists", name=entity.name, node_id=name_to_id[key])
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
        source_id = name_to_id.get(rel.source.lower())
        target_id = name_to_id.get(rel.target.lower())

        # Auto-create missing entities referenced in relations.
        # LLMs sometimes reference entities in relations that they forgot
        # to include in the entities array. Rather than dropping the edge,
        # we create the missing node with a best-guess type (CONCEPT).
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
