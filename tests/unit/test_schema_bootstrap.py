"""Tests for NW-FIX-002 — Neo4j schema bootstrap verification."""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from neuroweave.graph.backends.memory import MemoryGraphStore


class MockResult:
    async def single(self):
        return None
    def __aiter__(self):
        return self
    async def __anext__(self):
        raise StopAsyncIteration


class MockSession:
    def __init__(self):
        self.queries: list[str] = []
    async def run(self, query: str, **params: Any) -> MockResult:
        self.queries.append(query)
        return MockResult()
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass


class MockDriver:
    def __init__(self):
        self._session = MockSession()
    def session(self, **kwargs):
        return self._session
    async def close(self):
        pass


def _make_neo4j_store(driver: MockDriver):
    from neuroweave.graph.backends.neo4j import Neo4jGraphStore
    store = Neo4jGraphStore.__new__(Neo4jGraphStore)
    store._driver = driver
    store._database = "neo4j"
    store._event_queue = None
    store._event_bus = None
    store._lock = threading.Lock()
    store._node_count = 0
    store._edge_count = 0
    return store


@pytest.mark.asyncio
async def test_initialize_creates_id_constraint_cypher():
    driver = MockDriver()
    store = _make_neo4j_store(driver)
    await store.initialize()
    queries = driver._session.queries
    assert any("nwnode_id_unique" in q for q in queries), (
        f"Expected 'nwnode_id_unique' constraint in queries: {queries}"
    )


@pytest.mark.asyncio
async def test_initialize_creates_name_index_cypher():
    driver = MockDriver()
    store = _make_neo4j_store(driver)
    await store.initialize()
    queries = driver._session.queries
    assert any("nwnode_name_idx" in q for q in queries), (
        f"Expected 'nwnode_name_idx' index in queries: {queries}"
    )


@pytest.mark.asyncio
async def test_initialize_creates_type_index_cypher():
    driver = MockDriver()
    store = _make_neo4j_store(driver)
    await store.initialize()
    queries = driver._session.queries
    assert any("nwnode_type_idx" in q for q in queries), (
        f"Expected 'nwnode_type_idx' index in queries: {queries}"
    )


@pytest.mark.asyncio
async def test_initialize_creates_relation_index_cypher():
    driver = MockDriver()
    store = _make_neo4j_store(driver)
    await store.initialize()
    queries = driver._session.queries
    assert any("nwedge_relation_idx" in q for q in queries), (
        f"Expected 'nwedge_relation_idx' index in queries: {queries}"
    )


@pytest.mark.asyncio
async def test_initialize_uses_if_not_exists_syntax():
    driver = MockDriver()
    store = _make_neo4j_store(driver)
    await store.initialize()
    queries = driver._session.queries
    for q in queries:
        assert "IF NOT EXISTS" in q, (
            f"Expected 'IF NOT EXISTS' in query: {q}"
        )


@pytest.mark.asyncio
async def test_initialize_called_from_build_graph_store():
    from neuroweave.api import _build_graph_store
    from neuroweave.config import NeuroWeaveConfig
    config = NeuroWeaveConfig()
    with patch.object(MemoryGraphStore, 'initialize', new_callable=AsyncMock) as mock_init:
        store = await _build_graph_store(config)
        mock_init.assert_called_once()


@pytest.mark.asyncio
async def test_initialize_called_from_neuroweave_aenter():
    from neuroweave import NeuroWeave
    with patch.object(MemoryGraphStore, 'initialize', new_callable=AsyncMock) as mock_init:
        async with NeuroWeave(llm_provider="mock") as nw:
            mock_init.assert_called_once()
