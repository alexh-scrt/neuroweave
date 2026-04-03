# NeuroWeave Developer Tutorial

A hands-on guide for developers who want to understand, extend, or contribute to NeuroWeave.

---

## Prerequisites

- Python 3.11+
- Git
- (Optional) Neo4j 5.x for persistent backend testing

---

## Setup

```bash
git clone https://github.com/alexh-scrt/neuroweave.git
cd neuroweave
make install    # pip install -e ".[dev]"
```

Verify:

```bash
make test       # Should see ~400 tests passing
```

---

## Running NeuroWeave

### Mock Mode (no API key)

```bash
NEUROWEAVE_LLM_PROVIDER=mock neuroweave
```

### With Anthropic

```bash
export NEUROWEAVE_LLM_API_KEY=sk-ant-...
neuroweave
```

### Demo Agent

```bash
python examples/demo_agent.py              # Canned demo
python examples/demo_agent.py -i           # Interactive
python examples/demo_agent.py --provider anthropic  # Real LLM
```

### As a Library

```python
import asyncio
from neuroweave import NeuroWeave

async def main():
    async with NeuroWeave(llm_provider="mock") as nw:
        result = await nw.process("My name is Alex and I'm a software engineer")
        print(f"Extracted {result.entity_count} entities, {result.relation_count} relations")
        print(f"Graph: {nw.graph.node_count} nodes, {nw.graph.edge_count} edges")

        context = await nw.get_context("I've been using Python for 10 years")
        print(f"Relevant: {context.relevant.node_names()}")

asyncio.run(main())
```

---

## Architecture Overview

```
NeuroWeave Facade (api.py)
  ├── ExtractionPipeline (extraction/)
  │     └── LLMClient (mock or anthropic)
  ├── AbstractGraphStore (graph/backends/)
  │     ├── MemoryGraphStore (NetworkX)
  │     └── Neo4jGraphStore (async driver)
  ├── Ingest (graph/ingest.py)
  ├── Query Engine (graph/query.py)
  ├── NL Query Planner (graph/nl_query.py)
  ├── EventBus (events.py)
  └── Visualization Server (server/app.py)
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed diagrams and data flow.

---

## Graph Backend System

### The Async Interface

All graph store methods are `async def` (since v0.2.1). This is required because NeuroWeave runs inside async event loops — `run_until_complete()` cannot be called from within a running loop.

```python
from neuroweave.graph.backends.base import AbstractGraphStore

class AbstractGraphStore(ABC):
    async def initialize(self) -> None: ...
    async def add_node(self, node: Node) -> Node: ...
    async def get_node(self, node_id: str) -> dict | None: ...
    async def find_nodes(self, node_type=None, name_contains=None) -> list[dict]: ...
    async def add_edge(self, edge: Edge) -> Edge: ...
    async def get_edges(self, source_id=None, target_id=None, relation=None) -> list[dict]: ...
    async def get_neighbors(self, node_id: str, depth: int = 1) -> list[dict]: ...
    async def update_node_properties(self, node_id: str, properties: dict) -> None: ...
    async def to_dict(self) -> dict: ...

    @property
    def node_count(self) -> int: ...   # sync — cached counter
    @property
    def edge_count(self) -> int: ...   # sync — cached counter
```

### MemoryGraphStore

Wraps sync NetworkX operations in async methods. Used for development, testing, and ephemeral sessions.

```python
from neuroweave.graph.backends.memory import MemoryGraphStore

store = MemoryGraphStore()
await store.initialize()  # no-op
node = await store.add_node(make_node("Alice", NodeType.ENTITY))
```

### Neo4jGraphStore

Uses the native async Neo4j driver. On `initialize()`, creates:
- Uniqueness constraint on `NWNode.id`
- Indexes on `NWNode.name`, `NWNode.node_type`, `NW_EDGE.relation`

```python
from neuroweave.graph.backends.neo4j import Neo4jGraphStore

store = Neo4jGraphStore(uri="neo4j://localhost:7687", user="neo4j", password="secret")
await store.initialize()  # creates schema if not exists
```

### Selecting a Backend

Set `graph_backend` in config or environment:

```bash
NEUROWEAVE_GRAPH_BACKEND=neo4j neuroweave
```

Or in code:

```python
nw = NeuroWeave(llm_provider="mock")  # defaults to memory
```

---

## Writing Tests

### Test Infrastructure

- **pytest** with `asyncio_mode = "auto"` — async test functions run automatically
- **`MemoryGraphStore`** for all tests (no real Neo4j needed)
- **`MockLLMClient`** for deterministic extraction responses
- **`conftest.py`** provides shared fixtures

### Pattern: Testing with MemoryGraphStore

```python
import pytest
from neuroweave.graph.backends.memory import MemoryGraphStore
from neuroweave.graph.store import GraphStore, NodeType, make_node

@pytest.fixture
def store() -> MemoryGraphStore:
    return MemoryGraphStore()

async def test_add_and_find(store: MemoryGraphStore):
    node = make_node("Alice", NodeType.ENTITY)
    await store.add_node(node)
    results = await store.find_nodes(name_contains="Alice")
    assert len(results) == 1
    assert results[0]["name"] == "Alice"
```

### Pattern: Sync Fixture Setup

When building test fixtures, you can call the sync `GraphStore` parent methods directly to avoid `await` in non-async fixtures:

```python
@pytest.fixture
def populated_store() -> MemoryGraphStore:
    store = MemoryGraphStore()
    # Sync parent method — no await needed
    GraphStore.add_node(store, make_node("Alice", NodeType.ENTITY, node_id="alice"))
    GraphStore.add_node(store, make_node("Bob", NodeType.ENTITY, node_id="bob"))
    GraphStore.add_edge(store, make_edge_from_tuple("alice", "bob", "knows", 0.9))
    return store
```

### Pattern: Testing with MockLLMClient

```python
from neuroweave.extraction.llm_client import MockLLMClient
from neuroweave.extraction.pipeline import ExtractionPipeline

mock = MockLLMClient()
mock.set_response("alice", {
    "entities": [{"name": "Alice", "entity_type": "person"}],
    "relations": [],
})

pipeline = ExtractionPipeline(mock)
result = await pipeline.extract("My name is Alice")
assert result.entities[0].name == "Alice"
```

### Running Tests

```bash
make test           # All tests
make test-cov       # With coverage
make lint           # Ruff linting

# Run specific test file
python -m pytest tests/test_query.py -v

# Run specific test
python -m pytest tests/test_query.py::TestBasicQueries::test_empty_store -v
```

---

## Key Concepts

### Entity Deduplication

Entities are deduplicated by case-insensitive name matching across sessions. When processing "Alice loves Python" followed by "alice uses Lean4", the second message reuses the existing "Alice" node.

The dedup happens in `ingest_extraction()`:
1. Query store for all existing nodes
2. Build lowercase name → node ID index
3. For each extracted entity, check the index before creating

### Event System

NeuroWeave uses an async `EventBus` for decoupled notifications:

```python
from neuroweave import EventType

async def on_node_added(event):
    print(f"New entity: {event.data['name']}")

nw.subscribe(on_node_added, event_types={EventType.NODE_ADDED})
```

Events: `NODE_ADDED`, `NODE_UPDATED`, `EDGE_ADDED`, `EDGE_UPDATED`

### Query Engine

Two query paths:

**Structured** — deterministic, no LLM:
```python
result = await nw.query(["Alice"], relations=["knows"], max_hops=2)
```

**Natural language** — LLM translates to structured query:
```python
result = await nw.query("who does Alice know?")
```

---

## Adding a New Graph Backend

1. Create `src/neuroweave/graph/backends/mybackend.py`
2. Implement `AbstractGraphStore` with all async methods
3. Add to `GraphBackend` enum in `config.py`
4. Add factory case in `_build_graph_store()` in `api.py`
5. Write tests in `tests/unit/test_mybackend.py`

Key requirements:
- `initialize()` must be idempotent
- `node_count`/`edge_count` are sync properties (cached counters)
- `find_nodes()` must support case-insensitive `name_contains` matching
- Emit `GraphEvent` objects for mutations

---

## Configuration

Three-tier priority: **field defaults < YAML < environment variables**

```bash
# All env vars are prefixed with NEUROWEAVE_
NEUROWEAVE_LLM_PROVIDER=mock
NEUROWEAVE_LLM_API_KEY=sk-ant-...
NEUROWEAVE_GRAPH_BACKEND=neo4j
NEUROWEAVE_NEO4J_URI=neo4j://localhost:7687
NEUROWEAVE_LOG_FORMAT=json
```

---

## Common Development Tasks

### Adding a New Node Type

1. Add to `NodeType` enum in `store.py`
2. Add extraction type mapping in `ingest.py` (`_ENTITY_TYPE_MAP`)
3. Add color in `static/index.html` node style map

### Adding a New Query Function

1. Add `async def` function in `query.py`
2. Accept `store: Any` (not `GraphStore`) for backend flexibility
3. Use `await store.find_nodes()`, `await store.get_edges()`, etc.
4. Return `QueryResult`
5. Write tests using `MemoryGraphStore` fixture

### Modifying the Extraction Prompt

Edit `_SYSTEM_PROMPT` or `_SCIENTIFIC_SYSTEM_PROMPT` in `extraction/pipeline.py`. Test with `MockLLMClient` first, then verify with real LLM.
