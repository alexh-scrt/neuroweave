"""End-to-end test — the POC proof.

Feeds a 5-message simulated conversation through the full pipeline
(extraction → ingest → graph) and asserts the knowledge graph is
correctly built.

This is the single most important test in the project. If this passes,
the POC works.
"""

from __future__ import annotations

import pytest

from neuroweave.extraction.llm_client import MockLLMClient
from neuroweave.extraction.pipeline import ExtractionPipeline
from neuroweave.graph.ingest import ingest_extraction
from neuroweave.graph.store import GraphStore, NodeType
from neuroweave.main import process_message


# ---------------------------------------------------------------------------
# The 5-message conversation
# ---------------------------------------------------------------------------

CONVERSATION = [
    "My name is Alex and I'm a software engineer",
    "My wife Lena and I are going to Tokyo in March",
    "She loves sushi but I prefer ramen",
    "We have two kids, both in elementary school",
    "I've been using Python for 10 years",
]


# ---------------------------------------------------------------------------
# Fixtures — reuse the shared corpus from conftest.py
# ---------------------------------------------------------------------------

@pytest.fixture
def e2e_store() -> GraphStore:
    return GraphStore()


@pytest.fixture
async def e2e_result(
    mock_llm_with_corpus: MockLLMClient,
    e2e_store: GraphStore,
) -> GraphStore:
    """Run all 5 messages through the full pipeline, return the populated store."""
    pipeline = ExtractionPipeline(mock_llm_with_corpus)
    for message in CONVERSATION:
        await process_message(message, pipeline, e2e_store)
    return e2e_store


# ---------------------------------------------------------------------------
# The proof: conversation → correctly structured graph
# ---------------------------------------------------------------------------

class TestConversationBuildsGraph:
    """After 5 messages, the graph contains the expected knowledge."""

    async def test_graph_is_not_empty(self, e2e_result: GraphStore):
        assert e2e_result.node_count > 0
        assert e2e_result.edge_count > 0

    async def test_expected_node_count(self, e2e_result: GraphStore):
        # Alex, User, Lena, Tokyo, software engineering, sushi, ramen,
        # children, Python = 9 unique entities
        # (User appears in multiple messages but is deduplicated)
        assert e2e_result.node_count >= 8

    async def test_expected_edge_count(self, e2e_result: GraphStore):
        # named, occupation, married_to, 2x traveling_to, 2x prefers,
        # has_children, experienced_with = 9+
        assert e2e_result.edge_count >= 7


class TestPeopleExtracted:
    """People mentioned in the conversation are in the graph."""

    async def test_alex_exists(self, e2e_result: GraphStore):
        matches = e2e_result.find_nodes(name_contains="Alex")
        assert len(matches) >= 1

    async def test_lena_exists(self, e2e_result: GraphStore):
        matches = e2e_result.find_nodes(name_contains="Lena")
        assert len(matches) >= 1

    async def test_user_exists(self, e2e_result: GraphStore):
        matches = e2e_result.find_nodes(name_contains="User")
        assert len(matches) >= 1

    async def test_children_exist(self, e2e_result: GraphStore):
        matches = e2e_result.find_nodes(name_contains="children")
        assert len(matches) >= 1


class TestPlacesAndConcepts:
    """Places and concepts mentioned are in the graph."""

    async def test_tokyo_exists(self, e2e_result: GraphStore):
        matches = e2e_result.find_nodes(name_contains="Tokyo")
        assert len(matches) == 1
        assert matches[0]["node_type"] == NodeType.ENTITY.value

    async def test_python_exists(self, e2e_result: GraphStore):
        matches = e2e_result.find_nodes(name_contains="Python")
        assert len(matches) == 1

    async def test_sushi_exists(self, e2e_result: GraphStore):
        matches = e2e_result.find_nodes(name_contains="sushi")
        assert len(matches) >= 1

    async def test_ramen_exists(self, e2e_result: GraphStore):
        matches = e2e_result.find_nodes(name_contains="ramen")
        assert len(matches) >= 1


class TestRelationships:
    """Key relationships are captured with correct types and confidence."""

    async def test_married_to_relation(self, e2e_result: GraphStore):
        edges = e2e_result.get_edges(relation="married_to")
        assert len(edges) >= 1
        edge = edges[0]
        assert edge["confidence"] >= 0.85

    async def test_traveling_to_relation(self, e2e_result: GraphStore):
        edges = e2e_result.get_edges(relation="traveling_to")
        assert len(edges) >= 1  # At least User → Tokyo

    async def test_food_preferences(self, e2e_result: GraphStore):
        prefs = e2e_result.get_edges(relation="prefers")
        assert len(prefs) >= 2  # Lena→sushi, User→ramen
        targets = {e["target_id"] for e in prefs}
        # Resolve target names
        target_names = set()
        for tid in targets:
            node = e2e_result.get_node(tid)
            if node:
                target_names.add(node["name"].lower())
        assert "sushi" in target_names or "ramen" in target_names

    async def test_has_children_relation(self, e2e_result: GraphStore):
        edges = e2e_result.get_edges(relation="has_children")
        assert len(edges) >= 1
        assert edges[0]["confidence"] >= 0.85

    async def test_python_experience(self, e2e_result: GraphStore):
        edges = e2e_result.get_edges(relation="experienced_with")
        assert len(edges) >= 1
        edge = edges[0]
        assert edge["confidence"] >= 0.85


class TestConfidenceScores:
    """Confidence scores are in expected ranges."""

    async def test_all_confidences_in_range(self, e2e_result: GraphStore):
        data = e2e_result.to_dict()
        for edge in data["edges"]:
            assert 0.0 <= edge["confidence"] <= 1.0, (
                f"Edge {edge['relation']} has confidence {edge['confidence']} out of range"
            )

    async def test_explicit_facts_high_confidence(self, e2e_result: GraphStore):
        """Explicit statements should have confidence >= 0.85."""
        high_confidence_relations = ["married_to", "named", "has_children"]
        for rel in high_confidence_relations:
            edges = e2e_result.get_edges(relation=rel)
            for edge in edges:
                assert edge["confidence"] >= 0.85, (
                    f"{rel} confidence {edge['confidence']} < 0.85"
                )


class TestGraphStructure:
    """The graph is structurally sound."""

    async def test_no_orphan_edges(self, e2e_result: GraphStore):
        """Every edge connects two existing nodes."""
        data = e2e_result.to_dict()
        node_ids = {n["id"] for n in data["nodes"]}
        for edge in data["edges"]:
            assert edge["source_id"] in node_ids, f"Orphan source: {edge['source_id']}"
            assert edge["target_id"] in node_ids, f"Orphan target: {edge['target_id']}"

    async def test_serialization_roundtrip(self, e2e_result: GraphStore):
        """to_dict() produces a complete, consistent snapshot."""
        data = e2e_result.to_dict()
        assert data["stats"]["node_count"] == len(data["nodes"])
        assert data["stats"]["edge_count"] == len(data["edges"])

    async def test_user_is_central_node(self, e2e_result: GraphStore):
        """User should be the most connected node in the graph."""
        user_nodes = e2e_result.find_nodes(name_contains="User")
        assert len(user_nodes) >= 1
        user_id = user_nodes[0]["id"]
        neighbors = e2e_result.get_neighbors(user_id, depth=1)
        # User connects to most other entities
        assert len(neighbors) >= 3


class TestIncrementalGrowth:
    """The graph builds incrementally — each message adds to the previous state."""

    async def test_graph_grows_with_each_message(self, mock_llm_with_corpus: MockLLMClient):
        store = GraphStore()
        pipeline = ExtractionPipeline(mock_llm_with_corpus)

        prev_nodes = 0
        prev_edges = 0

        for i, message in enumerate(CONVERSATION):
            await process_message(message, pipeline, store)
            # Graph should be at least as large as before (may grow or stay same
            # if message adds no new info, but never shrink)
            assert store.node_count >= prev_nodes, f"Nodes shrank after message {i+1}"
            assert store.edge_count >= prev_edges, f"Edges shrank after message {i+1}"
            prev_nodes = store.node_count
            prev_edges = store.edge_count

        # After all messages, graph should be substantially populated
        assert store.node_count >= 8
        assert store.edge_count >= 7

    async def test_llm_called_for_each_message(self, mock_llm_with_corpus: MockLLMClient):
        store = GraphStore()
        pipeline = ExtractionPipeline(mock_llm_with_corpus)

        for message in CONVERSATION:
            await process_message(message, pipeline, store)

        assert mock_llm_with_corpus.call_count == len(CONVERSATION)
