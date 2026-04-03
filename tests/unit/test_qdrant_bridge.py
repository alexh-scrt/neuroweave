"""Tests for NW-004 — Qdrant integration bridge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from neuroweave.graph.query import QueryResult
from neuroweave.graph.store import GraphStore, NodeType, make_edge, make_node
from neuroweave.vector.qdrant_bridge import QdrantBridge, VectorContextResult


@pytest.fixture
def store() -> GraphStore:
    s = GraphStore()
    n1 = make_node("Chromatic Polynomial", NodeType.THEOREM, node_id="n1")
    n2 = make_node("Planar Graphs", NodeType.CONCEPT, node_id="n2")
    s.add_node(n1)
    s.add_node(n2)
    s.add_edge(make_edge("n1", "n2", "applies_to", 0.9, edge_id="e1"))
    return s


@dataclass
class MockScoredPoint:
    id: str
    score: float
    payload: dict[str, Any]


class MockQdrantClient:
    def __init__(self, results: list[MockScoredPoint] | None = None):
        self._results = results or []
        self.search_calls: list[dict[str, Any]] = []
        self.upsert_calls: list[dict[str, Any]] = []

    async def search(self, **kwargs: Any) -> list[MockScoredPoint]:
        self.search_calls.append(kwargs)
        return self._results

    async def upsert(self, **kwargs: Any) -> None:
        self.upsert_calls.append(kwargs)


# ---------------------------------------------------------------------------
# VectorContextResult
# ---------------------------------------------------------------------------


def test_vector_context_result_all_node_names_deduplicates():
    graph_ctx = QueryResult(
        nodes=[{"id": "n1", "name": "Alpha"}, {"id": "n2", "name": "Beta"}],
        edges=[],
    )
    vector_matches = [
        {"id": "v1", "score": 0.9, "payload": {"name": "Beta"}},
        {"id": "v2", "score": 0.8, "payload": {"name": "Gamma"}},
    ]
    result = VectorContextResult(
        graph_context=graph_ctx,
        vector_matches=vector_matches,
        combined_node_ids={"n1", "n2", "v1", "v2"},
        query="test",
        vector_collection="test_collection",
    )
    names = result.all_node_names()
    assert names == ["Alpha", "Beta", "Gamma"]  # deduplicated, order preserved


def test_vector_context_result_combined_node_ids_is_union():
    graph_ctx = QueryResult(
        nodes=[{"id": "n1", "name": "A"}],
        edges=[],
    )
    result = VectorContextResult(
        graph_context=graph_ctx,
        vector_matches=[{"id": "v1", "score": 0.9, "payload": {}}],
        combined_node_ids={"n1", "v1"},
        query="test",
        vector_collection="col",
    )
    assert result.combined_node_ids == {"n1", "v1"}


# ---------------------------------------------------------------------------
# QdrantBridge
# ---------------------------------------------------------------------------


async def test_qdrant_bridge_runs_graph_and_vector_concurrently(store):
    mock_qdrant = MockQdrantClient(results=[
        MockScoredPoint(id="v1", score=0.95, payload={"name": "Result 1"}),
    ])
    bridge = QdrantBridge(store=store, qdrant_client=mock_qdrant)
    result = await bridge.get_context_with_vectors(
        query="chromatic polynomial for planar graphs",
        query_vector=[0.1, 0.2, 0.3],
        top_k=5,
    )
    assert isinstance(result, VectorContextResult)
    assert len(result.vector_matches) == 1
    assert len(result.combined_node_ids) > 0


async def test_qdrant_bridge_graph_query_returns_nodes_by_name(store):
    mock_qdrant = MockQdrantClient()
    bridge = QdrantBridge(store=store, qdrant_client=mock_qdrant)
    graph_result = await bridge._graph_query("Chromatic Polynomial", max_hops=1)
    names = {n["name"] for n in graph_result.nodes}
    assert "Chromatic Polynomial" in names


async def test_qdrant_bridge_vector_search_calls_qdrant_with_correct_params(store):
    mock_qdrant = MockQdrantClient()
    bridge = QdrantBridge(store=store, qdrant_client=mock_qdrant)
    # Test without filter (qdrant_client not installed in dev)
    await bridge._vector_search(
        query_vector=[0.1, 0.2],
        top_k=10,
        qdrant_filter=None,
    )
    assert len(mock_qdrant.search_calls) == 1
    assert mock_qdrant.search_calls[0]["limit"] == 10
    assert mock_qdrant.search_calls[0]["query_filter"] is None


async def test_qdrant_bridge_vector_search_no_filter(store):
    mock_qdrant = MockQdrantClient()
    bridge = QdrantBridge(store=store, qdrant_client=mock_qdrant)
    await bridge._vector_search(
        query_vector=[0.1, 0.2],
        top_k=5,
        qdrant_filter=None,
    )
    assert len(mock_qdrant.search_calls) == 1
    call = mock_qdrant.search_calls[0]
    assert call["query_filter"] is None


async def test_qdrant_bridge_upsert_node_vectors(store):
    import sys
    import types

    # Create fake qdrant_client.models module with PointStruct
    fake_models = types.ModuleType("qdrant_client.models")
    fake_models.PointStruct = MagicMock()  # type: ignore[attr-defined]
    fake_qdrant_client = types.ModuleType("qdrant_client")
    fake_qdrant_client.models = fake_models  # type: ignore[attr-defined]
    sys.modules["qdrant_client"] = fake_qdrant_client
    sys.modules["qdrant_client.models"] = fake_models
    try:
        mock_qdrant = MockQdrantClient()
        bridge = QdrantBridge(store=store, qdrant_client=mock_qdrant)
        await bridge.upsert_node_vectors("n1", [0.1, 0.2], payload={"extra": "data"})
        assert len(mock_qdrant.upsert_calls) == 1
    finally:
        del sys.modules["qdrant_client"]
        del sys.modules["qdrant_client.models"]


async def test_facade_get_context_with_vectors_exists():
    from neuroweave import NeuroWeave

    async with NeuroWeave(llm_provider="mock") as nw:
        assert hasattr(nw, "get_context_with_vectors")


async def test_facade_get_context_with_vectors_returns_vector_context_result():
    from neuroweave import NeuroWeave

    mock_qdrant = MockQdrantClient(results=[
        MockScoredPoint(id="v1", score=0.9, payload={"name": "Hit"}),
    ])

    async with NeuroWeave(llm_provider="mock") as nw:
        # Process a message first to populate graph
        await nw.process("I study chromatic polynomials in graph theory")
        result = await nw.get_context_with_vectors(
            query="chromatic polynomial",
            query_vector=[0.1, 0.2, 0.3],
            qdrant_client=mock_qdrant,
        )
        assert isinstance(result, VectorContextResult)
