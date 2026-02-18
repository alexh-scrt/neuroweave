"""Tests for the NeuroWeave public API facade."""

from __future__ import annotations

import asyncio

import pytest

from neuroweave.api import ContextResult, EventType, NeuroWeave, ProcessResult
from neuroweave.graph.query import QueryResult
from neuroweave.graph.store import GraphEvent, GraphEventType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _drain() -> None:
    """Yield control so event tasks can run."""
    await asyncio.sleep(0)
    await asyncio.sleep(0)


def _make_nw(**overrides) -> NeuroWeave:
    """Create a NeuroWeave instance with mock LLM defaults."""
    defaults = dict(llm_provider="mock", log_level="DEBUG", log_format="console")
    defaults.update(overrides)
    return NeuroWeave(**defaults)


# Five-message conversation corpus — same as conftest.py
CORPUS = [
    "My name is Alex and I'm a software engineer.",
    "My wife Lena and I are going to Tokyo in March.",
    "She loves sushi but I prefer ramen.",
    "We have two kids in elementary school.",
    "I've been using Python for 10 years.",
]


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    async def test_start_and_stop(self):
        nw = _make_nw()
        assert not nw.is_started

        await nw.start()
        assert nw.is_started

        await nw.stop()
        assert not nw.is_started

    async def test_context_manager(self):
        async with _make_nw() as nw:
            assert nw.is_started
        # After exiting context manager
        assert not nw.is_started

    async def test_double_start_is_safe(self):
        async with _make_nw() as nw:
            await nw.start()  # Should not raise
            assert nw.is_started

    async def test_double_stop_is_safe(self):
        nw = _make_nw()
        await nw.start()
        await nw.stop()
        await nw.stop()  # Should not raise

    async def test_not_started_raises(self):
        nw = _make_nw()
        with pytest.raises(RuntimeError, match="not started"):
            await nw.process("hello")

    async def test_not_started_query_raises(self):
        nw = _make_nw()
        with pytest.raises(RuntimeError, match="not started"):
            await nw.query("anything")

    async def test_not_started_get_context_raises(self):
        nw = _make_nw()
        with pytest.raises(RuntimeError, match="not started"):
            await nw.get_context("anything")

    async def test_not_started_subscribe_raises(self):
        nw = _make_nw()

        async def handler(event: GraphEvent) -> None:
            pass

        with pytest.raises(RuntimeError, match="not started"):
            nw.subscribe(handler)

    async def test_unsubscribe_before_start_is_safe(self):
        nw = _make_nw()

        async def handler(event: GraphEvent) -> None:
            pass

        nw.unsubscribe(handler)  # Should not raise


# ---------------------------------------------------------------------------
# from_config
# ---------------------------------------------------------------------------


class TestFromConfig:
    async def test_from_config_creates_instance(self, tmp_path):
        config_file = tmp_path / "test.yaml"
        config_file.write_text(
            "llm_provider: mock\nlog_level: DEBUG\nlog_format: console\n"
        )
        nw = NeuroWeave.from_config(str(config_file))
        assert not nw.is_started

        async with nw:
            assert nw.is_started


# ---------------------------------------------------------------------------
# Process (write path)
# ---------------------------------------------------------------------------


class TestProcess:
    async def test_process_returns_result(self):
        async with _make_nw() as nw:
            result = await nw.process("My name is Alex")
            assert isinstance(result, ProcessResult)

    async def test_process_with_mock_extracts_nothing(self):
        """Mock LLM with no registered responses returns empty extraction."""
        async with _make_nw() as nw:
            result = await nw.process("My name is Alex")
            # Default MockLLMClient returns empty for unmatched messages
            assert result.entity_count == 0
            assert result.relation_count == 0

    async def test_process_updates_graph(self):
        """Even with empty extraction, the graph should be queryable."""
        async with _make_nw() as nw:
            await nw.process("Hello world")
            # Graph starts empty and stays empty for unmatched mock
            assert nw.graph.node_count == 0

    async def test_process_result_to_dict(self):
        async with _make_nw() as nw:
            result = await nw.process("test")
            d = result.to_dict()
            assert "entities_extracted" in d
            assert "relations_extracted" in d
            assert "nodes_added" in d
            assert "edges_added" in d
            assert "extraction_ms" in d


# ---------------------------------------------------------------------------
# Query (read path)
# ---------------------------------------------------------------------------


class TestQuery:
    async def test_query_structured_empty_graph(self):
        async with _make_nw() as nw:
            result = await nw.query(["User"])
            assert isinstance(result, QueryResult)
            assert result.is_empty

    async def test_query_whole_graph(self):
        async with _make_nw() as nw:
            result = await nw.query()
            assert isinstance(result, QueryResult)
            assert result.is_empty  # Empty graph

    async def test_query_structured_with_kwargs(self):
        async with _make_nw() as nw:
            result = await nw.query(
                ["User"],
                relations=["prefers"],
                min_confidence=0.5,
                max_hops=2,
            )
            assert isinstance(result, QueryResult)

    async def test_query_nl_string(self):
        """String input triggers NL query path."""
        async with _make_nw() as nw:
            result = await nw.query("what does my wife like?")
            assert isinstance(result, QueryResult)
            # On empty graph with mock LLM, NL path falls back to broad search
            assert result.is_empty

    async def test_query_none_returns_whole_graph(self):
        async with _make_nw() as nw:
            result = await nw.query(None)
            assert isinstance(result, QueryResult)


# ---------------------------------------------------------------------------
# Get context (combined path)
# ---------------------------------------------------------------------------


class TestGetContext:
    async def test_get_context_returns_context_result(self):
        async with _make_nw() as nw:
            result = await nw.get_context("My name is Alex")
            assert isinstance(result, ContextResult)
            assert isinstance(result.process, ProcessResult)
            assert isinstance(result.relevant, QueryResult)

    async def test_get_context_includes_plan(self):
        async with _make_nw() as nw:
            result = await nw.get_context("test message")
            assert result.plan is not None

    async def test_get_context_to_dict(self):
        async with _make_nw() as nw:
            result = await nw.get_context("test")
            d = result.to_dict()
            assert "process" in d
            assert "relevant" in d
            assert "plan" in d


# ---------------------------------------------------------------------------
# Event subscription
# ---------------------------------------------------------------------------


class TestEventSubscription:
    async def test_subscribe_and_receive_events(self):
        async with _make_nw() as nw:
            received: list[GraphEvent] = []

            async def handler(event: GraphEvent) -> None:
                received.append(event)

            nw.subscribe(handler, event_types={EventType.NODE_ADDED})

            # Manually add a node to trigger event
            from neuroweave.graph.store import NodeType, make_node

            nw.graph.add_node(make_node("Test", NodeType.ENTITY))
            await _drain()

            assert len(received) == 1
            assert received[0].event_type == GraphEventType.NODE_ADDED

    async def test_subscribe_all_events(self):
        async with _make_nw() as nw:
            received: list[GraphEvent] = []

            async def handler(event: GraphEvent) -> None:
                received.append(event)

            nw.subscribe(handler)  # No filter — all events

            from neuroweave.graph.store import NodeType, make_edge, make_node

            nw.graph.add_node(make_node("A", NodeType.ENTITY, node_id="a"))
            nw.graph.add_node(make_node("B", NodeType.ENTITY, node_id="b"))
            nw.graph.add_edge(make_edge("a", "b", "knows", 0.9, edge_id="e1"))
            await _drain()

            assert len(received) == 3

    async def test_unsubscribe_stops_events(self):
        async with _make_nw() as nw:
            received: list[GraphEvent] = []

            async def handler(event: GraphEvent) -> None:
                received.append(event)

            nw.subscribe(handler)

            from neuroweave.graph.store import NodeType, make_node

            nw.graph.add_node(make_node("A", NodeType.ENTITY, node_id="a"))
            await _drain()
            assert len(received) == 1

            nw.unsubscribe(handler)

            nw.graph.add_node(make_node("B", NodeType.ENTITY, node_id="b"))
            await _drain()
            assert len(received) == 1  # Still 1 — no new event


# ---------------------------------------------------------------------------
# Property accessors
# ---------------------------------------------------------------------------


class TestProperties:
    async def test_graph_property(self):
        async with _make_nw() as nw:
            assert nw.graph is not None
            assert nw.graph.node_count == 0

    async def test_event_bus_property(self):
        async with _make_nw() as nw:
            assert nw.event_bus is not None

    async def test_graph_property_before_start_raises(self):
        nw = _make_nw()
        with pytest.raises(RuntimeError):
            _ = nw.graph


# ---------------------------------------------------------------------------
# Visualization
# ---------------------------------------------------------------------------


class TestVisualization:
    async def test_create_visualization_app(self):
        async with _make_nw() as nw:
            app = nw.create_visualization_app()
            assert app is not None
            # Should be a FastAPI instance
            assert hasattr(app, "routes")

    async def test_create_visualization_app_before_start_raises(self):
        nw = _make_nw()
        with pytest.raises(RuntimeError):
            nw.create_visualization_app()


# ---------------------------------------------------------------------------
# Top-level imports
# ---------------------------------------------------------------------------


class TestImports:
    def test_import_from_package(self):
        """Verify the public API can be imported from the top-level package."""
        from neuroweave import (
            ContextResult,
            EventType,
            NeuroWeave,
            ProcessResult,
            QueryResult,
        )

        assert NeuroWeave is not None
        assert ProcessResult is not None
        assert ContextResult is not None
        assert QueryResult is not None
        assert EventType is not None

    def test_event_type_aliases(self):
        """EventType should alias GraphEventType."""
        assert EventType.NODE_ADDED == GraphEventType.NODE_ADDED
        assert EventType.EDGE_ADDED == GraphEventType.EDGE_ADDED
        assert EventType.NODE_UPDATED == GraphEventType.NODE_UPDATED
        assert EventType.EDGE_UPDATED == GraphEventType.EDGE_UPDATED


# ---------------------------------------------------------------------------
# Full integration: process 5-message corpus
# ---------------------------------------------------------------------------


class TestFullIntegration:
    async def test_process_corpus_builds_graph(self):
        """Feed the 5-message corpus and verify graph state.

        Since we're using the default MockLLMClient (no registered
        responses), extraction will return empty results. This test
        verifies the plumbing works end-to-end without errors.
        """
        async with _make_nw() as nw:
            for msg in CORPUS:
                result = await nw.process(msg)
                assert isinstance(result, ProcessResult)

    async def test_get_context_after_corpus(self):
        async with _make_nw() as nw:
            for msg in CORPUS:
                await nw.process(msg)

            context = await nw.get_context("what do you know about me?")
            assert isinstance(context, ContextResult)
            assert context.plan is not None

    async def test_events_fire_during_corpus(self):
        """Events should fire as graph is mutated during processing."""
        async with _make_nw() as nw:
            events: list[GraphEvent] = []

            async def handler(event: GraphEvent) -> None:
                events.append(event)

            nw.subscribe(handler)

            # Manually add nodes to ensure events fire
            from neuroweave.graph.store import NodeType, make_node

            nw.graph.add_node(make_node("TestNode", NodeType.ENTITY))
            await _drain()

            assert len(events) >= 1

    async def test_query_after_manual_graph_build(self):
        """Build graph manually, then query via all paths."""
        async with _make_nw() as nw:
            from neuroweave.graph.store import NodeType, make_edge, make_node

            nw.graph.add_node(make_node("User", NodeType.ENTITY, node_id="user"))
            nw.graph.add_node(make_node("Lena", NodeType.ENTITY, node_id="lena"))
            nw.graph.add_node(make_node("sushi", NodeType.CONCEPT, node_id="sushi"))
            nw.graph.add_edge(make_edge("user", "lena", "married_to", 0.9))
            nw.graph.add_edge(make_edge("lena", "sushi", "prefers", 0.9))

            # Structured query
            result = await nw.query(["Lena"], relations=["prefers"], max_hops=1)
            assert "sushi" in result.node_names()
            assert "Lena" in result.node_names()

            # Whole-graph query
            result = await nw.query()
            assert result.node_count == 3
            assert result.edge_count == 2

            # NL query (mock LLM won't produce a great plan, but shouldn't crash)
            result = await nw.query("what does my wife like?")
            assert isinstance(result, QueryResult)
