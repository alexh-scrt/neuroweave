"""Tests for the natural language query planner."""

from __future__ import annotations

import json

import pytest

from neuroweave.extraction.llm_client import MockLLMClient
from neuroweave.graph.nl_query import NLQueryPlanner, QueryPlan
from neuroweave.graph.store import GraphStore, NodeType, make_edge, make_node


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store() -> GraphStore:
    return GraphStore()


@pytest.fixture
def family_graph(store: GraphStore) -> GraphStore:
    """Same graph as test_query.py — the 5-message conversation corpus."""
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


def _make_mock_llm(**query_responses: dict) -> MockLLMClient:
    """Create a MockLLMClient with canned NL query planner responses.

    Each kwarg key is a substring to match in the question, and the value
    is the JSON response dict the LLM should return.
    """
    mock = MockLLMClient()
    for substring, response in query_responses.items():
        mock.set_response(substring, response)
    return mock


# ---------------------------------------------------------------------------
# QueryPlan dataclass
# ---------------------------------------------------------------------------


class TestQueryPlan:
    def test_default_plan(self):
        plan = QueryPlan()
        assert plan.entities == []
        assert plan.relations is None
        assert plan.min_confidence == 0.0
        assert plan.max_hops == 1
        assert plan.is_broad_search

    def test_plan_with_entities(self):
        plan = QueryPlan(entities=["Lena"], relations=["prefers"], max_hops=1)
        assert not plan.is_broad_search
        assert plan.entities == ["Lena"]

    def test_to_dict(self):
        plan = QueryPlan(
            entities=["Lena"],
            relations=["prefers"],
            max_hops=1,
            reasoning="Looking for Lena's preferences",
        )
        d = plan.to_dict()
        assert d["entities"] == ["Lena"]
        assert d["relations"] == ["prefers"]
        assert d["max_hops"] == 1
        assert "Looking for" in d["reasoning"]

    def test_is_broad_search_with_empty_entities(self):
        assert QueryPlan(entities=[]).is_broad_search

    def test_is_not_broad_with_entities(self):
        assert not QueryPlan(entities=["User"]).is_broad_search


# ---------------------------------------------------------------------------
# System prompt construction
# ---------------------------------------------------------------------------


class TestSystemPrompt:
    def test_prompt_includes_entity_names(self, family_graph: GraphStore):
        mock_llm = _make_mock_llm()
        planner = NLQueryPlanner(mock_llm, family_graph)
        prompt = planner._build_system_prompt()

        assert "User" in prompt
        assert "Lena" in prompt
        assert "Tokyo" in prompt
        assert "Python" in prompt
        assert "sushi" in prompt

    def test_prompt_includes_relation_types(self, family_graph: GraphStore):
        mock_llm = _make_mock_llm()
        planner = NLQueryPlanner(mock_llm, family_graph)
        prompt = planner._build_system_prompt()

        assert "married_to" in prompt
        assert "prefers" in prompt
        assert "traveling_to" in prompt
        assert "experienced_with" in prompt

    def test_prompt_includes_node_types(self, family_graph: GraphStore):
        mock_llm = _make_mock_llm()
        planner = NLQueryPlanner(mock_llm, family_graph)
        prompt = planner._build_system_prompt()

        assert "entity" in prompt
        assert "concept" in prompt

    def test_prompt_for_empty_graph(self, store: GraphStore):
        mock_llm = _make_mock_llm()
        planner = NLQueryPlanner(mock_llm, store)
        prompt = planner._build_system_prompt()

        assert "graph is empty" in prompt
        assert "no relations yet" in prompt

    async def test_llm_receives_system_prompt(self, family_graph: GraphStore):
        """Verify the system prompt is passed to the LLM extract call."""
        mock_llm = _make_mock_llm(
            anything={"entities": [], "relations": None, "max_hops": 1, "reasoning": "test"},
        )
        planner = NLQueryPlanner(mock_llm, family_graph)

        await planner.plan("anything")

        assert "ENTITIES" in mock_llm.last_system_prompt
        assert "RELATION TYPES" in mock_llm.last_system_prompt
        assert "Lena" in mock_llm.last_system_prompt


# ---------------------------------------------------------------------------
# Core NL→Plan translation
# ---------------------------------------------------------------------------


class TestPlanGeneration:
    async def test_wife_preferences(self, family_graph: GraphStore):
        """The canonical query: 'what does my wife like?'"""
        mock_llm = _make_mock_llm(
            wife={
                "entities": ["Lena"],
                "relations": ["prefers", "likes"],
                "max_hops": 1,
                "min_confidence": 0.0,
                "reasoning": "User's wife is Lena, looking for her preferences",
            },
        )
        planner = NLQueryPlanner(mock_llm, family_graph)
        plan = await planner.plan("what does my wife like?")

        assert plan.entities == ["Lena"]
        assert "prefers" in plan.relations
        assert plan.max_hops == 1
        assert not plan.is_broad_search
        assert "Lena" in plan.reasoning

    async def test_travel_plans(self, family_graph: GraphStore):
        """'where are we traveling?'"""
        mock_llm = _make_mock_llm(
            traveling={
                "entities": ["User"],
                "relations": ["traveling_to"],
                "max_hops": 1,
                "min_confidence": 0.0,
                "reasoning": "Looking for travel plans connected to the user",
            },
        )
        planner = NLQueryPlanner(mock_llm, family_graph)
        plan = await planner.plan("where are we traveling?")

        assert plan.entities == ["User"]
        assert plan.relations == ["traveling_to"]
        assert plan.max_hops == 1

    async def test_broad_user_query(self, family_graph: GraphStore):
        """'what do you know about me?'"""
        mock_llm = _make_mock_llm(
            know={
                "entities": ["User"],
                "relations": None,
                "max_hops": 2,
                "min_confidence": 0.0,
                "reasoning": "Broad user query, return full user context",
            },
        )
        planner = NLQueryPlanner(mock_llm, family_graph)
        plan = await planner.plan("what do you know about me?")

        assert plan.entities == ["User"]
        assert plan.relations is None
        assert plan.max_hops == 2

    async def test_specific_entity_query(self, family_graph: GraphStore):
        """'tell me about Tokyo'"""
        mock_llm = _make_mock_llm(
            tokyo={
                "entities": ["Tokyo"],
                "relations": None,
                "max_hops": 2,
                "min_confidence": 0.0,
                "reasoning": "Everything about Tokyo",
            },
        )
        planner = NLQueryPlanner(mock_llm, family_graph)
        plan = await planner.plan("tell me about Tokyo")

        assert plan.entities == ["Tokyo"]
        assert plan.relations is None
        assert plan.max_hops == 2

    async def test_plan_records_duration(self, family_graph: GraphStore):
        mock_llm = _make_mock_llm(
            test={
                "entities": ["User"],
                "relations": None,
                "max_hops": 1,
                "reasoning": "test",
            },
        )
        planner = NLQueryPlanner(mock_llm, family_graph)
        plan = await planner.plan("test question")

        assert plan.duration_ms >= 0.0

    async def test_plan_records_raw_response(self, family_graph: GraphStore):
        mock_llm = _make_mock_llm(
            test={
                "entities": ["User"],
                "relations": None,
                "max_hops": 1,
                "reasoning": "test",
            },
        )
        planner = NLQueryPlanner(mock_llm, family_graph)
        plan = await planner.plan("test question")

        assert plan.raw_response  # Should be non-empty
        assert "User" in plan.raw_response


# ---------------------------------------------------------------------------
# Plan execution
# ---------------------------------------------------------------------------


class TestPlanExecution:
    async def test_execute_wife_preferences(self, family_graph: GraphStore):
        """End-to-end: NL question → plan → query result."""
        mock_llm = _make_mock_llm(
            wife={
                "entities": ["Lena"],
                "relations": ["prefers"],
                "max_hops": 1,
                "min_confidence": 0.0,
                "reasoning": "Wife is Lena, looking for preferences",
            },
        )
        planner = NLQueryPlanner(mock_llm, family_graph)
        plan = await planner.plan("what does my wife like?")
        result = planner.execute(plan)

        assert "sushi" in result.node_names()
        assert "Lena" in result.node_names()
        assert result.edge_count >= 1
        assert all(e["relation"] == "prefers" for e in result.edges)

    async def test_execute_travel(self, family_graph: GraphStore):
        mock_llm = _make_mock_llm(
            traveling={
                "entities": ["User"],
                "relations": ["traveling_to"],
                "max_hops": 1,
                "min_confidence": 0.0,
                "reasoning": "Travel plans",
            },
        )
        planner = NLQueryPlanner(mock_llm, family_graph)
        plan = await planner.plan("where are we traveling?")
        result = planner.execute(plan)

        assert "Tokyo" in result.node_names()
        assert any(e["relation"] == "traveling_to" for e in result.edges)

    async def test_execute_broad_query(self, family_graph: GraphStore):
        mock_llm = _make_mock_llm(
            know={
                "entities": ["User"],
                "relations": None,
                "max_hops": 2,
                "min_confidence": 0.0,
                "reasoning": "Broad query",
            },
        )
        planner = NLQueryPlanner(mock_llm, family_graph)
        plan = await planner.plan("what do you know about me?")
        result = planner.execute(plan)

        # 2 hops from User should reach most of the graph
        assert result.node_count >= 7
        assert "Lena" in result.node_names()
        assert "Tokyo" in result.node_names()
        assert "Python" in result.node_names()

    async def test_convenience_query_method(self, family_graph: GraphStore):
        """Test the combined plan+execute `query()` method."""
        mock_llm = _make_mock_llm(
            wife={
                "entities": ["Lena"],
                "relations": ["prefers"],
                "max_hops": 1,
                "min_confidence": 0.0,
                "reasoning": "Wife preferences",
            },
        )
        planner = NLQueryPlanner(mock_llm, family_graph)
        result = await planner.query("what does my wife like?")

        assert "sushi" in result.node_names()
        assert "Lena" in result.node_names()


# ---------------------------------------------------------------------------
# Fallback behavior
# ---------------------------------------------------------------------------


class TestFallback:
    async def test_fallback_on_unparseable_response(self, family_graph: GraphStore):
        """LLM returns garbage → falls back to broad whole-graph search."""
        mock_llm = MockLLMClient()
        mock_llm.set_response("anything", "this is not json at all")
        # Override extract to return raw string
        original_extract = mock_llm.extract

        async def bad_extract(system_prompt: str, user_message: str) -> str:
            return "this is definitely not json"

        mock_llm.extract = bad_extract  # type: ignore

        planner = NLQueryPlanner(mock_llm, family_graph)
        plan = await planner.plan("anything at all")

        assert plan.is_broad_search
        assert plan.max_hops == 2
        assert "Fallback" in plan.reasoning

    async def test_fallback_on_llm_error(self, family_graph: GraphStore):
        """LLM raises an error → falls back to broad search."""
        mock_llm = MockLLMClient()

        async def failing_extract(system_prompt: str, user_message: str) -> str:
            from neuroweave.extraction.llm_client import LLMError
            raise LLMError("API rate limit exceeded")

        mock_llm.extract = failing_extract  # type: ignore

        planner = NLQueryPlanner(mock_llm, family_graph)
        plan = await planner.plan("what does my wife like?")

        assert plan.is_broad_search
        assert plan.max_hops == 2

    async def test_fallback_still_returns_results(self, family_graph: GraphStore):
        """Even the fallback plan should return useful graph data."""
        mock_llm = MockLLMClient()

        async def failing_extract(system_prompt: str, user_message: str) -> str:
            from neuroweave.extraction.llm_client import LLMError
            raise LLMError("fail")

        mock_llm.extract = failing_extract  # type: ignore

        planner = NLQueryPlanner(mock_llm, family_graph)
        plan = await planner.plan("anything")
        result = planner.execute(plan)

        # Broad search should return the whole graph
        assert result.node_count == 9
        assert result.edge_count == 9

    async def test_fallback_on_empty_json(self, family_graph: GraphStore):
        """LLM returns empty JSON object → fallback."""
        mock_llm = MockLLMClient()

        async def empty_json(system_prompt: str, user_message: str) -> str:
            return "{}"

        mock_llm.extract = empty_json  # type: ignore

        planner = NLQueryPlanner(mock_llm, family_graph)
        plan = await planner.plan("some question")

        # {} is parseable but has no entities → broad search
        assert plan.is_broad_search
        assert plan.max_hops == 1  # default from parsed empty, not fallback

    async def test_fallback_on_partial_json(self, family_graph: GraphStore):
        """LLM returns partial JSON → repair + use what we can."""
        mock_llm = MockLLMClient()

        async def partial_json(system_prompt: str, user_message: str) -> str:
            return '{"entities": ["Lena"], "relations": ["prefers"]}'

        mock_llm.extract = partial_json  # type: ignore

        planner = NLQueryPlanner(mock_llm, family_graph)
        plan = await planner.plan("wife preferences")

        # Should parse successfully despite missing fields
        assert plan.entities == ["Lena"]
        assert plan.relations == ["prefers"]
        assert plan.max_hops == 1  # default


# ---------------------------------------------------------------------------
# Defensive parsing edge cases
# ---------------------------------------------------------------------------


class TestParsing:
    async def test_entities_as_non_list(self, family_graph: GraphStore):
        """entities is a string instead of list → treat as empty."""
        mock_llm = MockLLMClient()

        async def bad_entities(system_prompt: str, user_message: str) -> str:
            return json.dumps({"entities": "Lena", "relations": None, "max_hops": 1})

        mock_llm.extract = bad_entities  # type: ignore

        planner = NLQueryPlanner(mock_llm, family_graph)
        plan = await planner.plan("test")
        assert plan.entities == []

    async def test_relations_as_empty_list(self, family_graph: GraphStore):
        """relations is [] → treat as None (no filter)."""
        mock_llm = MockLLMClient()

        async def empty_relations(system_prompt: str, user_message: str) -> str:
            return json.dumps({"entities": ["User"], "relations": [], "max_hops": 1})

        mock_llm.extract = empty_relations  # type: ignore

        planner = NLQueryPlanner(mock_llm, family_graph)
        plan = await planner.plan("test")
        assert plan.relations is None

    async def test_max_hops_clamped_to_range(self, family_graph: GraphStore):
        """max_hops > 10 gets clamped."""
        mock_llm = MockLLMClient()

        async def big_hops(system_prompt: str, user_message: str) -> str:
            return json.dumps({"entities": ["User"], "max_hops": 999})

        mock_llm.extract = big_hops  # type: ignore

        planner = NLQueryPlanner(mock_llm, family_graph)
        plan = await planner.plan("test")
        assert plan.max_hops == 10

    async def test_negative_max_hops_clamped(self, family_graph: GraphStore):
        mock_llm = MockLLMClient()

        async def neg_hops(system_prompt: str, user_message: str) -> str:
            return json.dumps({"entities": ["User"], "max_hops": -5})

        mock_llm.extract = neg_hops  # type: ignore

        planner = NLQueryPlanner(mock_llm, family_graph)
        plan = await planner.plan("test")
        assert plan.max_hops == 0

    async def test_confidence_clamped(self, family_graph: GraphStore):
        mock_llm = MockLLMClient()

        async def high_conf(system_prompt: str, user_message: str) -> str:
            return json.dumps({"entities": ["User"], "min_confidence": 5.0})

        mock_llm.extract = high_conf  # type: ignore

        planner = NLQueryPlanner(mock_llm, family_graph)
        plan = await planner.plan("test")
        assert plan.min_confidence == 1.0

    async def test_confidence_negative_clamped(self, family_graph: GraphStore):
        mock_llm = MockLLMClient()

        async def neg_conf(system_prompt: str, user_message: str) -> str:
            return json.dumps({"entities": ["User"], "min_confidence": -0.5})

        mock_llm.extract = neg_conf  # type: ignore

        planner = NLQueryPlanner(mock_llm, family_graph)
        plan = await planner.plan("test")
        assert plan.min_confidence == 0.0

    async def test_max_hops_as_string(self, family_graph: GraphStore):
        """max_hops comes back as string → parse to int."""
        mock_llm = MockLLMClient()

        async def str_hops(system_prompt: str, user_message: str) -> str:
            return json.dumps({"entities": ["User"], "max_hops": "2"})

        mock_llm.extract = str_hops  # type: ignore

        planner = NLQueryPlanner(mock_llm, family_graph)
        plan = await planner.plan("test")
        assert plan.max_hops == 2

    async def test_reasoning_as_non_string(self, family_graph: GraphStore):
        mock_llm = MockLLMClient()

        async def int_reasoning(system_prompt: str, user_message: str) -> str:
            return json.dumps({"entities": ["User"], "reasoning": 42})

        mock_llm.extract = int_reasoning  # type: ignore

        planner = NLQueryPlanner(mock_llm, family_graph)
        plan = await planner.plan("test")
        assert plan.reasoning == ""

    async def test_json_with_markdown_fences(self, family_graph: GraphStore):
        """LLM wraps response in ```json ... ``` fences."""
        mock_llm = MockLLMClient()

        async def fenced_json(system_prompt: str, user_message: str) -> str:
            return '```json\n{"entities": ["Lena"], "relations": ["prefers"], "max_hops": 1}\n```'

        mock_llm.extract = fenced_json  # type: ignore

        planner = NLQueryPlanner(mock_llm, family_graph)
        plan = await planner.plan("wife preferences")
        assert plan.entities == ["Lena"]
        assert plan.relations == ["prefers"]

    async def test_json_with_preamble(self, family_graph: GraphStore):
        """LLM adds explanation before the JSON."""
        mock_llm = MockLLMClient()

        async def preamble_json(system_prompt: str, user_message: str) -> str:
            return 'Here is the query plan:\n{"entities": ["Tokyo"], "relations": null, "max_hops": 2}'

        mock_llm.extract = preamble_json  # type: ignore

        planner = NLQueryPlanner(mock_llm, family_graph)
        plan = await planner.plan("tell me about Tokyo")
        assert plan.entities == ["Tokyo"]
        assert plan.relations is None

    async def test_null_entities_in_json(self, family_graph: GraphStore):
        """entities is null → treat as empty list."""
        mock_llm = MockLLMClient()

        async def null_entities(system_prompt: str, user_message: str) -> str:
            return '{"entities": null, "relations": null, "max_hops": 1}'

        mock_llm.extract = null_entities  # type: ignore

        planner = NLQueryPlanner(mock_llm, family_graph)
        plan = await planner.plan("test")
        assert plan.entities == []
        assert plan.is_broad_search


# ---------------------------------------------------------------------------
# Empty graph behavior
# ---------------------------------------------------------------------------


class TestEmptyGraph:
    async def test_plan_on_empty_graph(self, store: GraphStore):
        """NL query on empty graph still works — returns empty result."""
        mock_llm = _make_mock_llm(
            anything={
                "entities": [],
                "relations": None,
                "max_hops": 1,
                "reasoning": "Graph is empty",
            },
        )
        planner = NLQueryPlanner(mock_llm, store)
        result = await planner.query("what do you know?")
        assert result.is_empty

    async def test_system_prompt_mentions_empty(self, store: GraphStore):
        mock_llm = _make_mock_llm()
        planner = NLQueryPlanner(mock_llm, store)
        prompt = planner._build_system_prompt()
        assert "graph is empty" in prompt
