"""Tests for NW-001 — Neo4j backend, graph store factory, config fields."""

from __future__ import annotations

import queue
from typing import Any
from unittest.mock import MagicMock, patch

from neuroweave.config import GraphBackend, NeuroWeaveConfig
from neuroweave.graph.backends.memory import MemoryGraphStore
from neuroweave.graph.store import Edge, GraphEvent, GraphEventType, Node, NodeType

# ---------------------------------------------------------------------------
# Mock Neo4j driver
# ---------------------------------------------------------------------------


class MockRecord:
    def __init__(self, data: dict[str, Any]):
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]


class MockResult:
    def __init__(self, records: list[dict[str, Any]] | None = None):
        self._records = records or []
        self._index = 0

    async def single(self) -> MockRecord | None:
        if self._records:
            return MockRecord(self._records[0])
        return None

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._records):
            raise StopAsyncIteration
        record = MockRecord(self._records[self._index])
        self._index += 1
        return record


class MockSession:
    def __init__(self):
        self.queries: list[str] = []

    async def run(self, query: str, **params: Any) -> MockResult:
        self.queries.append(query.strip())
        # Return a generic record for add_node MERGE
        if "MERGE" in query and "NWNode" in query:
            return MockResult([{"id": params.get("id", "test"), "created": 1}])
        if "MATCH" in query and "RETURN n" in query:
            return MockResult([{"n": {"id": "n1", "name": "Test", "node_type": "entity"}}])
        if "RETURN DISTINCT neighbor" in query:
            return MockResult([])
        return MockResult([])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args: Any):
        pass


class MockDriver:
    def __init__(self):
        self._session = MockSession()
        self.closed = False

    def session(self, database: str = "neo4j") -> MockSession:
        return self._session

    async def close(self):
        self.closed = True


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _make_neo4j_store(driver: MockDriver):  # -> Neo4jGraphStore
    """Helper to build a Neo4jGraphStore without calling __init__ (no real neo4j import)."""
    from neuroweave.graph.backends.neo4j import Neo4jGraphStore

    store = Neo4jGraphStore.__new__(Neo4jGraphStore)
    store._driver = driver
    store._database = "neo4j"
    store._event_queue = None
    store._event_bus = None
    store._lock = __import__("threading").Lock()
    store._node_count = 0
    store._edge_count = 0
    return store


async def test_neo4j_store_add_node_runs_merge_cypher():
    """Neo4j add_node should run a MERGE cypher query."""
    driver = MockDriver()
    store = _make_neo4j_store(driver)

    node = Node(id="n1", name="Test", node_type=NodeType.ENTITY)
    await store.add_node(node)
    assert any("MERGE" in q for q in driver._session.queries)


async def test_neo4j_store_find_nodes_with_type_filter():
    driver = MockDriver()
    store = _make_neo4j_store(driver)
    await store.find_nodes(node_type="theorem", name_contains=None)
    assert any("node_type" in q for q in driver._session.queries)


async def test_neo4j_store_find_nodes_with_name_contains():
    driver = MockDriver()
    store = _make_neo4j_store(driver)
    await store.find_nodes(node_type=None, name_contains="euler")
    assert any("CONTAINS" in q for q in driver._session.queries)


async def test_neo4j_store_add_edge_runs_merge_cypher():
    driver = MockDriver()
    store = _make_neo4j_store(driver)
    edge = Edge(id="e1", source_id="n1", target_id="n2", relation="proves", confidence=0.9)
    await store.add_edge(edge)
    assert any("MERGE" in q and "NW_EDGE" in q for q in driver._session.queries)


async def test_neo4j_store_get_edges_with_relation_filter():
    driver = MockDriver()
    store = _make_neo4j_store(driver)
    await store.get_edges(source_id=None, target_id=None, relation="proves")
    assert any("r.relation" in q for q in driver._session.queries)


async def test_neo4j_store_get_neighbors_uses_variable_depth():
    driver = MockDriver()
    store = _make_neo4j_store(driver)
    await store.get_neighbors("n1", depth=3)
    assert any("1..3" in q for q in driver._session.queries)


async def test_neo4j_store_emits_node_added_event():
    driver = MockDriver()
    store = _make_neo4j_store(driver)
    q: queue.Queue[GraphEvent] = queue.Queue()
    store._event_queue = q

    node = Node(id="n1", name="Test", node_type=NodeType.ENTITY)
    await store.add_node(node)
    event = q.get_nowait()
    assert event.event_type == GraphEventType.NODE_ADDED


async def test_neo4j_store_emits_edge_added_event():
    driver = MockDriver()
    store = _make_neo4j_store(driver)
    q: queue.Queue[GraphEvent] = queue.Queue()
    store._event_queue = q

    edge = Edge(id="e1", source_id="n1", target_id="n2", relation="proves", confidence=0.9)
    await store.add_edge(edge)
    event = q.get_nowait()
    assert event.event_type == GraphEventType.EDGE_ADDED


async def test_neo4j_store_to_dict_returns_correct_structure():
    driver = MockDriver()
    store = _make_neo4j_store(driver)
    result = await store.to_dict()
    assert "nodes" in result
    assert "edges" in result
    assert "stats" in result


async def test_build_graph_store_returns_memory_for_memory_backend():
    from neuroweave.api import _build_graph_store

    config = NeuroWeaveConfig(graph_backend=GraphBackend.MEMORY)
    store = await _build_graph_store(config)
    assert isinstance(store, MemoryGraphStore)


async def test_build_graph_store_returns_neo4j_for_neo4j_backend():
    """Verify the factory dispatches to Neo4jGraphStore for neo4j backend.

    Since neo4j isn't installed in dev, we mock the deferred import.
    """
    import sys
    import types

    # Create a fake neo4j module with AsyncGraphDatabase
    fake_neo4j = types.ModuleType("neo4j")
    fake_agd = MagicMock()
    fake_agd.driver.return_value = MockDriver()
    fake_neo4j.AsyncGraphDatabase = fake_agd  # type: ignore[attr-defined]
    sys.modules["neo4j"] = fake_neo4j
    try:
        # Clear the cached import so it picks up our fake
        import importlib

        import neuroweave.graph.backends.neo4j as neo4j_mod

        importlib.reload(neo4j_mod)

        from neuroweave.api import _build_graph_store

        config = NeuroWeaveConfig(graph_backend=GraphBackend.NEO4J)
        store = await _build_graph_store(config)
        assert type(store).__name__ == "Neo4jGraphStore"
    finally:
        del sys.modules["neo4j"]


async def test_neuroweave_facade_uses_neo4j_when_configured():
    """Verify the factory is called when neo4j is configured."""
    from neuroweave import NeuroWeave

    with patch("neuroweave.api._build_graph_store", return_value=MemoryGraphStore()) as mock_build:
        nw = NeuroWeave(llm_provider="mock")
        nw._config = nw._config.model_copy(update={"graph_backend": GraphBackend.NEO4J})
        await nw.start()
        mock_build.assert_called_once()
        await nw.stop()


def test_neo4j_config_fields_loaded_from_yaml():
    config = NeuroWeaveConfig.load()
    assert config.neo4j_uri == "neo4j://localhost:7687"
    assert config.neo4j_user == "neo4j"
    assert config.neo4j_password == ""
    assert config.neo4j_database == "neo4j"


def test_neo4j_config_fields_loaded_from_env_vars(monkeypatch):
    monkeypatch.setenv("NEUROWEAVE_NEO4J_URI", "neo4j://custom:7688")
    monkeypatch.setenv("NEUROWEAVE_NEO4J_USER", "admin")
    monkeypatch.setenv("NEUROWEAVE_NEO4J_PASSWORD", "secret")
    monkeypatch.setenv("NEUROWEAVE_NEO4J_DATABASE", "mydb")
    # Use constructor directly to test env var loading (NeuroWeaveConfig.load()
    # passes YAML values which take precedence over env vars)
    config = NeuroWeaveConfig()
    assert config.neo4j_uri == "neo4j://custom:7688"
    assert config.neo4j_user == "admin"
    assert config.neo4j_password == "secret"
    assert config.neo4j_database == "mydb"
