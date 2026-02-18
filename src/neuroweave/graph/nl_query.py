"""Natural language query planner for the knowledge graph.

Translates free-text questions like "what does my wife like?" into structured
query plans that can be executed by `query_subgraph()`.

This is the "Tier 2" query path — uses an LLM to interpret the question
against the current graph schema, then delegates to the deterministic
structured query engine (Tier 1) for execution.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from neuroweave.extraction.llm_client import LLMClient, LLMError
from neuroweave.extraction.pipeline import repair_llm_json
from neuroweave.graph.query import QueryResult, query_subgraph
from neuroweave.graph.store import GraphStore
from neuroweave.logging import get_logger

log = get_logger("nl_query")


# ---------------------------------------------------------------------------
# Query plan — the bridge between NL and structured query
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QueryPlan:
    """A structured query plan produced by the NL planner.

    This maps directly to the parameters of `query_subgraph()`.

    Attributes:
        entities: Entity names to start traversal from.
        relations: Relation types to filter on (None = all).
        min_confidence: Minimum edge confidence threshold.
        max_hops: How many hops to traverse from seed entities.
        reasoning: LLM's brief explanation of its interpretation.
        raw_response: The raw LLM output (for debugging).
        duration_ms: Time taken for the LLM call.
    """

    entities: list[str] = field(default_factory=list)
    relations: list[str] | None = None
    min_confidence: float = 0.0
    max_hops: int = 1
    reasoning: str = ""
    raw_response: str = ""
    duration_ms: float = 0.0

    @property
    def is_broad_search(self) -> bool:
        """True if this plan has no entity filter (whole-graph search)."""
        return len(self.entities) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "entities": self.entities,
            "relations": self.relations,
            "min_confidence": self.min_confidence,
            "max_hops": self.max_hops,
            "reasoning": self.reasoning,
        }


# ---------------------------------------------------------------------------
# System prompt template
# ---------------------------------------------------------------------------

_NL_QUERY_SYSTEM_PROMPT = """\
You are a query planner for a knowledge graph. Your task is to translate a \
natural language question into a structured graph query.

The knowledge graph contains these ENTITIES (nodes):
{entity_list}

The graph has these RELATION TYPES (edges):
{relation_list}

RULES:
- Identify which entities in the graph are relevant to the question.
- Identify which relation types would help answer the question.
- Choose how many hops to traverse (1 = direct connections, 2 = friends-of-friends, etc.)
- If the question mentions a person by relationship (e.g. "my wife"), resolve it \
to the actual entity name from the graph.
- If the question is very broad or you can't identify specific entities, return \
an empty entities list (this triggers a whole-graph search).
- If no specific relation types are needed, set relations to null.

Respond with ONLY valid JSON in this exact format, no other text:

{{
  "entities": ["entity_name1", "entity_name2"],
  "relations": ["relation_type1", "relation_type2"],
  "min_confidence": 0.0,
  "max_hops": 1,
  "reasoning": "Brief explanation of your interpretation"
}}

Examples:
- "what does my wife like?" → {{"entities": ["Lena"], "relations": ["prefers", "likes"], "max_hops": 1, "min_confidence": 0.0, "reasoning": "User's wife is Lena, looking for her preferences"}}
- "where are we traveling?" → {{"entities": ["User"], "relations": ["traveling_to"], "max_hops": 1, "min_confidence": 0.0, "reasoning": "Looking for travel plans connected to the user"}}
- "tell me everything about Tokyo" → {{"entities": ["Tokyo"], "relations": null, "max_hops": 2, "min_confidence": 0.0, "reasoning": "Broad query about Tokyo, get all connections"}}
- "what do you know about me?" → {{"entities": ["User"], "relations": null, "max_hops": 2, "min_confidence": 0.0, "reasoning": "Broad user query, return full user context"}}
"""


# ---------------------------------------------------------------------------
# NL Query Planner
# ---------------------------------------------------------------------------


class NLQueryPlanner:
    """Translates natural language questions into structured graph queries.

    Uses an LLM to interpret the question against the current graph schema,
    producing a `QueryPlan` that maps to `query_subgraph()` parameters.

    Falls back to a broad whole-graph search if the LLM response is
    unparseable or the call fails.

    Usage:
        planner = NLQueryPlanner(llm_client, graph_store)
        plan = await planner.plan("what does my wife like?")
        result = planner.execute(plan)
    """

    def __init__(self, llm_client: LLMClient, store: GraphStore) -> None:
        self._llm = llm_client
        self._store = store

    async def plan(self, question: str) -> QueryPlan:
        """Translate a natural language question into a QueryPlan.

        Args:
            question: Free-text question about the knowledge graph.

        Returns:
            QueryPlan ready for execution. On LLM failure, returns a
            broad fallback plan (whole-graph search).
        """
        log.info("nl_query.plan_start", question=question[:100])
        start = time.monotonic()

        system_prompt = self._build_system_prompt()

        try:
            raw_response = await self._llm.extract(system_prompt, question)
        except LLMError as e:
            log.error("nl_query.llm_error", error=str(e))
            return self._fallback_plan(question, duration_ms=_elapsed_ms(start))

        plan = self._parse_plan(raw_response, duration_ms=_elapsed_ms(start))

        log.info(
            "nl_query.plan_complete",
            entities=plan.entities,
            relations=plan.relations,
            max_hops=plan.max_hops,
            is_broad=plan.is_broad_search,
            duration_ms=round(plan.duration_ms, 1),
        )

        return plan

    def execute(self, plan: QueryPlan) -> QueryResult:
        """Execute a QueryPlan against the graph store.

        This is a thin wrapper around `query_subgraph()` that maps
        the plan's fields to the function's parameters.

        Args:
            plan: A QueryPlan from `plan()`.

        Returns:
            QueryResult from the structured query engine.
        """
        return query_subgraph(
            self._store,
            entities=plan.entities if plan.entities else None,
            relations=plan.relations,
            min_confidence=plan.min_confidence,
            max_hops=plan.max_hops,
        )

    async def query(self, question: str) -> QueryResult:
        """Convenience: plan + execute in one call.

        Args:
            question: Natural language question.

        Returns:
            QueryResult from executing the generated plan.
        """
        plan = await self.plan(question)
        return self.execute(plan)

    # -- Internal -----------------------------------------------------------

    def _build_system_prompt(self) -> str:
        """Build the system prompt with current graph schema context."""
        # Collect entity names and types
        entities = []
        for nid, data in self._store._graph.nodes(data=True):
            name = data.get("name", nid)
            node_type = data.get("node_type", "unknown")
            entities.append(f"  - {name} ({node_type})")

        # Collect unique relation types
        relation_types: set[str] = set()
        for _, _, data in self._store._graph.edges(data=True):
            rel = data.get("relation")
            if rel:
                relation_types.add(rel)

        entity_list = "\n".join(entities) if entities else "  (graph is empty)"
        relation_list = "\n".join(f"  - {r}" for r in sorted(relation_types)) if relation_types else "  (no relations yet)"

        return _NL_QUERY_SYSTEM_PROMPT.format(
            entity_list=entity_list,
            relation_list=relation_list,
        )

    def _parse_plan(self, raw_response: str, *, duration_ms: float) -> QueryPlan:
        """Parse the LLM response into a QueryPlan.

        Falls back to a broad search if parsing fails.
        """
        parsed = repair_llm_json(raw_response)
        if parsed is None or not isinstance(parsed, dict):
            log.warning("nl_query.parse_failed", raw_response=raw_response[:200])
            return self._fallback_plan(raw_response=raw_response, duration_ms=duration_ms)

        # Extract fields with safe defaults
        entities = parsed.get("entities", [])
        if not isinstance(entities, list):
            entities = []
        entities = [str(e) for e in entities if e]

        relations = parsed.get("relations")
        if isinstance(relations, list):
            relations = [str(r) for r in relations if r]
            if not relations:
                relations = None
        else:
            relations = None

        min_confidence = parsed.get("min_confidence", 0.0)
        if not isinstance(min_confidence, (int, float)):
            min_confidence = 0.0
        min_confidence = max(0.0, min(1.0, float(min_confidence)))

        max_hops = parsed.get("max_hops", 1)
        if not isinstance(max_hops, int):
            try:
                max_hops = int(max_hops)
            except (TypeError, ValueError):
                max_hops = 1
        max_hops = max(0, min(10, max_hops))

        reasoning = parsed.get("reasoning", "")
        if not isinstance(reasoning, str):
            reasoning = ""

        return QueryPlan(
            entities=entities,
            relations=relations,
            min_confidence=min_confidence,
            max_hops=max_hops,
            reasoning=reasoning,
            raw_response=raw_response,
            duration_ms=duration_ms,
        )

    def _fallback_plan(
        self,
        raw_response: str = "",
        *,
        duration_ms: float = 0.0,
    ) -> QueryPlan:
        """Return a broad fallback plan when LLM parsing fails.

        The fallback does a whole-graph search with 2 hops — the safest
        strategy when we can't understand the question.
        """
        log.info("nl_query.fallback")
        return QueryPlan(
            entities=[],
            relations=None,
            min_confidence=0.0,
            max_hops=2,
            reasoning="Fallback: could not parse LLM response, returning broad search.",
            raw_response=raw_response,
            duration_ms=duration_ms,
        )


def _elapsed_ms(start: float) -> float:
    return (time.monotonic() - start) * 1000
