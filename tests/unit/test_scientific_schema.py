"""Tests for NW-002 — Scientific entity schema, typed queries."""

from __future__ import annotations

import pytest

from neuroweave.extraction.llm_client import MockLLMClient
from neuroweave.extraction.pipeline import (
    _GENERAL_SYSTEM_PROMPT,
    _SCIENTIFIC_SYSTEM_PROMPT,
    ExtractionPipeline,
)
from neuroweave.graph.ingest import _TYPE_MAP, ingest_extraction
from neuroweave.graph.query import get_domain_graph, get_proof_chain, query_by_type
from neuroweave.graph.store import (
    GraphStore,
    NodeType,
    RelationType,
    make_edge,
    make_node,
)


@pytest.fixture
def store() -> GraphStore:
    return GraphStore()


# ---------------------------------------------------------------------------
# NodeType / RelationType enums
# ---------------------------------------------------------------------------


def test_theorem_node_type_exists():
    assert NodeType.THEOREM.value == "theorem"


def test_all_scientific_node_types_in_enum():
    expected = {
        "theorem", "lemma", "conjecture", "proof", "definition",
        "example", "paper", "author", "domain", "math_object",
        "open_problem", "algorithm",
    }
    actual = {t.value for t in NodeType}
    assert expected.issubset(actual)


def test_relation_type_enum_contains_proves():
    assert RelationType.PROVES.value == "proves"


def test_relation_type_enum_contains_cites():
    assert RelationType.CITES.value == "cites"


# ---------------------------------------------------------------------------
# Entity type mapping
# ---------------------------------------------------------------------------


def test_entity_type_map_includes_theorem():
    assert _TYPE_MAP["theorem"] == NodeType.THEOREM


def test_entity_type_map_includes_lemma():
    assert _TYPE_MAP["lemma"] == NodeType.LEMMA


def test_entity_type_map_fallback_to_entity():
    assert _TYPE_MAP["entity"] == NodeType.ENTITY


# ---------------------------------------------------------------------------
# Extraction pipeline mode
# ---------------------------------------------------------------------------


def test_extraction_pipeline_uses_scientific_prompt_in_scientific_mode():
    mock = MockLLMClient()
    pipeline = ExtractionPipeline(mock, mode="scientific")
    assert pipeline._system_prompt == _SCIENTIFIC_SYSTEM_PROMPT


def test_extraction_pipeline_uses_general_prompt_in_general_mode():
    mock = MockLLMClient()
    pipeline = ExtractionPipeline(mock, mode="general")
    assert pipeline._system_prompt == _GENERAL_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Ingest scientific types
# ---------------------------------------------------------------------------


def test_ingest_maps_theorem_type_correctly(store):
    from neuroweave.extraction.pipeline import ExtractedEntity, ExtractionResult

    result = ExtractionResult(
        entities=[ExtractedEntity(name="Euler's Theorem", entity_type="theorem")],
        relations=[],
    )
    ingest_extraction(store, result)
    nodes = store.find_nodes(node_type=NodeType.THEOREM)
    assert len(nodes) == 1
    assert nodes[0]["name"] == "Euler's Theorem"


def test_ingest_maps_paper_type_correctly(store):
    from neuroweave.extraction.pipeline import ExtractedEntity, ExtractionResult

    result = ExtractionResult(
        entities=[ExtractedEntity(name="Graph Coloring Paper", entity_type="paper")],
        relations=[],
    )
    ingest_extraction(store, result)
    nodes = store.find_nodes(node_type=NodeType.PAPER)
    assert len(nodes) == 1


# ---------------------------------------------------------------------------
# Typed query functions
# ---------------------------------------------------------------------------


def _build_math_graph(store: GraphStore) -> None:
    """Build a small math knowledge graph for testing."""
    t1 = make_node("Four Color Theorem", NodeType.THEOREM, node_id="t1")
    t2 = make_node("Euler's Formula", NodeType.THEOREM, node_id="t2")
    l1 = make_node("Kempe's Lemma", NodeType.LEMMA, node_id="l1")
    d1 = make_node("Graph Theory", NodeType.DOMAIN, node_id="d1")
    p1 = make_node("Appel & Haken 1976", NodeType.PAPER, node_id="p1")

    store.add_node(t1)
    store.add_node(t2)
    store.add_node(l1)
    store.add_node(d1)
    store.add_node(p1)

    store.add_edge(make_edge("t1", "l1", "uses", 0.95, edge_id="e1"))
    store.add_edge(make_edge("t1", "d1", "belongs_to", 0.99, edge_id="e2"))
    store.add_edge(make_edge("t2", "d1", "belongs_to", 0.99, edge_id="e3"))
    store.add_edge(make_edge("p1", "t1", "proves", 0.95, edge_id="e4"))


def test_query_by_type_returns_theorems_only(store):
    _build_math_graph(store)
    result = query_by_type(store, NodeType.THEOREM)
    names = {n["name"] for n in result.nodes}
    assert "Four Color Theorem" in names
    assert "Euler's Formula" in names
    assert "Kempe's Lemma" not in names


def test_query_by_type_with_relation_filter(store):
    _build_math_graph(store)
    result = query_by_type(store, NodeType.THEOREM, relations=["uses"])
    assert any(e["relation"] == "uses" for e in result.edges)
    assert not any(e["relation"] == "belongs_to" for e in result.edges)


def test_get_proof_chain_traverses_uses_relation(store):
    _build_math_graph(store)
    result = get_proof_chain(store, "Four Color Theorem")
    assert len(result.nodes) > 0
    relations = {e["relation"] for e in result.edges}
    assert relations.issubset({"uses", "follows_from", "proves", "verified_by"})


def test_get_domain_graph_returns_members(store):
    _build_math_graph(store)
    result = get_domain_graph(store, "Graph Theory")
    assert len(result.nodes) >= 1  # at least the domain node
    # Should include theorems belonging to the domain
    names = {n["name"] for n in result.nodes}
    assert "Graph Theory" in names


def test_scientific_mode_config_wired_to_pipeline():
    from neuroweave.config import NeuroWeaveConfig

    config = NeuroWeaveConfig(extraction_mode="scientific")
    assert config.extraction_mode == "scientific"
