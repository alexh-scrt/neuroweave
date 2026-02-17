"""Tests for the extraction → graph ingestion bridge."""

from __future__ import annotations

import pytest

from neuroweave.extraction.pipeline import ExtractedEntity, ExtractedRelation, ExtractionResult
from neuroweave.graph.ingest import ingest_extraction
from neuroweave.graph.store import GraphStore, NodeType, make_node


@pytest.fixture
def store() -> GraphStore:
    return GraphStore()


def _result(
    entities: list[tuple[str, str]] | None = None,
    relations: list[tuple[str, str, str, float]] | None = None,
) -> ExtractionResult:
    """Helper to build ExtractionResult from short tuples."""
    ents = [
        ExtractedEntity(name=name, entity_type=etype)
        for name, etype in (entities or [])
    ]
    rels = [
        ExtractedRelation(source=src, target=tgt, relation=rel, confidence=conf)
        for src, tgt, rel, conf in (relations or [])
    ]
    return ExtractionResult(entities=ents, relations=rels)


class TestIngestEntities:
    def test_adds_new_entities(self, store: GraphStore):
        result = _result(entities=[("Alex", "person"), ("Python", "tool")])
        stats = ingest_extraction(store, result)
        assert stats["nodes_added"] == 2
        assert store.node_count == 2

    def test_deduplicates_by_name(self, store: GraphStore):
        result1 = _result(entities=[("Alex", "person")])
        result2 = _result(entities=[("Alex", "person"), ("Lena", "person")])

        ingest_extraction(store, result1)
        stats = ingest_extraction(store, result2)

        assert stats["nodes_added"] == 1  # Only Lena is new
        assert store.node_count == 2

    def test_deduplication_case_insensitive(self, store: GraphStore):
        result1 = _result(entities=[("Python", "tool")])
        result2 = _result(entities=[("python", "tool")])

        ingest_extraction(store, result1)
        stats = ingest_extraction(store, result2)

        assert stats["nodes_added"] == 0
        assert store.node_count == 1

    def test_maps_entity_types(self, store: GraphStore):
        result = _result(entities=[
            ("Alex", "person"),
            ("Python", "tool"),
            ("Tokyo", "place"),
            ("ML", "concept"),
        ])
        ingest_extraction(store, result)

        alex = store.find_nodes(name_contains="Alex")[0]
        python = store.find_nodes(name_contains="Python")[0]
        tokyo = store.find_nodes(name_contains="Tokyo")[0]

        assert alex["node_type"] == NodeType.ENTITY.value
        assert python["node_type"] == NodeType.CONCEPT.value
        assert tokyo["node_type"] == NodeType.ENTITY.value

    def test_empty_result(self, store: GraphStore):
        stats = ingest_extraction(store, _result())
        assert stats == {"nodes_added": 0, "edges_added": 0, "edges_skipped": 0}


class TestIngestRelations:
    def test_adds_edges(self, store: GraphStore):
        result = _result(
            entities=[("User", "person"), ("Python", "tool")],
            relations=[("User", "Python", "prefers", 0.9)],
        )
        stats = ingest_extraction(store, result)
        assert stats["edges_added"] == 1
        assert store.edge_count == 1

    def test_skips_unknown_source(self, store: GraphStore):
        result = _result(
            entities=[("Python", "tool")],
            relations=[("Ghost", "Python", "prefers", 0.9)],
        )
        stats = ingest_extraction(store, result)
        assert stats["edges_skipped"] == 1
        assert stats["edges_added"] == 0

    def test_skips_unknown_target(self, store: GraphStore):
        result = _result(
            entities=[("User", "person")],
            relations=[("User", "Ghost", "prefers", 0.9)],
        )
        stats = ingest_extraction(store, result)
        assert stats["edges_skipped"] == 1

    def test_resolves_entities_case_insensitive(self, store: GraphStore):
        result = _result(
            entities=[("User", "person"), ("Python", "tool")],
            relations=[("user", "python", "prefers", 0.9)],
        )
        stats = ingest_extraction(store, result)
        assert stats["edges_added"] == 1

    def test_multiple_relations(self, store: GraphStore):
        result = _result(
            entities=[("User", "person"), ("Lena", "person"), ("Tokyo", "place")],
            relations=[
                ("User", "Lena", "married_to", 0.95),
                ("User", "Tokyo", "traveling_to", 0.85),
                ("Lena", "Tokyo", "traveling_to", 0.85),
            ],
        )
        stats = ingest_extraction(store, result)
        assert stats["edges_added"] == 3
        assert store.edge_count == 3


class TestIngestAcrossMessages:
    """Simulates multiple messages building up the graph incrementally."""

    def test_graph_grows_across_messages(self, store: GraphStore):
        # Message 1
        r1 = _result(
            entities=[("User", "person"), ("Alex", "person")],
            relations=[("User", "Alex", "named", 0.95)],
        )
        ingest_extraction(store, r1)
        assert store.node_count == 2
        assert store.edge_count == 1

        # Message 2 — reuses User, adds new entities
        r2 = _result(
            entities=[("User", "person"), ("Lena", "person"), ("Tokyo", "place")],
            relations=[
                ("User", "Lena", "married_to", 0.90),
                ("User", "Tokyo", "traveling_to", 0.85),
            ],
        )
        stats2 = ingest_extraction(store, r2)
        assert stats2["nodes_added"] == 2  # Lena and Tokyo are new
        assert store.node_count == 4
        assert store.edge_count == 3

        # Message 3 — all entities already exist
        r3 = _result(
            entities=[("Lena", "person"), ("User", "person")],
            relations=[("Lena", "Tokyo", "traveling_to", 0.85)],
        )
        stats3 = ingest_extraction(store, r3)
        assert stats3["nodes_added"] == 0
        assert stats3["edges_added"] == 1
        assert store.edge_count == 4
