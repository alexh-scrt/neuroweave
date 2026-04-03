# NeuroWeave — Technical Requirements
## Implementation Spec for Claude Code

**Target repo:** `https://github.com/alexh-scrt/neuroweave`  
**Base version:** v0.1.0 (Phase 1 complete — 308 tests passing)  
**Python:** 3.11+  
**All 308 existing tests must remain green after every change.**

---

## How to read this document

Each requirement block contains:
- **Exact file paths** to create or modify
- **Exact signatures** with types — implement verbatim
- **Behaviour contract** — invariants that must hold
- **Tests to write** — file + function names
- **pyproject.toml changes** — exact dependency strings

Do not rename, move, or restructure existing files unless the requirement explicitly says so. The existing `NeuroWeave` facade API (`process`, `query`, `get_context`) must remain unchanged.

---

## NW-001 — Persistent Graph Backend (Neo4j)

**Priority:** Critical — blocks all production use  
**Rationale:** NetworkX in-memory is wiped on every restart. AC1-LLM's cumulative identity requires a graph that survives indefinitely across restarts, deployments, and crashes.

### Architecture

Introduce a `GraphStore` abstract base class. The existing `GraphStore` class becomes `MemoryGraphStore`. A new `Neo4jGraphStore` class implements the same interface. The config key `graph_backend` selects which implementation is used.

### New files to create

#### `src/neuroweave/graph/backends/__init__.py` — create new

```python
"""Graph storage backend implementations."""
from neuroweave.graph.backends.base import AbstractGraphStore
from neuroweave.graph.backends.memory import MemoryGraphStore
from neuroweave.graph.backends.neo4j import Neo4jGraphStore

__all__ = ["AbstractGraphStore", "MemoryGraphStore", "Neo4jGraphStore"]
```

#### `src/neuroweave/graph/backends/base.py` — create new

Extract the public interface from the existing `GraphStore` into a protocol/ABC:

```python
"""Abstract base for all graph storage backends."""
from __future__ import annotations

import abc
from typing import Any

from neuroweave.graph.store import Edge, GraphEvent, Node


class AbstractGraphStore(abc.ABC):
    """Interface contract for all NeuroWeave graph backends.

    Implementations must be thread-safe for concurrent reads during
    single-writer access from the main thread.
    """

    @abc.abstractmethod
    def set_event_queue(self, q: Any) -> None:
        """Attach an event queue. Events are pushed here on mutations."""
        ...

    @abc.abstractmethod
    def add_node(self, node: Node) -> Node:
        """Add a node. Returns the node (possibly with db-assigned id)."""
        ...

    @abc.abstractmethod
    def get_node(self, node_id: str) -> dict[str, Any] | None:
        """Return node dict by id, or None if not found."""
        ...

    @abc.abstractmethod
    def find_nodes(
        self,
        node_type: str | None = None,
        name_contains: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return all nodes matching the given filters."""
        ...

    @abc.abstractmethod
    def add_edge(self, edge: Edge) -> Edge:
        """Add a directed edge. Returns the edge."""
        ...

    @abc.abstractmethod
    def get_edges(
        self,
        source_id: str | None = None,
        target_id: str | None = None,
        relation: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return edges matching any combination of source, target, relation."""
        ...

    @abc.abstractmethod
    def get_neighbors(self, node_id: str, depth: int = 1) -> list[dict[str, Any]]:
        """Return all nodes within `depth` hops of node_id via BFS."""
        ...

    @abc.abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Full serialization: {"nodes": [...], "edges": [...], "stats": {...}}."""
        ...

    @property
    @abc.abstractmethod
    def node_count(self) -> int: ...

    @property
    @abc.abstractmethod
    def edge_count(self) -> int: ...
```

#### `src/neuroweave/graph/backends/memory.py` — create new

Move the existing `GraphStore` implementation here, renaming the class to `MemoryGraphStore` and making it extend `AbstractGraphStore`. The existing `src/neuroweave/graph/store.py` must be updated to re-export `MemoryGraphStore` as `GraphStore` for backward compatibility:

```python
# src/neuroweave/graph/store.py — add at bottom for backward compat
from neuroweave.graph.backends.memory import MemoryGraphStore as GraphStore
```

No other changes to `store.py` — all existing tests import `GraphStore` from `neuroweave.graph.store` and must continue to work.

#### `src/neuroweave/graph/backends/neo4j.py` — create new

```python
"""Neo4j graph backend for persistent storage."""
from __future__ import annotations

import queue
import threading
from typing import Any

from neuroweave.graph.backends.base import AbstractGraphStore
from neuroweave.graph.store import Edge, GraphEvent, GraphEventType, Node


class Neo4jGraphStore(AbstractGraphStore):
    """Persistent graph backend backed by Neo4j.

    Requires: neo4j>=5.0 (pip install neo4j)
    Config keys:
        neo4j_uri:      str  — "neo4j://localhost:7687"
        neo4j_user:     str  — "neo4j"
        neo4j_password: str  — ""
        neo4j_database: str  — "neo4j"  (default)
    """

    def __init__(
        self,
        uri: str = "neo4j://localhost:7687",
        user: str = "neo4j",
        password: str = "",
        database: str = "neo4j",
    ) -> None:
        from neo4j import AsyncGraphDatabase  # deferred import
        self._driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
        self._database = database
        self._event_queue: queue.Queue[GraphEvent] | None = None
        self._lock = threading.Lock()
        self._node_count: int = 0
        self._edge_count: int = 0

    def set_event_queue(self, q: queue.Queue[GraphEvent]) -> None:  # type: ignore[type-arg]
        self._event_queue = q

    def _emit(self, event: GraphEvent) -> None:
        if self._event_queue is not None:
            try:
                self._event_queue.put_nowait(event)
            except queue.Full:
                pass

    def add_node(self, node: Node) -> Node:
        """Upsert a node by id using MERGE. Thread-safe."""
        import asyncio
        asyncio.get_event_loop().run_until_complete(self._async_add_node(node))
        return node

    async def _async_add_node(self, node: Node) -> None:
        async with self._driver.session(database=self._database) as session:
            result = await session.run(
                """
                MERGE (n:NWNode {id: $id})
                ON CREATE SET
                    n.name = $name,
                    n.node_type = $node_type,
                    n.created_at = $created_at,
                    n.properties = $properties
                RETURN n.id AS id, count(*) AS created
                """,
                id=node.id,
                name=node.name,
                node_type=node.node_type.value,
                created_at=node.created_at,
                properties=str(node.properties),
            )
            record = await result.single()
            if record and record["created"]:
                with self._lock:
                    self._node_count += 1
                self._emit(GraphEvent(
                    event_type=GraphEventType.NODE_ADDED,
                    data={"id": node.id, "name": node.name, "node_type": node.node_type.value},
                ))

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(self._async_get_node(node_id))

    async def _async_get_node(self, node_id: str) -> dict[str, Any] | None:
        async with self._driver.session(database=self._database) as session:
            result = await session.run(
                "MATCH (n:NWNode {id: $id}) RETURN n",
                id=node_id,
            )
            record = await result.single()
            if not record:
                return None
            n = record["n"]
            return dict(n)

    def find_nodes(
        self,
        node_type: str | None = None,
        name_contains: str | None = None,
    ) -> list[dict[str, Any]]:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self._async_find_nodes(node_type, name_contains)
        )

    async def _async_find_nodes(
        self,
        node_type: str | None,
        name_contains: str | None,
    ) -> list[dict[str, Any]]:
        clauses = ["MATCH (n:NWNode)"]
        params: dict[str, Any] = {}
        where: list[str] = []
        if node_type:
            where.append("n.node_type = $node_type")
            params["node_type"] = node_type
        if name_contains:
            where.append("toLower(n.name) CONTAINS toLower($name_contains)")
            params["name_contains"] = name_contains
        if where:
            clauses.append("WHERE " + " AND ".join(where))
        clauses.append("RETURN n")
        cypher = "\n".join(clauses)
        async with self._driver.session(database=self._database) as session:
            result = await session.run(cypher, **params)
            return [dict(record["n"]) async for record in result]

    def add_edge(self, edge: Edge) -> Edge:
        import asyncio
        asyncio.get_event_loop().run_until_complete(self._async_add_edge(edge))
        return edge

    async def _async_add_edge(self, edge: Edge) -> None:
        async with self._driver.session(database=self._database) as session:
            await session.run(
                """
                MATCH (src:NWNode {id: $source_id})
                MATCH (tgt:NWNode {id: $target_id})
                MERGE (src)-[r:NW_EDGE {id: $id}]->(tgt)
                ON CREATE SET
                    r.relation = $relation,
                    r.confidence = $confidence,
                    r.created_at = $created_at,
                    r.properties = $properties
                """,
                id=edge.id,
                source_id=edge.source_id,
                target_id=edge.target_id,
                relation=edge.relation,
                confidence=edge.confidence,
                created_at=edge.created_at,
                properties=str(edge.properties),
            )
        with self._lock:
            self._edge_count += 1
        self._emit(GraphEvent(
            event_type=GraphEventType.EDGE_ADDED,
            data={
                "id": edge.id,
                "source_id": edge.source_id,
                "target_id": edge.target_id,
                "relation": edge.relation,
                "confidence": edge.confidence,
            },
        ))

    def get_edges(
        self,
        source_id: str | None = None,
        target_id: str | None = None,
        relation: str | None = None,
    ) -> list[dict[str, Any]]:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self._async_get_edges(source_id, target_id, relation)
        )

    async def _async_get_edges(
        self,
        source_id: str | None,
        target_id: str | None,
        relation: str | None,
    ) -> list[dict[str, Any]]:
        clauses = ["MATCH (src:NWNode)-[r:NW_EDGE]->(tgt:NWNode)"]
        params: dict[str, Any] = {}
        where: list[str] = []
        if source_id:
            where.append("src.id = $source_id")
            params["source_id"] = source_id
        if target_id:
            where.append("tgt.id = $target_id")
            params["target_id"] = target_id
        if relation:
            where.append("r.relation = $relation")
            params["relation"] = relation
        if where:
            clauses.append("WHERE " + " AND ".join(where))
        clauses.append("RETURN r, src.id AS source_id, tgt.id AS target_id")
        cypher = "\n".join(clauses)
        async with self._driver.session(database=self._database) as session:
            result = await session.run(cypher, **params)
            edges = []
            async for record in result:
                e = dict(record["r"])
                e["source_id"] = record["source_id"]
                e["target_id"] = record["target_id"]
                edges.append(e)
            return edges

    def get_neighbors(self, node_id: str, depth: int = 1) -> list[dict[str, Any]]:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self._async_get_neighbors(node_id, depth)
        )

    async def _async_get_neighbors(self, node_id: str, depth: int) -> list[dict[str, Any]]:
        async with self._driver.session(database=self._database) as session:
            result = await session.run(
                f"""
                MATCH (root:NWNode {{id: $node_id}})
                MATCH (root)-[:NW_EDGE*1..{depth}]-(neighbor:NWNode)
                WHERE neighbor.id <> root.id
                RETURN DISTINCT neighbor
                """,
                node_id=node_id,
            )
            return [dict(record["neighbor"]) async for record in result]

    def to_dict(self) -> dict[str, Any]:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(self._async_to_dict())

    async def _async_to_dict(self) -> dict[str, Any]:
        async with self._driver.session(database=self._database) as session:
            node_result = await session.run("MATCH (n:NWNode) RETURN n")
            nodes = [dict(r["n"]) async for r in node_result]
            edge_result = await session.run(
                "MATCH (src:NWNode)-[r:NW_EDGE]->(tgt:NWNode) "
                "RETURN r, src.id AS source_id, tgt.id AS target_id"
            )
            edges = []
            async for r in edge_result:
                e = dict(r["r"])
                e["source_id"] = r["source_id"]
                e["target_id"] = r["target_id"]
                edges.append(e)
        return {"nodes": nodes, "edges": edges, "stats": {"node_count": len(nodes), "edge_count": len(edges)}}

    @property
    def node_count(self) -> int:
        with self._lock:
            return self._node_count

    @property
    def edge_count(self) -> int:
        with self._lock:
            return self._edge_count

    async def close(self) -> None:
        """Close the Neo4j driver. Call on shutdown."""
        await self._driver.close()
```

### Modify `src/neuroweave/config.py`

Extend `GraphBackend` enum:

```python
class GraphBackend(str, Enum):
    MEMORY     = "memory"      # existing
    NEO4J      = "neo4j"       # new
    POSTGRESQL = "postgresql"  # reserved for NW-002
```

Add Neo4j config fields to `NeuroWeaveConfig`:

```python
class NeuroWeaveConfig(BaseSettings):
    # --- existing fields unchanged ---
    llm_provider: LLMProvider = LLMProvider.ANTHROPIC
    llm_model: str = "claude-haiku-4-5-20251001"
    llm_api_key: str = ""
    extraction_enabled: bool = True
    extraction_confidence_threshold: float = 0.3
    graph_backend: GraphBackend = GraphBackend.MEMORY

    # --- new fields ---
    neo4j_uri:      str = "neo4j://localhost:7687"
    neo4j_user:     str = "neo4j"
    neo4j_password: str = ""
    neo4j_database: str = "neo4j"

    # --- existing fields unchanged ---
    server_host: str = "127.0.0.1"
    server_port: int = 8787
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.CONSOLE
```

### Modify `src/neuroweave/api.py`

The `NeuroWeave` facade must build the correct backend from config:

```python
def _build_graph_store(config: NeuroWeaveConfig) -> AbstractGraphStore:
    """Factory: returns the correct GraphStore implementation."""
    if config.graph_backend == GraphBackend.NEO4J:
        from neuroweave.graph.backends.neo4j import Neo4jGraphStore
        return Neo4jGraphStore(
            uri=config.neo4j_uri,
            user=config.neo4j_user,
            password=config.neo4j_password,
            database=config.neo4j_database,
        )
    # Default: memory
    from neuroweave.graph.backends.memory import MemoryGraphStore
    return MemoryGraphStore()
```

Replace the hardcoded `GraphStore()` construction in `NeuroWeave.__init__` and `NeuroWeave.__aenter__` with `_build_graph_store(self._config)`.

### `config/default.yaml` — modify

```yaml
# --- add below graph_backend ---
neo4j_uri: "neo4j://localhost:7687"
neo4j_user: "neo4j"
neo4j_password: ""
neo4j_database: "neo4j"
```

### `pyproject.toml` — modify

Add optional dependency group:

```toml
[project.optional-dependencies]
neo4j = ["neo4j>=5.0"]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "pytest-cov>=5.0",
    "httpx>=0.27",
    "ruff>=0.4",
    # do NOT add neo4j here — tests use memory backend by default
]
```

### Tests to write

**File:** `tests/unit/test_neo4j_backend.py`

These tests use a `MockNeo4jDriver` fixture — do NOT require a real Neo4j instance. The mock captures Cypher queries.

```
test_neo4j_store_add_node_runs_merge_cypher
test_neo4j_store_find_nodes_with_type_filter
test_neo4j_store_find_nodes_with_name_contains
test_neo4j_store_add_edge_runs_merge_cypher
test_neo4j_store_get_edges_with_relation_filter
test_neo4j_store_get_neighbors_uses_variable_depth
test_neo4j_store_emits_node_added_event
test_neo4j_store_emits_edge_added_event
test_neo4j_store_to_dict_returns_correct_structure
test_build_graph_store_returns_memory_for_memory_backend
test_build_graph_store_returns_neo4j_for_neo4j_backend
test_neuroweave_facade_uses_neo4j_when_configured
test_neo4j_config_fields_loaded_from_yaml
test_neo4j_config_fields_loaded_from_env_vars
```

---

## NW-002 — Scientific Entity Schema

**Priority:** Critical  
**Rationale:** AC1-LLM needs typed nodes so it can query "all proven Theorems in Graph Theory" directly. Generic ENTITY nodes are too coarse for mathematical reasoning.

### Modify `src/neuroweave/graph/store.py`

Extend `NodeType` enum:

```python
class NodeType(str, Enum):
    # --- existing (keep all) ---
    ENTITY      = "entity"
    CONCEPT     = "concept"
    PREFERENCE  = "preference"
    EPISODE     = "episode"
    EXPERIENCE  = "experience"

    # --- new: scientific types ---
    THEOREM         = "theorem"         # a proven mathematical statement
    LEMMA           = "lemma"           # a helper theorem used in a proof
    CONJECTURE      = "conjecture"      # an unproven hypothesis
    PROOF           = "proof"           # a proof artifact (may be attached to theorem/lemma)
    DEFINITION      = "definition"      # a mathematical definition
    EXAMPLE         = "example"         # an example or counterexample
    PAPER           = "paper"           # a published or submitted paper
    AUTHOR          = "author"          # a person who authored a paper
    DOMAIN          = "domain"          # a mathematical subdomain (e.g. Graph Theory)
    MATH_OBJECT     = "math_object"     # a mathematical structure (e.g. Cayley graph, K4)
    OPEN_PROBLEM    = "open_problem"    # a known unsolved problem
    ALGORITHM       = "algorithm"       # a computational procedure
```

Add `RelationType` enum (new — does not exist yet):

```python
class RelationType(str, Enum):
    """Typed relations for scientific knowledge graphs."""
    # Proof relationships
    PROVES          = "proves"          # Theorem PROVES Conjecture
    FOLLOWS_FROM    = "follows_from"    # Lemma FOLLOWS_FROM Theorem
    USES            = "uses"            # Proof USES Lemma
    CONTRADICTS     = "contradicts"     # Result CONTRADICTS Conjecture

    # Structural relationships
    GENERALIZES     = "generalizes"     # TheoremA GENERALIZES TheoremB
    IS_SPECIAL_CASE = "is_special_case" # TheoremB IS_SPECIAL_CASE TheoremA
    EQUIVALENT_TO   = "equivalent_to"  # TheoremA EQUIVALENT_TO TheoremB
    IS_PART_OF      = "is_part_of"      # Lemma IS_PART_OF Paper

    # Domain relationships
    BELONGS_TO      = "belongs_to"      # Theorem BELONGS_TO Domain
    APPLIES_TO      = "applies_to"      # Theorem APPLIES_TO MathObject

    # Authorship / provenance
    AUTHORED_BY     = "authored_by"     # Paper AUTHORED_BY Author
    PUBLISHED_IN    = "published_in"    # Paper PUBLISHED_IN (journal/venue concept)
    CITES           = "cites"           # Paper CITES Paper
    BUILDS_ON       = "builds_on"       # Paper BUILDS_ON Paper

    # Research status
    VERIFIED_BY     = "verified_by"     # Theorem VERIFIED_BY Proof
    REJECTED_BY     = "rejected_by"     # Conjecture REJECTED_BY Counterexample
    OPEN_SINCE      = "open_since"      # OpenProblem OPEN_SINCE year (as property)
```

Export `RelationType` from `src/neuroweave/__init__.py`.

### Modify the extraction system prompt

**File:** `src/neuroweave/extraction/pipeline.py`

Add a `_SCIENTIFIC_SYSTEM_PROMPT` constant alongside the existing generic system prompt:

```python
_SCIENTIFIC_SYSTEM_PROMPT = """You are a scientific knowledge extraction system.
Extract entities and relations from mathematical and scientific text.

OUTPUT FORMAT — valid JSON only, no surrounding text:
{
  "entities": [
    {
      "name": "string — canonical name of the entity",
      "entity_type": "theorem|lemma|conjecture|proof|definition|example|paper|author|domain|math_object|open_problem|algorithm|entity|concept",
      "properties": {
        "statement": "formal statement if this is a theorem/lemma/conjecture",
        "domain": "mathematical subdomain e.g. Graph Theory",
        "status": "proven|unproven|disproven|open",
        "year": 2024,
        "doi": "10.xxxx/yyy if known"
      }
    }
  ],
  "relations": [
    {
      "source": "entity name",
      "target": "entity name",
      "relation": "proves|follows_from|uses|contradicts|generalizes|is_special_case|equivalent_to|is_part_of|belongs_to|applies_to|authored_by|published_in|cites|builds_on|verified_by|rejected_by",
      "confidence": 0.0-1.0,
      "properties": {}
    }
  ]
}

RULES:
- Use specific scientific entity types (theorem, lemma, etc.) over generic ones (concept, entity)
- "statement" property on theorems/lemmas must be the verbatim mathematical statement if present
- Confidence 0.90-0.99 for explicitly stated facts, 0.50-0.70 for inferred relations
- Extract the full citation as a PAPER entity if a paper is referenced
- Empty arrays if no entities or relations are extractable
- NEVER add explanation or preamble — pure JSON only
"""
```

Modify `ExtractionPipeline.__init__` to accept a `mode: str = "general"` parameter:

```python
class ExtractionPipeline:
    def __init__(
        self,
        llm_client: LLMClient,
        mode: str = "general",      # "general" | "scientific"
        confidence_threshold: float = 0.3,
    ) -> None:
        self._llm = llm_client
        self._mode = mode
        self._threshold = confidence_threshold

    @property
    def _system_prompt(self) -> str:
        return _SCIENTIFIC_SYSTEM_PROMPT if self._mode == "scientific" else _GENERAL_SYSTEM_PROMPT
```

Rename the existing system prompt constant to `_GENERAL_SYSTEM_PROMPT`.

### Modify `src/neuroweave/config.py`

Add extraction mode config:

```python
class NeuroWeaveConfig(BaseSettings):
    # ... existing fields ...
    extraction_mode: str = "general"   # "general" | "scientific"
```

Wire in `src/neuroweave/api.py`:

```python
# In NeuroWeave.__aenter__ or __init__, when building ExtractionPipeline:
pipeline = ExtractionPipeline(
    llm_client=self._llm_client,
    mode=self._config.extraction_mode,       # pass through
    confidence_threshold=self._config.extraction_confidence_threshold,
)
```

### Modify `src/neuroweave/graph/ingest.py`

Extend entity type mapping to include scientific types:

```python
_ENTITY_TYPE_MAP: dict[str, NodeType] = {
    # existing
    "person":         NodeType.ENTITY,
    "organization":   NodeType.ENTITY,
    "place":          NodeType.ENTITY,
    "tool":           NodeType.CONCEPT,
    "concept":        NodeType.CONCEPT,
    "preference":     NodeType.PREFERENCE,

    # scientific — map directly
    "theorem":        NodeType.THEOREM,
    "lemma":          NodeType.LEMMA,
    "conjecture":     NodeType.CONJECTURE,
    "proof":          NodeType.PROOF,
    "definition":     NodeType.DEFINITION,
    "example":        NodeType.EXAMPLE,
    "paper":          NodeType.PAPER,
    "author":         NodeType.AUTHOR,
    "domain":         NodeType.DOMAIN,
    "math_object":    NodeType.MATH_OBJECT,
    "open_problem":   NodeType.OPEN_PROBLEM,
    "algorithm":      NodeType.ALGORITHM,

    # fallback
    "entity":         NodeType.ENTITY,
}
```

### Add typed query methods

**File:** `src/neuroweave/graph/query.py` — add new public functions:

```python
def query_by_type(
    store: AbstractGraphStore,
    entity_type: NodeType,
    relations: list[str] | None = None,
    max_hops: int = 1,
) -> QueryResult:
    """Return all nodes of the given type, optionally filtered by relation.

    Example:
        query_by_type(store, NodeType.THEOREM, relations=["proves"])
        # Returns all theorems and their "proves" relations
    """
    nodes = store.find_nodes(node_type=entity_type.value)
    if not nodes:
        return QueryResult(nodes=[], edges=[])
    node_ids = {n["id"] for n in nodes}
    all_edges = []
    for node_id in node_ids:
        edges = store.get_edges(source_id=node_id)
        if relations:
            edges = [e for e in edges if e.get("relation") in relations]
        all_edges.extend(edges)
    return QueryResult(nodes=nodes, edges=all_edges)


def get_proof_chain(
    store: AbstractGraphStore,
    theorem_name: str,
    max_hops: int = 3,
) -> QueryResult:
    """Return the full dependency chain for a theorem: theorem → lemmas → definitions.

    Traverses USES, FOLLOWS_FROM, and PROVES relations up to max_hops deep.
    """
    proof_relations = {"uses", "follows_from", "proves", "verified_by"}
    nodes = store.find_nodes(name_contains=theorem_name)
    if not nodes:
        return QueryResult(nodes=[], edges=[])
    root_id = nodes[0]["id"]
    neighbors = store.get_neighbors(root_id, depth=max_hops)
    all_edges = store.get_edges()
    relevant_ids = {root_id} | {n["id"] for n in neighbors}
    relevant_edges = [
        e for e in all_edges
        if e.get("source_id") in relevant_ids
        and e.get("target_id") in relevant_ids
        and e.get("relation") in proof_relations
    ]
    return QueryResult(nodes=[*nodes, *neighbors], edges=relevant_edges)


def get_domain_graph(
    store: AbstractGraphStore,
    domain_name: str,
) -> QueryResult:
    """Return all entities belonging to a mathematical domain."""
    domain_nodes = store.find_nodes(node_type=NodeType.DOMAIN.value, name_contains=domain_name)
    if not domain_nodes:
        return QueryResult(nodes=[], edges=[])
    domain_ids = {n["id"] for n in domain_nodes}
    all_edges = store.get_edges()
    member_edges = [
        e for e in all_edges
        if e.get("target_id") in domain_ids and e.get("relation") == "belongs_to"
    ]
    member_ids = {e["source_id"] for e in member_edges}
    member_nodes = [store.get_node(nid) for nid in member_ids if store.get_node(nid)]
    return QueryResult(
        nodes=[*(domain_nodes), *(n for n in member_nodes if n)],
        edges=member_edges,
    )
```

Export all three from `src/neuroweave/__init__.py`.

### Tests to write

**File:** `tests/unit/test_scientific_schema.py`

```
test_theorem_node_type_exists
test_all_scientific_node_types_in_enum
test_relation_type_enum_contains_proves
test_relation_type_enum_contains_cites
test_entity_type_map_includes_theorem
test_entity_type_map_includes_lemma
test_entity_type_map_fallback_to_entity
test_extraction_pipeline_uses_scientific_prompt_in_scientific_mode
test_extraction_pipeline_uses_general_prompt_in_general_mode
test_ingest_maps_theorem_type_correctly
test_ingest_maps_paper_type_correctly
test_query_by_type_returns_theorems_only
test_query_by_type_with_relation_filter
test_get_proof_chain_traverses_uses_relation
test_get_domain_graph_returns_members
test_scientific_mode_config_wired_to_pipeline
```

---

## NW-003 — Bulk Document Ingestion

**Priority:** High  
**Rationale:** AC1-LLM ingests entire papers (5,000–30,000 tokens). The current message-by-message API processes one short string at a time.

### New file to create

#### `src/neuroweave/ingest/__init__.py` — create new

```python
from neuroweave.ingest.document import DocumentIngester, DocumentIngestionResult, ChunkStrategy

__all__ = ["DocumentIngester", "DocumentIngestionResult", "ChunkStrategy"]
```

#### `src/neuroweave/ingest/document.py` — create new

```python
"""Bulk document ingestion for full scientific papers."""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from neuroweave.extraction.pipeline import ExtractionPipeline
from neuroweave.graph.backends.base import AbstractGraphStore
from neuroweave.graph.ingest import ingest_extraction


class ChunkStrategy(str, Enum):
    PARAGRAPH   = "paragraph"    # split on blank lines
    FIXED       = "fixed"        # split on fixed token count
    SECTION     = "section"      # split on LaTeX \section{} markers
    SENTENCE    = "sentence"     # split on sentence boundaries


@dataclass(frozen=True, slots=True)
class DocumentIngestionResult:
    doc_type: str
    chunk_count: int
    total_entities: int
    total_relations: int
    duration_ms: float
    chunks_failed: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class DocumentIngester:
    """Ingests full documents into the NeuroWeave knowledge graph.

    Chunks the document, runs extraction on each chunk concurrently,
    and materialises results into the graph store.
    """

    def __init__(
        self,
        pipeline: ExtractionPipeline,
        store: AbstractGraphStore,
        chunk_strategy: ChunkStrategy = ChunkStrategy.PARAGRAPH,
        max_chunk_tokens: int = 2000,
        concurrent_chunks: int = 5,
    ) -> None:
        self._pipeline = pipeline
        self._store = store
        self._strategy = chunk_strategy
        self._max_chunk_tokens = max_chunk_tokens
        self._concurrency = concurrent_chunks

    async def ingest_document(
        self,
        text: str,
        doc_type: str = "paper",
        metadata: dict[str, Any] | None = None,
    ) -> DocumentIngestionResult:
        """Chunk text and extract entities/relations from each chunk concurrently.

        Args:
            text:     Full document text (abstract, body, bibliography).
            doc_type: "paper" | "proof" | "abstract" | "notes"
            metadata: Arbitrary metadata stored on doc-level PAPER node if doc_type=="paper".

        Returns:
            DocumentIngestionResult with counts of entities and relations added.
        """
        import time
        start = time.time()
        chunks = self._chunk(text)
        semaphore = asyncio.Semaphore(self._concurrency)
        total_entities = 0
        total_relations = 0
        chunks_failed = 0

        async def process_chunk(chunk: str) -> None:
            nonlocal total_entities, total_relations, chunks_failed
            async with semaphore:
                result = await self._pipeline.extract(chunk)
                if result.entities or result.relations:
                    stats = ingest_extraction(self._store, result)
                    total_entities += stats.get("nodes_added", 0)
                    total_relations += stats.get("edges_added", 0)
                else:
                    chunks_failed += 1

        await asyncio.gather(*[process_chunk(c) for c in chunks])

        # If doc_type is "paper", create a PAPER node with metadata
        if doc_type == "paper" and metadata:
            from neuroweave.graph.store import Node, NodeType
            import uuid
            paper_node = Node(
                id=f"paper_{uuid.uuid4().hex[:12]}",
                name=metadata.get("title", "Unknown Paper"),
                node_type=NodeType.PAPER,
                properties=metadata,
            )
            self._store.add_node(paper_node)

        return DocumentIngestionResult(
            doc_type=doc_type,
            chunk_count=len(chunks),
            total_entities=total_entities,
            total_relations=total_relations,
            duration_ms=(time.time() - start) * 1000,
            chunks_failed=chunks_failed,
            metadata=metadata or {},
        )

    def _chunk(self, text: str) -> list[str]:
        """Split text into chunks according to the configured strategy."""
        if self._strategy == ChunkStrategy.PARAGRAPH:
            return self._chunk_by_paragraph(text)
        if self._strategy == ChunkStrategy.SECTION:
            return self._chunk_by_section(text)
        if self._strategy == ChunkStrategy.SENTENCE:
            return self._chunk_by_sentence(text)
        return self._chunk_fixed(text)

    def _chunk_by_paragraph(self, text: str) -> list[str]:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        return self._merge_short_chunks(paragraphs)

    def _chunk_by_section(self, text: str) -> list[str]:
        # Split on LaTeX \section{} or \subsection{} markers
        sections = re.split(r"(?=\\(?:sub)*section\{)", text)
        return [s.strip() for s in sections if s.strip()]

    def _chunk_by_sentence(self, text: str) -> list[str]:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        return self._merge_short_chunks(sentences)

    def _chunk_fixed(self, text: str) -> list[str]:
        words = text.split()
        chunks, current = [], []
        for word in words:
            current.append(word)
            if len(current) >= self._max_chunk_tokens:
                chunks.append(" ".join(current))
                current = []
        if current:
            chunks.append(" ".join(current))
        return chunks

    def _merge_short_chunks(self, chunks: list[str], min_words: int = 50) -> list[str]:
        """Merge chunks shorter than min_words with the next chunk."""
        merged: list[str] = []
        buffer = ""
        for chunk in chunks:
            buffer = (buffer + " " + chunk).strip() if buffer else chunk
            if len(buffer.split()) >= min_words:
                merged.append(buffer)
                buffer = ""
        if buffer:
            merged.append(buffer)
        return merged
```

### Modify `src/neuroweave/api.py`

Add `ingest_document` to the `NeuroWeave` facade:

```python
async def ingest_document(
    self,
    text: str,
    doc_type: str = "paper",
    metadata: dict[str, Any] | None = None,
    chunk_strategy: str = "paragraph",
    concurrent_chunks: int = 5,
) -> "DocumentIngestionResult":
    """Ingest a full document, chunking and extracting concurrently.

    Usage:
        result = await nw.ingest_document(
            text=full_paper_text,
            doc_type="paper",
            metadata={"title": "...", "doi": "...", "year": 2025},
        )
        print(f"Extracted {result.total_entities} entities from {result.chunk_count} chunks")
    """
    from neuroweave.ingest.document import ChunkStrategy, DocumentIngester
    strategy = ChunkStrategy(chunk_strategy)
    ingester = DocumentIngester(
        pipeline=self._pipeline,
        store=self._graph,
        chunk_strategy=strategy,
        concurrent_chunks=concurrent_chunks,
    )
    return await ingester.ingest_document(text, doc_type=doc_type, metadata=metadata)
```

Export `DocumentIngestionResult`, `ChunkStrategy` from `src/neuroweave/__init__.py`.

### Tests to write

**File:** `tests/unit/test_document_ingestion.py`

```
test_ingest_document_chunks_by_paragraph
test_ingest_document_chunks_by_section
test_ingest_document_chunks_by_sentence
test_ingest_document_chunks_fixed
test_ingest_document_concurrent_extraction
test_ingest_document_returns_correct_entity_count
test_ingest_document_returns_correct_relation_count
test_ingest_document_creates_paper_node_when_metadata_provided
test_ingest_document_short_chunks_merged
test_ingest_document_empty_text_returns_zero_counts
test_ingest_document_failed_chunks_counted
test_facade_ingest_document_method_exists
test_facade_ingest_document_returns_result
test_chunk_strategy_enum_values
test_ingest_concurrent_chunks_respects_semaphore
```

---

## NW-004 — Qdrant Integration Bridge

**Priority:** High  
**Rationale:** NeuroWeave holds structured entity graph. Qdrant holds semantic embeddings. AC1-LLM needs both together: "find all theorems about Cayley graphs that are semantically similar to this new conjecture."

### New files to create

#### `src/neuroweave/vector/__init__.py` — create new

```python
from neuroweave.vector.qdrant_bridge import QdrantBridge, VectorContextResult

__all__ = ["QdrantBridge", "VectorContextResult"]
```

#### `src/neuroweave/vector/qdrant_bridge.py` — create new

```python
"""Qdrant vector search bridge for NeuroWeave."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from qdrant_client import AsyncQdrantClient

from neuroweave.graph.backends.base import AbstractGraphStore
from neuroweave.graph.query import QueryResult


@dataclass
class VectorContextResult:
    """Combined result from graph traversal + vector similarity search."""
    graph_context: QueryResult
    vector_matches: list[dict[str, Any]]        # raw Qdrant hits
    combined_node_ids: set[str]                  # union of graph + vector node IDs
    query: str
    vector_collection: str

    def all_node_names(self) -> list[str]:
        names = [n.get("name", "") for n in self.graph_context.nodes]
        for hit in self.vector_matches:
            payload = hit.get("payload", {})
            if "name" in payload:
                names.append(payload["name"])
        return list(dict.fromkeys(names))   # deduplicated, order preserved


class QdrantBridge:
    """Combines NeuroWeave graph traversal with Qdrant vector similarity search.

    Usage:
        bridge = QdrantBridge(
            store=nw._graph,
            qdrant_client=AsyncQdrantClient(url="http://localhost:6333"),
            collection="ravennest_papers",
        )
        result = await bridge.get_context_with_vectors(
            query="chromatic polynomial roots for planar graphs",
            query_vector=[0.1, 0.2, ...],   # pre-computed embedding
            top_k=10,
        )
    """

    def __init__(
        self,
        store: AbstractGraphStore,
        qdrant_client: "AsyncQdrantClient",
        collection: str = "ravennest_papers",
    ) -> None:
        self._store = store
        self._qdrant = qdrant_client
        self._collection = collection

    async def get_context_with_vectors(
        self,
        query: str,
        query_vector: list[float],
        top_k: int = 10,
        qdrant_filter: dict[str, Any] | None = None,
        graph_hops: int = 2,
    ) -> VectorContextResult:
        """Run graph NL query and vector search concurrently, merge results.

        Args:
            query:         Natural language query (used for graph NL lookup).
            query_vector:  Pre-computed embedding vector for Qdrant.
            top_k:         Number of vector search results to return.
            qdrant_filter: Optional Qdrant filter dict.
            graph_hops:    Max hops for graph BFS traversal.

        Returns:
            VectorContextResult combining graph + vector hits.
        """
        import asyncio
        from neuroweave.graph.nl_query import NLQueryPlanner

        # Run graph query and vector search concurrently
        graph_task = asyncio.create_task(self._graph_query(query, graph_hops))
        vector_task = asyncio.create_task(self._vector_search(query_vector, top_k, qdrant_filter))
        graph_result, vector_hits = await asyncio.gather(graph_task, vector_task)

        # Build combined node ID set
        graph_ids = {n.get("id", "") for n in graph_result.nodes}
        vector_ids = {hit.get("id", "") for hit in vector_hits}

        return VectorContextResult(
            graph_context=graph_result,
            vector_matches=vector_hits,
            combined_node_ids=graph_ids | vector_ids,
            query=query,
            vector_collection=self._collection,
        )

    async def _graph_query(self, query: str, max_hops: int) -> QueryResult:
        """Run a broad name-based graph search as fallback for NL queries."""
        # Extract key terms from query (first 3 significant words)
        words = [w for w in query.split() if len(w) > 4][:3]
        nodes = []
        for word in words:
            nodes.extend(self._store.find_nodes(name_contains=word))
        if not nodes:
            return QueryResult(nodes=[], edges=[])
        node_ids = list({n["id"] for n in nodes})[:5]
        neighbors = []
        for nid in node_ids:
            neighbors.extend(self._store.get_neighbors(nid, depth=max_hops))
        all_nodes = list({n["id"]: n for n in [*nodes, *neighbors]}.values())
        all_ids = {n["id"] for n in all_nodes}
        all_edges = [
            e for e in self._store.get_edges()
            if e.get("source_id") in all_ids and e.get("target_id") in all_ids
        ]
        return QueryResult(nodes=all_nodes, edges=all_edges)

    async def _vector_search(
        self,
        query_vector: list[float],
        top_k: int,
        qdrant_filter: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        from qdrant_client.models import Filter
        filter_obj = None
        if qdrant_filter:
            filter_obj = Filter(**qdrant_filter)
        results = await self._qdrant.search(
            collection_name=self._collection,
            query_vector=query_vector,
            limit=top_k,
            query_filter=filter_obj,
            with_payload=True,
        )
        return [
            {
                "id": str(hit.id),
                "score": hit.score,
                "payload": hit.payload or {},
            }
            for hit in results
        ]

    async def upsert_node_vectors(
        self,
        node_id: str,
        vector: list[float],
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Store a node's vector embedding in Qdrant alongside the graph node."""
        from qdrant_client.models import PointStruct
        node = self._store.get_node(node_id)
        full_payload = {**(node or {}), **(payload or {})}
        await self._qdrant.upsert(
            collection_name=self._collection,
            points=[PointStruct(id=node_id, vector=vector, payload=full_payload)],
        )
```

### Modify `src/neuroweave/api.py`

Add `get_context_with_vectors` to the `NeuroWeave` facade:

```python
async def get_context_with_vectors(
    self,
    query: str,
    query_vector: list[float],
    qdrant_client: Any,             # AsyncQdrantClient — deferred import avoids hard dep
    collection: str = "ravennest_papers",
    top_k: int = 10,
    graph_hops: int = 2,
    qdrant_filter: dict[str, Any] | None = None,
) -> "VectorContextResult":
    """Combined graph + vector search. Requires qdrant-client to be installed.

    Usage:
        from qdrant_client import AsyncQdrantClient
        client = AsyncQdrantClient(url="http://localhost:6333")
        result = await nw.get_context_with_vectors(
            query="chromatic polynomial bounds",
            query_vector=embedding,
            qdrant_client=client,
        )
    """
    from neuroweave.vector.qdrant_bridge import QdrantBridge
    bridge = QdrantBridge(
        store=self._graph,
        qdrant_client=qdrant_client,
        collection=collection,
    )
    return await bridge.get_context_with_vectors(
        query=query,
        query_vector=query_vector,
        top_k=top_k,
        graph_hops=graph_hops,
        qdrant_filter=qdrant_filter,
    )
```

### `pyproject.toml` — add optional dependency

```toml
[project.optional-dependencies]
qdrant = ["qdrant-client>=1.9"]
```

### Tests to write

**File:** `tests/unit/test_qdrant_bridge.py`

Use a `MockQdrantClient` fixture — do NOT require a real Qdrant instance.

```
test_vector_context_result_all_node_names_deduplicates
test_vector_context_result_combined_node_ids_is_union
test_qdrant_bridge_runs_graph_and_vector_concurrently
test_qdrant_bridge_graph_query_returns_nodes_by_name
test_qdrant_bridge_vector_search_calls_qdrant_with_filter
test_qdrant_bridge_vector_search_no_filter
test_qdrant_bridge_upsert_node_vectors
test_facade_get_context_with_vectors_exists
test_facade_get_context_with_vectors_returns_vector_context_result
```

---

## NW-005 — Node Merge / Deduplication

**Priority:** Medium  
**Rationale:** When AC1-LLM proves Theorem X in session 2, it must not create a duplicate of the Theorem X node already in the graph from session 1. The current dedup is case-insensitive name match within a session only.

### Modify `src/neuroweave/graph/ingest.py`

The existing dedup is: "build a name→id index from the current graph, skip entities whose name is already in the index."

Extend `ingest_extraction` to call the persistent store:

```python
def _resolve_entity_name(
    name: str,
    store: AbstractGraphStore,
    local_index: dict[str, str],
) -> str | None:
    """Return existing node ID for name, checking local index then store.

    Priority:
    1. local_index (built this ingestion pass)
    2. store.find_nodes(name_contains=name) — cross-session dedup
    Returns None if not found.
    """
    key = name.lower()
    if key in local_index:
        return local_index[key]
    matches = store.find_nodes(name_contains=name)
    exact = [m for m in matches if m.get("name", "").lower() == key]
    if exact:
        return exact[0]["id"]
    return None
```

Replace the `local_index = {n["name"].lower(): n["id"] for n in store.find_nodes()}` approach with a call to `_resolve_entity_name` for each entity before deciding to create a new node.

When a node is reused (found in store but not created), emit a `GraphEvent` with `GraphEventType.NODE_UPDATED` carrying the reused node's id and the new incoming properties (for merging properties on the existing node).

### Modify `src/neuroweave/graph/store.py`

Add `update_node_properties` method to `MemoryGraphStore` (and declare in `AbstractGraphStore`):

```python
# AbstractGraphStore — add abstract method:
@abc.abstractmethod
def update_node_properties(self, node_id: str, properties: dict[str, Any]) -> None:
    """Merge new properties into an existing node. Existing keys are preserved;
    new keys are added. Conflicts: new value wins."""
    ...

# MemoryGraphStore implementation:
def update_node_properties(self, node_id: str, properties: dict[str, Any]) -> None:
    if node_id not in self._graph.nodes:
        return
    existing = self._graph.nodes[node_id].get("properties", {})
    merged = {**existing, **properties}
    self._graph.nodes[node_id]["properties"] = merged
    self._emit(GraphEvent(
        event_type=GraphEventType.NODE_UPDATED,
        data={"id": node_id, "properties": merged},
    ))
```

### Tests to write

**File:** `tests/unit/test_deduplication.py`

```
test_dedup_reuses_node_by_exact_name_case_insensitive
test_dedup_reuses_node_from_store_across_sessions
test_dedup_does_not_create_duplicate_when_name_exists
test_dedup_merges_properties_on_existing_node
test_dedup_emits_node_updated_on_reuse
test_dedup_emits_node_added_on_new_node
test_dedup_local_index_takes_priority_over_store
test_update_node_properties_merges_correctly
test_update_node_properties_new_key_wins
test_update_node_properties_noop_for_unknown_id
```

---

## NW-006 — `config/default.yaml` Final State

After all changes, `config/default.yaml` must be:

```yaml
# NeuroWeave default configuration
# Override any field via environment variable: NEUROWEAVE_{FIELD}

llm_provider: "anthropic"
llm_model: "claude-haiku-4-5-20251001"
llm_api_key: ""

extraction_enabled: true
extraction_confidence_threshold: 0.3
extraction_mode: "general"               # "general" | "scientific"

graph_backend: "memory"                  # "memory" | "neo4j" | "postgresql"

neo4j_uri: "neo4j://localhost:7687"
neo4j_user: "neo4j"
neo4j_password: ""
neo4j_database: "neo4j"

server_host: "127.0.0.1"
server_port: 8787

log_level: "INFO"
log_format: "console"                    # "console" | "json"
```

---

## Acceptance Criteria

All requirements are complete when:

1. `pytest` passes with zero failures on all ~308 existing tests plus all new tests.
2. `ruff check src/ tests/` produces no violations.
3. `mypy src/` produces no errors with `strict = true`.
4. `NEUROWEAVE_GRAPH_BACKEND=neo4j NEUROWEAVE_NEO4J_URI=neo4j://localhost:7687 python -m neuroweave` starts without import errors (even without a running Neo4j instance — the error should be a connection error, not an import error).
5. `NEUROWEAVE_EXTRACTION_MODE=scientific` causes the scientific extraction prompt to be used.
6. `await nw.ingest_document(text)` splits a 5,000-word paper into chunks and returns a `DocumentIngestionResult` with `chunk_count >= 5`.
7. `await nw.get_context_with_vectors(query, vector, mock_qdrant)` returns a `VectorContextResult` with both `graph_context` and `vector_matches` populated.
8. Ingesting the same entity name twice results in exactly one node in the graph (NW-005 dedup).
9. `NodeType.THEOREM` is a valid `NodeType` and is accepted by `query_by_type(store, NodeType.THEOREM)`.
10. All new public symbols are exported from `src/neuroweave/__init__.py` and appear in `__all__`.