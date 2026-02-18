"""Integration tests — full end-to-end NeuroWeave flow with mock LLM.

These tests wire together every component (extraction pipeline, graph store,
query engines, event bus, facade) and verify the canonical 5-message
conversation corpus produces the expected knowledge graph.

Unlike unit tests that mock internal boundaries, these tests only mock
the LLM — everything else runs for real.
"""

from __future__ import annotations

import asyncio

import pytest

from neuroweave import ContextResult, EventType, NeuroWeave, ProcessResult, QueryResult
from neuroweave.extraction.llm_client import MockLLMClient
from neuroweave.extraction.pipeline import ExtractionPipeline
from neuroweave.graph.nl_query import NLQueryPlanner
from neuroweave.graph.store import GraphEvent, GraphEventType


# ---------------------------------------------------------------------------
# Corpus and mock LLM setup
# ---------------------------------------------------------------------------

CORPUS = [
    "My name is Alex and I'm a software engineer.",
    "My wife Lena and I are going to Tokyo in March.",
    "She loves sushi but I prefer ramen.",
    "We have two kids in elementary school.",
    "I've been using Python for 10 years.",
]


def _build_corpus_mock() -> MockLLMClient:
    """Create a MockLLMClient with realistic extraction + NL query responses."""
    mock = MockLLMClient()

    # --- Extraction responses (matched by user message substrings) ---

    mock.set_response("alex", {
        "entities": [
            {"name": "User", "entity_type": "person"},
            {"name": "Alex", "entity_type": "person"},
            {"name": "software engineering", "entity_type": "concept"},
        ],
        "relations": [
            {"source": "User", "target": "Alex", "relation": "named", "confidence": 0.95},
            {"source": "User", "target": "software engineering", "relation": "occupation", "confidence": 0.90},
        ],
    })

    mock.set_response("lena", {
        "entities": [
            {"name": "User", "entity_type": "person"},
            {"name": "Lena", "entity_type": "person"},
            {"name": "Tokyo", "entity_type": "place"},
        ],
        "relations": [
            {"source": "User", "target": "Lena", "relation": "married_to", "confidence": 0.90},
            {"source": "User", "target": "Tokyo", "relation": "traveling_to", "confidence": 0.85},
            {"source": "Lena", "target": "Tokyo", "relation": "traveling_to", "confidence": 0.85},
        ],
    })

    mock.set_response("sushi", {
        "entities": [
            {"name": "sushi", "entity_type": "preference"},
            {"name": "ramen", "entity_type": "preference"},
        ],
        "relations": [
            {"source": "Lena", "target": "sushi", "relation": "prefers", "confidence": 0.90},
            {"source": "User", "target": "ramen", "relation": "prefers", "confidence": 0.85},
        ],
    })

    mock.set_response("kids", {
        "entities": [
            {"name": "children", "entity_type": "person"},
        ],
        "relations": [
            {"source": "User", "target": "children", "relation": "has_children", "confidence": 0.90},
        ],
    })

    mock.set_response("python", {
        "entities": [
            {"name": "Python", "entity_type": "tool"},
        ],
        "relations": [
            {"source": "User", "target": "Python", "relation": "experienced_with", "confidence": 0.90},
        ],
    })

    # --- NL query planner responses ---

    mock.set_response("wife", {
        "entities": ["Lena"],
        "relations": ["prefers"],
        "max_hops": 1,
        "min_confidence": 0.0,
        "reasoning": "User's wife is Lena, looking for her preferences",
    })

    mock.set_response("traveling", {
        "entities": ["User"],
        "relations": ["traveling_to"],
        "max_hops": 1,
        "min_confidence": 0.0,
        "reasoning": "Looking for travel plans connected to the user",
    })

    mock.set_response("know about me", {
        "entities": ["User"],
        "relations": None,
        "max_hops": 2,
        "min_confidence": 0.0,
        "reasoning": "Broad user query, return full user context",
    })

    mock.set_response("tokyo", {
        "entities": ["Tokyo"],
        "relations": None,
        "max_hops": 2,
        "min_confidence": 0.0,
        "reasoning": "Everything about Tokyo",
    })

    return mock


async def _drain() -> None:
    """Let event handler tasks complete."""
    await asyncio.sleep(0)
    await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# Fixture: NeuroWeave with mock LLM and corpus loaded
# ---------------------------------------------------------------------------


@pytest.fixture
async def nw():
    """Create a NeuroWeave instance with mock LLM, started and ready."""
    mock_llm = _build_corpus_mock()
    instance = NeuroWeave(llm_provider="mock", log_level="WARNING")
    await instance.start()
    # Inject our pre-configured mock
    instance._pipeline = ExtractionPipeline(mock_llm)
    instance._nl_planner = NLQueryPlanner(mock_llm, instance.graph)
    yield instance
    await instance.stop()


@pytest.fixture
async def nw_with_corpus(nw):
    """NeuroWeave with the 5-message corpus already processed."""
    for msg in CORPUS:
        await nw.process(msg)
    return nw


# ---------------------------------------------------------------------------
# Graph construction — verify the corpus builds expected graph
# ---------------------------------------------------------------------------


class TestGraphConstruction:
    async def test_corpus_produces_expected_nodes(self, nw_with_corpus):
        nw = nw_with_corpus
        names = {n["name"] for _, n in nw.graph._graph.nodes(data=True)}

        assert "User" in names
        assert "Alex" in names
        assert "Lena" in names
        assert "Tokyo" in names
        assert "sushi" in names
        assert "ramen" in names
        assert "children" in names
        assert "Python" in names
        assert "software engineering" in names

    async def test_node_count(self, nw_with_corpus):
        assert nw_with_corpus.graph.node_count == 9

    async def test_edge_count(self, nw_with_corpus):
        assert nw_with_corpus.graph.edge_count == 9

    async def test_node_types(self, nw_with_corpus):
        nw = nw_with_corpus
        types = {}
        for _, data in nw.graph._graph.nodes(data=True):
            types[data["name"]] = data["node_type"]

        assert types["User"] == "entity"  # person → entity
        assert types["Alex"] == "entity"
        assert types["Lena"] == "entity"
        assert types["Tokyo"] == "entity"
        assert types["Python"] == "concept"  # tool → concept
        assert types["sushi"] == "preference"  # stored as-is from LLM
        assert types["ramen"] == "preference"

    async def test_specific_edges_exist(self, nw_with_corpus):
        nw = nw_with_corpus
        edges = nw.graph.to_dict()["edges"]
        edge_set = {(e["source_id"], e["relation"], e["target_id"]) for e in edges}

        # Find node IDs by name
        id_map = {}
        for nid, data in nw.graph._graph.nodes(data=True):
            id_map[data["name"]] = nid

        assert (id_map["User"], "named", id_map["Alex"]) in edge_set
        assert (id_map["User"], "married_to", id_map["Lena"]) in edge_set
        assert (id_map["User"], "traveling_to", id_map["Tokyo"]) in edge_set
        assert (id_map["Lena"], "traveling_to", id_map["Tokyo"]) in edge_set
        assert (id_map["Lena"], "prefers", id_map["sushi"]) in edge_set
        assert (id_map["User"], "prefers", id_map["ramen"]) in edge_set
        assert (id_map["User"], "has_children", id_map["children"]) in edge_set
        assert (id_map["User"], "experienced_with", id_map["Python"]) in edge_set

    async def test_process_result_accumulation(self, nw):
        """Each message returns correct per-message delta."""
        r1 = await nw.process(CORPUS[0])  # Alex, User, sw_eng + 2 rels
        assert r1.entity_count == 3
        assert r1.relation_count == 2
        assert r1.nodes_added == 3
        assert r1.edges_added == 2

        r2 = await nw.process(CORPUS[1])  # User (exists), Lena, Tokyo + 3 rels
        assert r2.entity_count == 3
        assert r2.relation_count == 3
        assert r2.nodes_added == 2  # Lena, Tokyo (User already exists)
        assert r2.edges_added == 3


# ---------------------------------------------------------------------------
# NL queries — verify canonical questions return expected context
# ---------------------------------------------------------------------------


class TestNLQueries:
    async def test_wife_preferences(self, nw_with_corpus):
        result = await nw_with_corpus.query("what does my wife like?")

        node_names = result.node_names()
        assert "Lena" in node_names
        assert "sushi" in node_names
        assert result.edge_count >= 1
        assert all(e["relation"] == "prefers" for e in result.edges)

    async def test_travel_plans(self, nw_with_corpus):
        result = await nw_with_corpus.query("where are we traveling?")

        node_names = result.node_names()
        assert "User" in node_names
        assert "Tokyo" in node_names
        assert any(e["relation"] == "traveling_to" for e in result.edges)

    async def test_broad_user_query(self, nw_with_corpus):
        result = await nw_with_corpus.query("what do you know about me?")

        node_names = result.node_names()
        assert "User" in node_names
        # 2-hop from User should reach most of the graph
        assert result.node_count >= 7
        assert "Lena" in node_names
        assert "Tokyo" in node_names
        assert "Python" in node_names
        assert "ramen" in node_names

    async def test_tokyo_query(self, nw_with_corpus):
        result = await nw_with_corpus.query("tell me about tokyo")

        node_names = result.node_names()
        assert "Tokyo" in node_names
        # 2 hops from Tokyo → User → everything connected to User
        assert "User" in node_names
        assert "Lena" in node_names


# ---------------------------------------------------------------------------
# Structured queries
# ---------------------------------------------------------------------------


class TestStructuredQueries:
    async def test_single_entity(self, nw_with_corpus):
        result = await nw_with_corpus.query(["Lena"])
        assert "Lena" in result.node_names()
        assert result.node_count >= 3  # Lena + her 1-hop neighbors

    async def test_entity_with_relation_filter(self, nw_with_corpus):
        result = await nw_with_corpus.query(["Lena"], relations=["prefers"])
        assert "sushi" in result.node_names()
        assert all(e["relation"] == "prefers" for e in result.edges)

    async def test_multi_hop(self, nw_with_corpus):
        result = await nw_with_corpus.query(["sushi"], max_hops=2)
        # sushi → Lena → User, Tokyo
        assert "Lena" in result.node_names()
        assert "User" in result.node_names()

    async def test_whole_graph(self, nw_with_corpus):
        result = await nw_with_corpus.query()
        assert result.node_count == 9
        assert result.edge_count == 9

    async def test_confidence_filter(self, nw_with_corpus):
        high_conf = await nw_with_corpus.query(["User"], min_confidence=0.90)
        all_conf = await nw_with_corpus.query(["User"], min_confidence=0.0)
        # Higher confidence should return fewer or equal edges
        assert high_conf.edge_count <= all_conf.edge_count


# ---------------------------------------------------------------------------
# get_context (combined process + query)
# ---------------------------------------------------------------------------


class TestGetContext:
    async def test_get_context_returns_both(self, nw_with_corpus):
        context = await nw_with_corpus.get_context("She loves sushi but I prefer ramen.")
        assert isinstance(context, ContextResult)
        assert isinstance(context.process, ProcessResult)
        assert isinstance(context.relevant, QueryResult)

    async def test_get_context_query_uses_message(self, nw_with_corpus):
        """The NL query should use the same message text."""
        context = await nw_with_corpus.get_context("what does my wife like?")
        # The NL planner matches "wife" → Lena's preferences
        assert "Lena" in context.relevant.node_names()
        assert "sushi" in context.relevant.node_names()

    async def test_get_context_plan_is_present(self, nw_with_corpus):
        context = await nw_with_corpus.get_context("where are we traveling?")
        assert context.plan is not None
        assert context.plan.entities == ["User"]
        assert "traveling_to" in context.plan.relations

    async def test_get_context_serialization(self, nw_with_corpus):
        context = await nw_with_corpus.get_context("My name is Alex and I'm a software engineer.")
        d = context.to_dict()
        assert "process" in d
        assert "relevant" in d
        assert "plan" in d
        assert d["plan"] is not None


# ---------------------------------------------------------------------------
# Event flow
# ---------------------------------------------------------------------------


class TestEventFlow:
    async def test_events_fire_during_corpus_processing(self, nw):
        events: list[GraphEvent] = []

        async def handler(event: GraphEvent) -> None:
            events.append(event)

        nw.subscribe(handler)

        for msg in CORPUS:
            await nw.process(msg)

        await _drain()

        # 9 nodes + 9 edges = 18 total events (some may be updates if IDs collide)
        assert len(events) >= 18

        node_adds = [e for e in events if e.event_type == GraphEventType.NODE_ADDED]
        edge_adds = [e for e in events if e.event_type == GraphEventType.EDGE_ADDED]
        assert len(node_adds) >= 9
        assert len(edge_adds) >= 9

    async def test_filtered_events(self, nw):
        node_events: list[GraphEvent] = []
        edge_events: list[GraphEvent] = []

        async def node_handler(event: GraphEvent) -> None:
            node_events.append(event)

        async def edge_handler(event: GraphEvent) -> None:
            edge_events.append(event)

        nw.subscribe(node_handler, event_types={EventType.NODE_ADDED})
        nw.subscribe(edge_handler, event_types={EventType.EDGE_ADDED})

        await nw.process(CORPUS[0])
        await _drain()

        assert len(node_events) == 3  # User, Alex, software engineering
        assert len(edge_events) == 2  # named, occupation
        assert all(e.event_type == GraphEventType.NODE_ADDED for e in node_events)
        assert all(e.event_type == GraphEventType.EDGE_ADDED for e in edge_events)

    async def test_unsubscribe_stops_delivery(self, nw):
        events: list[GraphEvent] = []

        async def handler(event: GraphEvent) -> None:
            events.append(event)

        nw.subscribe(handler)
        await nw.process(CORPUS[0])
        await _drain()
        count_after_first = len(events)
        assert count_after_first > 0

        nw.unsubscribe(handler)
        await nw.process(CORPUS[1])
        await _drain()

        assert len(events) == count_after_first  # No new events


# ---------------------------------------------------------------------------
# Idempotency and re-processing
# ---------------------------------------------------------------------------


class TestIdempotency:
    async def test_reprocessing_same_message_deduplicates_nodes(self, nw):
        """Processing the same message twice deduplicates nodes by name."""
        r1 = await nw.process(CORPUS[0])
        r2 = await nw.process(CORPUS[0])

        # Second processing should add 0 new nodes (all exist by name)
        assert r2.nodes_added == 0
        # Graph should still have same node count
        assert nw.graph.node_count == 3

    async def test_no_node_events_on_reprocess(self, nw):
        """Re-processing skips existing nodes — no NODE events emitted.

        The ingest module detects existing nodes by name and reuses their
        IDs for edge creation, but does not call add_node() again.
        """
        await nw.process(CORPUS[0])
        await _drain()

        all_events: list[GraphEvent] = []

        async def handler(event: GraphEvent) -> None:
            all_events.append(event)

        nw.subscribe(handler)

        await nw.process(CORPUS[0])
        await _drain()

        node_events = [e for e in all_events if e.event_type in {
            GraphEventType.NODE_ADDED, GraphEventType.NODE_UPDATED,
        }]
        # Existing nodes are silently skipped — no add or update events
        assert len(node_events) == 0

        # But edges DO get added (new IDs each time)
        edge_events = [e for e in all_events if e.event_type == GraphEventType.EDGE_ADDED]
        assert len(edge_events) == 2

    async def test_edges_are_added_not_updated_on_reprocess(self, nw):
        """Edges get new IDs each time, so re-processing adds new edges.

        This is a known limitation: edge dedup by content isn't implemented
        yet. For now, edges accumulate on re-processing.
        """
        r1 = await nw.process(CORPUS[0])
        assert r1.edges_added == 2

        r2 = await nw.process(CORPUS[0])
        # Edges are added again (new IDs generated each time)
        assert r2.edges_added == 2
        # Total edges = 4 (2 original + 2 duplicates)
        assert nw.graph.edge_count == 4


# ---------------------------------------------------------------------------
# Full lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    async def test_full_lifecycle(self):
        """Complete lifecycle: create → start → process → query → stop."""
        mock_llm = _build_corpus_mock()
        nw = NeuroWeave(llm_provider="mock", log_level="WARNING")

        await nw.start()
        nw._pipeline = ExtractionPipeline(mock_llm)
        nw._nl_planner = NLQueryPlanner(mock_llm, nw.graph)

        # Build graph
        for msg in CORPUS:
            await nw.process(msg)

        # Query
        result = await nw.query("what does my wife like?")
        assert "sushi" in result.node_names()

        # Stop
        await nw.stop()
        assert not nw.is_started

    async def test_context_manager_lifecycle(self):
        """Same lifecycle but with async context manager."""
        mock_llm = _build_corpus_mock()

        async with NeuroWeave(llm_provider="mock", log_level="WARNING") as nw:
            nw._pipeline = ExtractionPipeline(mock_llm)
            nw._nl_planner = NLQueryPlanner(mock_llm, nw.graph)

            for msg in CORPUS:
                await nw.process(msg)

            result = await nw.query(["User"], max_hops=2)
            assert result.node_count >= 7


# ---------------------------------------------------------------------------
# Demo agent smoke test
# ---------------------------------------------------------------------------


class TestDemoAgent:
    async def test_demo_runs_without_error(self):
        """Import and run the demo agent's run_demo function."""
        import sys
        from pathlib import Path

        examples_dir = str(Path(__file__).resolve().parent.parent / "examples")
        if examples_dir not in sys.path:
            sys.path.insert(0, examples_dir)

        from demo_agent import run_demo

        # Should complete without raising
        await run_demo("mock")
