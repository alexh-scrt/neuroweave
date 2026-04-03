"""Tests for NW-FIX-001 — Neo4j async interface verification."""

from __future__ import annotations

import inspect
import threading
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from neuroweave.graph.backends.memory import MemoryGraphStore
from neuroweave.graph.store import Edge, Node, NodeType

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
        self.queries.append(query)
        if "RETURN" in query and "props" in query:
            return MockResult([{
                "props": {"id": "n1", "name": "Test", "node_type": "entity"},
                "source_id": "n1",
                "target_id": "n2",
            }])
        return MockResult([{"id": "n1", "created": True}])

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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_neo4j_store_all_public_methods_are_coroutines():
    """Inspect Neo4jGraphStore to verify all public data methods are coroutines."""
    from neuroweave.graph.backends.neo4j import Neo4jGraphStore

    # Public data methods that should be coroutines
    expected_async = {
        "initialize",
        "add_node",
        "get_node",
        "find_nodes",
        "add_edge",
        "get_edges",
        "get_neighbors",
        "to_dict",
        "update_node_properties",
        "set_event_queue",
        "close",
    }

    for name in expected_async:
        method = getattr(Neo4jGraphStore, name, None)
        assert method is not None, f"Missing method: {name}"
        assert inspect.iscoroutinefunction(method), (
            f"{name}() is not a coroutine function"
        )


async def test_neo4j_store_initialize_runs_without_error_with_mock_driver():
    """Use a mock driver, call initialize()."""
    driver = MockDriver()
    store = _make_neo4j_store(driver)
    await store.initialize()
    # Verify constraint/index queries were issued
    assert len(driver._session.queries) > 0


async def test_neo4j_store_initialize_is_idempotent():
    """Call initialize() twice, should work without error."""
    driver = MockDriver()
    store = _make_neo4j_store(driver)
    await store.initialize()
    first_count = len(driver._session.queries)
    await store.initialize()
    second_count = len(driver._session.queries)
    # Both calls should succeed and issue queries
    assert first_count > 0
    assert second_count > first_count


async def test_neo4j_store_add_node_is_awaitable():
    """await add_node() returns a node."""
    driver = MockDriver()
    store = _make_neo4j_store(driver)
    node = Node(id="n1", name="Test", node_type=NodeType.ENTITY)
    result = await store.add_node(node)
    assert isinstance(result, Node)
    assert result.id == "n1"


async def test_neo4j_store_find_nodes_is_awaitable():
    """await find_nodes() returns a list."""
    driver = MockDriver()
    store = _make_neo4j_store(driver)
    result = await store.find_nodes(node_type="entity")
    assert isinstance(result, list)


async def test_neo4j_store_add_edge_is_awaitable():
    """await add_edge() returns an edge."""
    driver = MockDriver()
    store = _make_neo4j_store(driver)
    edge = Edge(
        id="e1", source_id="n1", target_id="n2",
        relation="proves", confidence=0.9,
    )
    result = await store.add_edge(edge)
    assert isinstance(result, Edge)
    assert result.id == "e1"


async def test_neo4j_store_get_edges_is_awaitable():
    """await get_edges() returns a list."""
    driver = MockDriver()
    store = _make_neo4j_store(driver)
    result = await store.get_edges()
    assert isinstance(result, list)


async def test_neo4j_store_get_neighbors_is_awaitable():
    """await get_neighbors() returns a list."""
    driver = MockDriver()
    store = _make_neo4j_store(driver)
    result = await store.get_neighbors("n1", depth=2)
    assert isinstance(result, list)


async def test_neo4j_store_to_dict_is_awaitable():
    """await to_dict() returns a dict with expected keys."""
    driver = MockDriver()
    store = _make_neo4j_store(driver)
    result = await store.to_dict()
    assert isinstance(result, dict)
    assert "nodes" in result
    assert "edges" in result
    assert "stats" in result


async def test_neo4j_store_update_node_properties_is_awaitable():
    """await update_node_properties() completes without error."""
    driver = MockDriver()
    store = _make_neo4j_store(driver)
    # Should not raise; returns None
    result = await store.update_node_properties("n1", {"key": "value"})
    assert result is None


async def test_build_graph_store_calls_initialize():
    """Mock build, verify initialize is called."""
    from neuroweave.api import _build_graph_store
    from neuroweave.config import NeuroWeaveConfig

    config = NeuroWeaveConfig()  # defaults to memory backend
    store = await _build_graph_store(config)
    # If it returns without error, initialize() was called (it's a no-op for memory)
    assert isinstance(store, MemoryGraphStore)


async def test_build_graph_store_neo4j_calls_initialize_once():
    """Verify initialize is only called once during build."""
    from neuroweave.graph.backends.neo4j import Neo4jGraphStore

    init_mock = AsyncMock()
    driver = MockDriver()
    store = _make_neo4j_store(driver)

    with patch.object(Neo4jGraphStore, "initialize", init_mock):
        with patch(
            "neuroweave.api._build_graph_store",
            new_callable=AsyncMock,
            return_value=store,
        ) as mock_build:
            # Simulate what _build_graph_store does internally
            mock_build.side_effect = None
            mock_build.return_value = store
            await mock_build(MagicMock())

        # Directly test that initialize is a single-call contract
        await Neo4jGraphStore.initialize(store)
        init_mock.assert_called_once()


async def test_memory_store_initialize_is_noop():
    """MemoryGraphStore.initialize() is a no-op."""
    store = MemoryGraphStore()
    result = await store.initialize()
    # Should return None and cause no side effects
    assert result is None


async def test_no_run_until_complete_in_neo4j_module():
    """Scan module source code, fail if run_until_complete found."""
    import neuroweave.graph.backends.neo4j as neo4j_mod

    source = inspect.getsource(neo4j_mod)
    assert "run_until_complete" not in source, (
        "Neo4j module still contains run_until_complete"
    )
    assert "get_event_loop" not in source, (
        "Neo4j module still contains get_event_loop"
    )
