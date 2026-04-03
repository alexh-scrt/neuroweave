"""Tests for NW-005 — Node merge / deduplication."""

from __future__ import annotations

import asyncio

import pytest

from neuroweave.extraction.pipeline import ExtractedEntity, ExtractionResult
from neuroweave.graph.backends.memory import MemoryGraphStore
from neuroweave.graph.ingest import _resolve_entity_name, ingest_extraction
from neuroweave.graph.store import (
    GraphEvent,
    GraphEventType,
    GraphStore,
    NodeType,
    make_node,
)


@pytest.fixture
def store() -> GraphStore:
    return GraphStore()


@pytest.fixture
def memory_store() -> MemoryGraphStore:
    return MemoryGraphStore()


# ---------------------------------------------------------------------------
# Dedup tests
# ---------------------------------------------------------------------------


def test_dedup_reuses_node_by_exact_name_case_insensitive(store):
    """Ingesting the same entity name twice (different case) should not create duplicates."""
    result1 = ExtractionResult(
        entities=[ExtractedEntity(name="Python", entity_type="tool")],
        relations=[],
    )
    result2 = ExtractionResult(
        entities=[ExtractedEntity(name="python", entity_type="tool")],
        relations=[],
    )
    ingest_extraction(store, result1)
    ingest_extraction(store, result2)
    assert store.node_count == 1


def test_dedup_reuses_node_from_store_across_sessions(store):
    """Cross-session dedup: entity added in session 1 reused in session 2."""
    # Session 1
    node = make_node("Euler's Theorem", NodeType.THEOREM, node_id="thm_euler")
    store.add_node(node)

    # Session 2 — extraction mentions same entity
    result = ExtractionResult(
        entities=[ExtractedEntity(name="Euler's Theorem", entity_type="theorem")],
        relations=[],
    )
    stats = ingest_extraction(store, result)
    assert stats["nodes_added"] == 0
    assert store.node_count == 1  # still just one


def test_dedup_does_not_create_duplicate_when_name_exists(store):
    result1 = ExtractionResult(
        entities=[ExtractedEntity(name="Graph Theory", entity_type="domain")],
        relations=[],
    )
    result2 = ExtractionResult(
        entities=[ExtractedEntity(name="Graph Theory", entity_type="domain")],
        relations=[],
    )
    ingest_extraction(store, result1)
    ingest_extraction(store, result2)
    nodes = store.find_nodes(name_contains="Graph Theory")
    assert len(nodes) == 1


def test_dedup_merges_properties_on_existing_node(memory_store):
    """When a node is reused, incoming properties should be merged."""
    node = make_node("Theorem X", NodeType.THEOREM, node_id="t1", status="unproven")
    memory_store.add_node(node)

    result = ExtractionResult(
        entities=[ExtractedEntity(
            name="Theorem X",
            entity_type="theorem",
            properties={"status": "proven", "year": 2025},
        )],
        relations=[],
    )
    ingest_extraction(memory_store, result)

    node_data = memory_store.get_node("t1")
    assert node_data is not None
    props = node_data.get("properties", {})
    assert props.get("year") == 2025
    assert props.get("status") == "proven"  # new value wins


def test_dedup_emits_node_updated_on_reuse(memory_store):
    """Reusing an existing node should emit NODE_UPDATED (via update_node_properties)."""
    events: list[GraphEvent] = []
    q = asyncio.Queue()
    memory_store.set_event_queue(q)

    node = make_node("Lemma Y", NodeType.LEMMA, node_id="l1")
    memory_store.add_node(node)

    result = ExtractionResult(
        entities=[ExtractedEntity(
            name="Lemma Y",
            entity_type="lemma",
            properties={"author": "Gauss"},
        )],
        relations=[],
    )
    ingest_extraction(memory_store, result)

    # Drain events
    while not q.empty():
        events.append(q.get_nowait())

    update_events = [e for e in events if e.event_type == GraphEventType.NODE_UPDATED]
    assert len(update_events) >= 1


def test_dedup_emits_node_added_on_new_node(store):
    """Creating a new node should emit NODE_ADDED."""
    events: list[GraphEvent] = []
    q = asyncio.Queue()
    store.set_event_queue(q)

    result = ExtractionResult(
        entities=[ExtractedEntity(name="NewEntity", entity_type="concept")],
        relations=[],
    )
    ingest_extraction(store, result)

    while not q.empty():
        events.append(q.get_nowait())

    added_events = [e for e in events if e.event_type == GraphEventType.NODE_ADDED]
    assert len(added_events) >= 1


def test_dedup_local_index_takes_priority_over_store(store):
    """The local name_to_id index (this ingestion pass) should be checked first."""
    # Pre-populate store with a node
    store.add_node(make_node("Alpha", NodeType.ENTITY, node_id="store_alpha"))

    local_index = {"alpha": "local_alpha"}
    result = _resolve_entity_name("Alpha", store, local_index)
    assert result == "local_alpha"  # local wins


# ---------------------------------------------------------------------------
# update_node_properties
# ---------------------------------------------------------------------------


def test_update_node_properties_merges_correctly(memory_store):
    node = make_node("TestNode", NodeType.ENTITY, node_id="t1", key1="val1")
    memory_store.add_node(node)
    memory_store.update_node_properties("t1", {"key2": "val2"})

    data = memory_store.get_node("t1")
    assert data is not None
    props = data.get("properties", {})
    assert props.get("key1") == "val1"
    assert props.get("key2") == "val2"


def test_update_node_properties_new_key_wins(memory_store):
    node = make_node("TestNode", NodeType.ENTITY, node_id="t1", status="old")
    memory_store.add_node(node)
    memory_store.update_node_properties("t1", {"status": "new"})

    data = memory_store.get_node("t1")
    assert data is not None
    props = data.get("properties", {})
    assert props.get("status") == "new"


def test_update_node_properties_noop_for_unknown_id(memory_store):
    """Updating a nonexistent node should be a no-op."""
    memory_store.update_node_properties("nonexistent", {"key": "val"})
    assert memory_store.node_count == 0
