"""Tests for the structured graph query engine."""

from __future__ import annotations

import pytest

from neuroweave.graph.query import QueryResult, query_subgraph
from neuroweave.graph.store import GraphStore, NodeType, make_edge, make_node


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store() -> GraphStore:
    return GraphStore()


@pytest.fixture
def family_graph(store: GraphStore) -> GraphStore:
    """A richer graph modelling the 5-message conversation corpus.

    Nodes: User, Alex, Lena, Tokyo, Python, sushi, ramen, children, software engineering
    Edges: named, occupation, married_to, 2x traveling_to, 2x prefers,
           has_children, experienced_with
    """
    nodes = [
        make_node("User", NodeType.ENTITY, node_id="user"),
        make_node("Alex", NodeType.ENTITY, node_id="alex"),
        make_node("Lena", NodeType.ENTITY, node_id="lena"),
        make_node("Tokyo", NodeType.ENTITY, node_id="tokyo"),
        make_node("Python", NodeType.CONCEPT, node_id="python"),
        make_node("sushi", NodeType.CONCEPT, node_id="sushi"),
        make_node("ramen", NodeType.CONCEPT, node_id="ramen"),
        make_node("children", NodeType.ENTITY, node_id="children"),
        make_node("software engineering", NodeType.CONCEPT, node_id="sw_eng"),
    ]
    for n in nodes:
        store.add_node(n)

    edges = [
        make_edge("user", "alex", "named", 0.95, edge_id="e1"),
        make_edge("user", "sw_eng", "occupation", 0.90, edge_id="e2"),
        make_edge("user", "lena", "married_to", 0.90, edge_id="e3"),
        make_edge("user", "tokyo", "traveling_to", 0.85, edge_id="e4"),
        make_edge("lena", "tokyo", "traveling_to", 0.85, edge_id="e5"),
        make_edge("lena", "sushi", "prefers", 0.90, edge_id="e6"),
        make_edge("user", "ramen", "prefers", 0.85, edge_id="e7"),
        make_edge("user", "children", "has_children", 0.90, edge_id="e8"),
        make_edge("user", "python", "experienced_with", 0.90, edge_id="e9"),
    ]
    for e in edges:
        store.add_edge(e)

    return store


# ---------------------------------------------------------------------------
# QueryResult dataclass
# ---------------------------------------------------------------------------

class TestQueryResult:
    def test_empty_result(self):
        r = QueryResult()
        assert r.is_empty
        assert r.node_count == 0
        assert r.edge_count == 0
        assert r.node_names() == set()
        assert r.relation_types() == set()

    def test_non_empty_result(self):
        r = QueryResult(
            nodes=[{"id": "a", "name": "Alex", "node_type": "entity"}],
            edges=[{"id": "e1", "source_id": "a", "target_id": "b", "relation": "knows", "confidence": 0.9}],
        )
        assert not r.is_empty
        assert r.node_count == 1
        assert r.edge_count == 1
        assert r.node_names() == {"Alex"}
        assert r.relation_types() == {"knows"}

    def test_to_dict(self):
        r = QueryResult(
            nodes=[{"id": "a", "name": "Alex", "node_type": "entity"}],
            edges=[],
            seed_node_ids=["a"],
            hops_traversed=1,
        )
        d = r.to_dict()
        assert d["stats"]["node_count"] == 1
        assert d["stats"]["edge_count"] == 0
        assert d["seed_node_ids"] == ["a"]
        assert d["hops_traversed"] == 1


# ---------------------------------------------------------------------------
# Entity name resolution
# ---------------------------------------------------------------------------

class TestEntityResolution:
    def test_finds_by_exact_name(self, family_graph: GraphStore):
        result = query_subgraph(family_graph, entities=["Lena"], max_hops=0)
        assert "Lena" in result.node_names()
        assert len(result.seed_node_ids) == 1

    def test_case_insensitive(self, family_graph: GraphStore):
        result = query_subgraph(family_graph, entities=["lena"], max_hops=0)
        assert "Lena" in result.node_names()

    def test_case_insensitive_upper(self, family_graph: GraphStore):
        result = query_subgraph(family_graph, entities=["PYTHON"], max_hops=0)
        assert "Python" in result.node_names()

    def test_multiple_entities(self, family_graph: GraphStore):
        result = query_subgraph(family_graph, entities=["Lena", "Python"], max_hops=0)
        assert result.node_names() == {"Lena", "Python"}
        assert len(result.seed_node_ids) == 2

    def test_unknown_entity_returns_empty(self, family_graph: GraphStore):
        result = query_subgraph(family_graph, entities=["Nonexistent"])
        assert result.is_empty

    def test_mix_known_unknown(self, family_graph: GraphStore):
        result = query_subgraph(family_graph, entities=["Lena", "Nonexistent"], max_hops=0)
        assert result.node_names() == {"Lena"}

    def test_empty_entity_list(self, family_graph: GraphStore):
        """Empty list is treated as no entity filter — returns entire graph."""
        result = query_subgraph(family_graph, entities=[], max_hops=0)
        # Empty list → all nodes
        assert result.node_count == 9


# ---------------------------------------------------------------------------
# Hop traversal
# ---------------------------------------------------------------------------

class TestHopTraversal:
    def test_zero_hops_returns_seed_only(self, family_graph: GraphStore):
        result = query_subgraph(family_graph, entities=["Lena"], max_hops=0)
        assert result.node_names() == {"Lena"}
        assert result.edge_count == 0  # No edges: no neighbors collected

    def test_one_hop_from_lena(self, family_graph: GraphStore):
        result = query_subgraph(family_graph, entities=["Lena"], max_hops=1)
        names = result.node_names()
        # Lena connects to: User (married_to), Tokyo (traveling_to), sushi (prefers)
        assert "Lena" in names
        assert "User" in names
        assert "Tokyo" in names
        assert "sushi" in names
        # Should NOT include Python, ramen, etc. (2 hops from Lena)
        assert "Python" not in names
        assert "ramen" not in names

    def test_two_hops_from_lena(self, family_graph: GraphStore):
        result = query_subgraph(family_graph, entities=["Lena"], max_hops=2)
        names = result.node_names()
        # 2 hops from Lena reaches everything connected to User
        assert "Python" in names
        assert "ramen" in names
        assert "Alex" in names

    def test_one_hop_includes_connecting_edges(self, family_graph: GraphStore):
        result = query_subgraph(family_graph, entities=["Lena"], max_hops=1)
        rels = result.relation_types()
        assert "married_to" in rels
        assert "traveling_to" in rels
        assert "prefers" in rels

    def test_hops_from_leaf_node(self, family_graph: GraphStore):
        """sushi is a leaf node — 1 hop reaches only Lena."""
        result = query_subgraph(family_graph, entities=["sushi"], max_hops=1)
        names = result.node_names()
        assert names == {"sushi", "Lena"}


# ---------------------------------------------------------------------------
# Relation type filter
# ---------------------------------------------------------------------------

class TestRelationFilter:
    def test_filter_single_relation(self, family_graph: GraphStore):
        result = query_subgraph(family_graph, entities=["User"], relations=["prefers"], max_hops=1)
        assert all(e["relation"] == "prefers" for e in result.edges)
        assert result.edge_count >= 1

    def test_filter_multiple_relations(self, family_graph: GraphStore):
        result = query_subgraph(
            family_graph, entities=["User"], relations=["prefers", "married_to"], max_hops=1
        )
        rels = result.relation_types()
        assert rels <= {"prefers", "married_to"}

    def test_filter_excludes_non_matching(self, family_graph: GraphStore):
        result = query_subgraph(
            family_graph, entities=["User"], relations=["prefers"], max_hops=1
        )
        assert "married_to" not in result.relation_types()
        assert "traveling_to" not in result.relation_types()

    def test_no_matching_relations_returns_nodes_no_edges(self, family_graph: GraphStore):
        result = query_subgraph(
            family_graph, entities=["User"], relations=["nonexistent"], max_hops=1
        )
        # Nodes are still returned (hop traversal doesn't depend on relation filter)
        assert result.node_count > 0
        assert result.edge_count == 0

    def test_none_relations_returns_all(self, family_graph: GraphStore):
        result = query_subgraph(family_graph, entities=["User"], max_hops=1)
        assert result.edge_count >= 7  # User has many edges


# ---------------------------------------------------------------------------
# Confidence filter
# ---------------------------------------------------------------------------

class TestConfidenceFilter:
    def test_min_confidence_filters_edges(self, family_graph: GraphStore):
        result = query_subgraph(
            family_graph, entities=["User"], min_confidence=0.90, max_hops=1
        )
        for edge in result.edges:
            assert edge["confidence"] >= 0.90

    def test_high_threshold_filters_most(self, family_graph: GraphStore):
        all_edges = query_subgraph(family_graph, entities=["User"], max_hops=1)
        filtered = query_subgraph(
            family_graph, entities=["User"], min_confidence=0.90, max_hops=1
        )
        assert filtered.edge_count <= all_edges.edge_count

    def test_zero_threshold_returns_all(self, family_graph: GraphStore):
        result = query_subgraph(
            family_graph, entities=["User"], min_confidence=0.0, max_hops=1
        )
        assert result.edge_count >= 7

    def test_threshold_one_returns_none_or_few(self, family_graph: GraphStore):
        result = query_subgraph(
            family_graph, entities=["User"], min_confidence=1.0, max_hops=1
        )
        # No edges in our corpus have confidence == 1.0
        assert result.edge_count == 0


# ---------------------------------------------------------------------------
# Whole-graph query (no entity filter)
# ---------------------------------------------------------------------------

class TestWholeGraphQuery:
    def test_no_entities_returns_full_graph(self, family_graph: GraphStore):
        result = query_subgraph(family_graph)
        assert result.node_count == 9
        assert result.edge_count == 9

    def test_no_entities_with_relation_filter(self, family_graph: GraphStore):
        result = query_subgraph(family_graph, relations=["prefers"])
        assert all(e["relation"] == "prefers" for e in result.edges)
        assert result.edge_count == 2  # Lena→sushi, User→ramen

    def test_no_entities_with_confidence_filter(self, family_graph: GraphStore):
        result = query_subgraph(family_graph, min_confidence=0.90)
        for edge in result.edges:
            assert edge["confidence"] >= 0.90

    def test_empty_graph(self, store: GraphStore):
        result = query_subgraph(store)
        assert result.is_empty


# ---------------------------------------------------------------------------
# Combined filters
# ---------------------------------------------------------------------------

class TestCombinedFilters:
    def test_entity_plus_relation_plus_confidence(self, family_graph: GraphStore):
        result = query_subgraph(
            family_graph,
            entities=["User"],
            relations=["prefers", "experienced_with"],
            min_confidence=0.85,
            max_hops=1,
        )
        for edge in result.edges:
            assert edge["relation"] in ("prefers", "experienced_with")
            assert edge["confidence"] >= 0.85

    def test_lena_preferences(self, family_graph: GraphStore):
        """The canonical query: 'what does my wife like?'"""
        result = query_subgraph(
            family_graph, entities=["Lena"], relations=["prefers"], max_hops=1
        )
        assert "sushi" in result.node_names()
        assert result.edge_count == 1
        assert result.edges[0]["relation"] == "prefers"


# ---------------------------------------------------------------------------
# Query params transparency
# ---------------------------------------------------------------------------

class TestQueryParams:
    def test_query_params_recorded(self, family_graph: GraphStore):
        result = query_subgraph(
            family_graph, entities=["Lena"], relations=["prefers"], min_confidence=0.5, max_hops=2
        )
        assert result.query_params["entities"] == ["Lena"]
        assert result.query_params["relations"] == ["prefers"]
        assert result.query_params["min_confidence"] == 0.5
        assert result.query_params["max_hops"] == 2

    def test_hops_traversed_recorded(self, family_graph: GraphStore):
        result = query_subgraph(family_graph, entities=["Lena"], max_hops=3)
        assert result.hops_traversed == 3

    def test_seed_ids_recorded(self, family_graph: GraphStore):
        result = query_subgraph(family_graph, entities=["Lena"], max_hops=0)
        assert result.seed_node_ids == ["lena"]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_self_referencing_would_not_duplicate(self, store: GraphStore):
        """If a node has a self-edge, it shouldn't cause issues."""
        store.add_node(make_node("Loop", NodeType.CONCEPT, node_id="loop"))
        store.add_edge(make_edge("loop", "loop", "references", 0.5, edge_id="e_self"))

        result = query_subgraph(store, entities=["Loop"], max_hops=1)
        assert result.node_count == 1
        assert result.edge_count == 1

    def test_disconnected_components(self, store: GraphStore):
        """Querying one component doesn't return nodes from another."""
        store.add_node(make_node("A", NodeType.ENTITY, node_id="a"))
        store.add_node(make_node("B", NodeType.ENTITY, node_id="b"))
        store.add_edge(make_edge("a", "b", "knows", 0.9, edge_id="e1"))

        store.add_node(make_node("X", NodeType.ENTITY, node_id="x"))
        store.add_node(make_node("Y", NodeType.ENTITY, node_id="y"))
        store.add_edge(make_edge("x", "y", "knows", 0.9, edge_id="e2"))

        result = query_subgraph(store, entities=["A"], max_hops=5)
        names = result.node_names()
        assert "A" in names
        assert "B" in names
        assert "X" not in names
        assert "Y" not in names

    def test_large_hops_doesnt_error(self, family_graph: GraphStore):
        """max_hops larger than graph diameter still works."""
        result = query_subgraph(family_graph, entities=["sushi"], max_hops=100)
        # Should reach everything since graph is connected
        assert result.node_count == 9

    def test_duplicate_entity_names(self, family_graph: GraphStore):
        """Passing the same entity name twice doesn't duplicate results."""
        result = query_subgraph(family_graph, entities=["Lena", "Lena"], max_hops=0)
        assert result.node_count == 1
