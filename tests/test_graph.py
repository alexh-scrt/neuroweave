"""Tests for the in-memory knowledge graph store."""

from __future__ import annotations

import asyncio

import pytest

from neuroweave.graph.store import (
    Edge,
    GraphEvent,
    GraphEventType,
    GraphStore,
    Node,
    NodeType,
    make_edge,
    make_node,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store() -> GraphStore:
    return GraphStore()


@pytest.fixture
def populated_store(store: GraphStore) -> GraphStore:
    """A store with a small pre-built graph: Alex -married_to-> Lena, Alex -prefers-> Python."""
    alex = make_node("Alex", NodeType.ENTITY, node_id="alex")
    lena = make_node("Lena", NodeType.ENTITY, node_id="lena")
    python = make_node("Python", NodeType.CONCEPT, node_id="python")

    store.add_node(alex)
    store.add_node(lena)
    store.add_node(python)

    store.add_edge(make_edge("alex", "lena", "married_to", 0.95, edge_id="e1"))
    store.add_edge(make_edge("alex", "python", "prefers", 0.90, edge_id="e2"))

    return store


# ---------------------------------------------------------------------------
# Node operations
# ---------------------------------------------------------------------------

class TestAddNode:
    def test_add_single_node(self, store: GraphStore):
        node = make_node("Alex", NodeType.ENTITY, node_id="alex")
        result = store.add_node(node)
        assert result.id == "alex"
        assert store.node_count == 1

    def test_add_multiple_nodes(self, store: GraphStore):
        store.add_node(make_node("Alex", NodeType.ENTITY, node_id="a"))
        store.add_node(make_node("Lena", NodeType.ENTITY, node_id="b"))
        store.add_node(make_node("Python", NodeType.CONCEPT, node_id="c"))
        assert store.node_count == 3

    def test_update_existing_node(self, store: GraphStore):
        store.add_node(make_node("Alex", NodeType.ENTITY, node_id="alex", role="engineer"))
        store.add_node(make_node("Alex", NodeType.ENTITY, node_id="alex", role="CTO"))
        assert store.node_count == 1
        data = store.get_node("alex")
        assert data["properties"]["role"] == "CTO"

    def test_node_preserves_properties(self, store: GraphStore):
        store.add_node(make_node("Tokyo", NodeType.ENTITY, node_id="tokyo", country="Japan"))
        data = store.get_node("tokyo")
        assert data["name"] == "Tokyo"
        assert data["node_type"] == "entity"
        assert data["properties"]["country"] == "Japan"


class TestGetNode:
    def test_get_existing_node(self, populated_store: GraphStore):
        node = populated_store.get_node("alex")
        assert node is not None
        assert node["name"] == "Alex"

    def test_get_nonexistent_node(self, store: GraphStore):
        assert store.get_node("does_not_exist") is None


class TestFindNodes:
    def test_find_by_type(self, populated_store: GraphStore):
        entities = populated_store.find_nodes(node_type=NodeType.ENTITY)
        assert len(entities) == 2
        names = {n["name"] for n in entities}
        assert names == {"Alex", "Lena"}

    def test_find_by_name(self, populated_store: GraphStore):
        results = populated_store.find_nodes(name_contains="lex")
        assert len(results) == 1
        assert results[0]["name"] == "Alex"

    def test_find_by_type_and_name(self, populated_store: GraphStore):
        results = populated_store.find_nodes(node_type=NodeType.CONCEPT, name_contains="python")
        assert len(results) == 1

    def test_find_case_insensitive(self, populated_store: GraphStore):
        results = populated_store.find_nodes(name_contains="PYTHON")
        assert len(results) == 1

    def test_find_no_matches(self, populated_store: GraphStore):
        results = populated_store.find_nodes(name_contains="Rust")
        assert results == []


# ---------------------------------------------------------------------------
# Edge operations
# ---------------------------------------------------------------------------

class TestAddEdge:
    def test_add_edge(self, populated_store: GraphStore):
        assert populated_store.edge_count == 2

    def test_edge_requires_source_node(self, store: GraphStore):
        store.add_node(make_node("Lena", NodeType.ENTITY, node_id="lena"))
        with pytest.raises(KeyError, match="Source node"):
            store.add_edge(make_edge("ghost", "lena", "knows", 0.5))

    def test_edge_requires_target_node(self, store: GraphStore):
        store.add_node(make_node("Alex", NodeType.ENTITY, node_id="alex"))
        with pytest.raises(KeyError, match="Target node"):
            store.add_edge(make_edge("alex", "ghost", "knows", 0.5))

    def test_multiple_edges_between_same_nodes(self, populated_store: GraphStore):
        """MultiDiGraph supports parallel edges (e.g. married_to AND works_with)."""
        populated_store.add_edge(make_edge("alex", "lena", "works_with", 0.7, edge_id="e3"))
        edges = populated_store.get_edges(source_id="alex", target_id="lena")
        assert len(edges) == 2
        relations = {e["relation"] for e in edges}
        assert relations == {"married_to", "works_with"}


class TestGetEdges:
    def test_get_by_source(self, populated_store: GraphStore):
        edges = populated_store.get_edges(source_id="alex")
        assert len(edges) == 2

    def test_get_by_target(self, populated_store: GraphStore):
        edges = populated_store.get_edges(target_id="lena")
        assert len(edges) == 1
        assert edges[0]["relation"] == "married_to"

    def test_get_by_relation(self, populated_store: GraphStore):
        edges = populated_store.get_edges(relation="prefers")
        assert len(edges) == 1
        assert edges[0]["target_id"] == "python"

    def test_get_combined_filter(self, populated_store: GraphStore):
        edges = populated_store.get_edges(source_id="alex", relation="married_to")
        assert len(edges) == 1

    def test_get_no_matches(self, populated_store: GraphStore):
        edges = populated_store.get_edges(relation="hates")
        assert edges == []


class TestGetNeighbors:
    def test_direct_neighbors(self, populated_store: GraphStore):
        neighbors = populated_store.get_neighbors("alex", depth=1)
        assert len(neighbors) == 2
        names = {n["name"] for n in neighbors}
        assert names == {"Lena", "Python"}

    def test_depth_two(self, populated_store: GraphStore):
        # Add: Lena -> Tokyo
        populated_store.add_node(make_node("Tokyo", NodeType.ENTITY, node_id="tokyo"))
        populated_store.add_edge(make_edge("lena", "tokyo", "traveling_to", 0.8, edge_id="e3"))

        # From Alex at depth 1: Lena, Python. At depth 2: also Tokyo.
        depth1 = populated_store.get_neighbors("alex", depth=1)
        depth2 = populated_store.get_neighbors("alex", depth=2)
        assert len(depth1) == 2
        assert len(depth2) == 3

    def test_nonexistent_node(self, store: GraphStore):
        assert store.get_neighbors("ghost") == []


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_to_dict_structure(self, populated_store: GraphStore):
        data = populated_store.to_dict()
        assert "nodes" in data
        assert "edges" in data
        assert "stats" in data
        assert data["stats"]["node_count"] == 3
        assert data["stats"]["edge_count"] == 2

    def test_to_dict_nodes_have_required_fields(self, populated_store: GraphStore):
        data = populated_store.to_dict()
        for node in data["nodes"]:
            assert "id" in node
            assert "name" in node
            assert "node_type" in node

    def test_to_dict_edges_have_required_fields(self, populated_store: GraphStore):
        data = populated_store.to_dict()
        for edge in data["edges"]:
            assert "id" in edge
            assert "source_id" in edge
            assert "target_id" in edge
            assert "relation" in edge
            assert "confidence" in edge

    def test_empty_graph(self, store: GraphStore):
        data = store.to_dict()
        assert data["nodes"] == []
        assert data["edges"] == []
        assert data["stats"]["node_count"] == 0


# ---------------------------------------------------------------------------
# Event emission
# ---------------------------------------------------------------------------

class TestEventEmission:
    def test_no_queue_no_error(self, store: GraphStore):
        """Adding nodes/edges without a queue attached doesn't raise."""
        store.add_node(make_node("Alex", NodeType.ENTITY, node_id="a"))

    def test_node_added_event(self, store: GraphStore):
        queue: asyncio.Queue[GraphEvent] = asyncio.Queue()
        store.set_event_queue(queue)

        store.add_node(make_node("Alex", NodeType.ENTITY, node_id="alex"))

        assert not queue.empty()
        event = queue.get_nowait()
        assert event.event_type == GraphEventType.NODE_ADDED
        assert event.data["name"] == "Alex"

    def test_node_updated_event(self, store: GraphStore):
        queue: asyncio.Queue[GraphEvent] = asyncio.Queue()
        store.set_event_queue(queue)

        store.add_node(make_node("Alex", NodeType.ENTITY, node_id="alex"))
        store.add_node(make_node("Alex Updated", NodeType.ENTITY, node_id="alex"))

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        assert events[0].event_type == GraphEventType.NODE_ADDED
        assert events[1].event_type == GraphEventType.NODE_UPDATED

    def test_edge_added_event(self, store: GraphStore):
        queue: asyncio.Queue[GraphEvent] = asyncio.Queue()
        store.set_event_queue(queue)

        store.add_node(make_node("Alex", NodeType.ENTITY, node_id="alex"))
        store.add_node(make_node("Lena", NodeType.ENTITY, node_id="lena"))
        store.add_edge(make_edge("alex", "lena", "married_to", 0.95, edge_id="e1"))

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        edge_events = [e for e in events if e.event_type == GraphEventType.EDGE_ADDED]
        assert len(edge_events) == 1
        assert edge_events[0].data["relation"] == "married_to"


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

class TestFactoryHelpers:
    def test_make_node_auto_id(self):
        node = make_node("Alex", NodeType.ENTITY)
        assert node.id.startswith("n_")
        assert len(node.id) == 14  # "n_" + 12 hex chars

    def test_make_node_custom_id(self):
        node = make_node("Alex", NodeType.ENTITY, node_id="custom_id")
        assert node.id == "custom_id"

    def test_make_edge_auto_id(self):
        edge = make_edge("a", "b", "knows", 0.8)
        assert edge.id.startswith("e_")

    def test_make_edge_with_properties(self):
        edge = make_edge("a", "b", "knows", 0.8, context="work")
        assert edge.properties["context"] == "work"
