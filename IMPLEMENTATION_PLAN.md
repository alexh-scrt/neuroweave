# NeuroWeave — Implementation Plan

---

## POC (Completed ✅)

**Goal:** Demonstrate that a conversation with an AI agent results in a knowledge graph being built and visualized in real time.

| Step | What | Status |
|------|------|--------|
| 1 | Project scaffolding (`pyproject.toml`, `Makefile`, `.gitignore`) | ✅ |
| 2 | Configuration system (`config.py`, `default.yaml`) | ✅ |
| 3 | Structured logging (`logging.py`) | ✅ |
| 4 | In-memory graph store (`graph/store.py`) | ✅ |
| 5 | Extraction pipeline with mock LLM (`extraction/pipeline.py`, `llm_client.py`) | ✅ |
| 6 | Wiring: extraction → graph ingestion (`graph/ingest.py`, `main.py`) | ✅ |
| 7 | Visualization server + Cytoscape.js UI (`server/app.py`, `static/index.html`) | ✅ |
| 8 | End-to-end proof test (`test_e2e.py`) | ✅ |
| 9 | WebSocket live updates (`test_live_updates.py`) | ✅ |
| 10 | Async refactor | ✅ |
| 11 | GraphStore Query Engine | ✅ |
| 12 | Natural Language Query Planner | ✅ |
| 13 | Event Subscription System | ✅ |
| 14 | NeuroWeave Facade | ✅ |
| 15 | Demo Agent | ✅ |
| 16 | Package Publishing Prep | ✅ |

**Result:** ~136 tests passing. `main.py` runs a terminal conversation loop with live graph visualization at `localhost:8787`. The POC proves the core loop works.

---

## Phase 1 — v0.1.0: Library Integration Layer

**Goal:** Transform NeuroWeave from a standalone CLI application into an async Python library that any AI agent can import and use. Ship to PyPI.

**Philosophy:** The agent owns the conversation loop. NeuroWeave owns the knowledge graph. The boundary is a clean async API with two directions — write (process messages) and read (query knowledge).

### Public API Surface

```python
from neuroweave import NeuroWeave

# Initialize
nw = NeuroWeave.from_config("config/default.yaml")
# or
nw = NeuroWeave(llm_provider="mock")

# Write path — agent feeds a user message
extraction = await nw.process("My wife Lena loves Malbec")
# extraction.entities, extraction.relations, extraction.graph_delta

# Read path — structured query
results = await nw.query(entities=["Lena"], relations=["prefers"], max_hops=2)

# Read path — natural language query (LLM-powered)
results = await nw.query("what does my wife like?")

# Combined — process + query in one call
context = await nw.get_context("remind me about my wife's birthday")
# context.extraction  — what was just extracted from this message
# context.relevant    — subgraph of knowledge relevant to this message

# Event subscription
nw.subscribe(my_handler, event_types=[EventType.NODE_ADDED, EventType.EDGE_ADDED])
nw.unsubscribe(my_handler)

# Optional visualization
nw = NeuroWeave(enable_visualization=True, server_port=8787)

# Lifecycle
await nw.start()   # Start background tasks (viz server, event dispatch)
await nw.stop()    # Graceful shutdown

# Async context manager
async with NeuroWeave.from_config("config/default.yaml") as nw:
    context = await nw.get_context("hello")
```

### Architecture After Phase 1

```
┌─────────────────────────────────────────────────────┐
│  Agent Process (owns conversation loop, tools, etc) │
│                                                     │
│   agent_llm.chat(user_msg + nw_context) ──► user    │
│        │                          ▲                  │
│        │ user_msg                 │ relevant context  │
│        ▼                          │                  │
│  ┌─────────────────────────────────────────────┐    │
│  │         NeuroWeave (async library)           │    │
│  │                                             │    │
│  │  ┌──────────┐  ┌────────────┐  ┌────────┐  │    │
│  │  │ process() │  │  query()   │  │ events │  │    │
│  │  │  (write)  │  │  (read)    │  │ (push) │  │    │
│  │  └─────┬─────┘  └─────┬──────┘  └───┬────┘  │    │
│  │        │               │             │       │    │
│  │  ┌─────▼───────────────▼─────────────▼──┐   │    │
│  │  │  ExtractionPipeline  │  QueryEngine  │   │    │
│  │  │  IngestBridge        │  NLQueryPlanner│   │    │
│  │  └─────────┬────────────┴───────┬───────┘   │    │
│  │            │                    │            │    │
│  │  ┌─────────▼────────────────────▼────────┐  │    │
│  │  │           GraphStore (NetworkX)        │  │    │
│  │  └───────────────────┬───────────────────┘  │    │
│  │                      │ optional              │    │
│  │  ┌───────────────────▼───────────────────┐  │    │
│  │  │     Visualization Server (FastAPI)     │  │    │
│  │  └───────────────────────────────────────┘  │    │
│  └─────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

### Implementation Steps

#### Step 10: Async Refactor ✅

**Status:** Already complete — the codebase was migrated to async during POC Steps 5–9.

**What changed:
- `LLMClient` protocol: `extract()` becomes `async def extract()`
- `MockLLMClient.extract()` → `async def extract()`
- `AnthropicLLMClient` → uses `anthropic.AsyncAnthropic` instead of `anthropic.Anthropic`
- `ExtractionPipeline.extract()` → `async def extract()`
- `ingest_extraction()` stays sync (in-memory graph ops, no I/O)
- `process_message()` in `main.py` → `async def process_message()`
- `GraphStore` event queue reverts from `queue.Queue` to `asyncio.Queue` (same event loop now)
- All tests updated to use `pytest-asyncio`

**Depends on:** POC complete
**Validates:** `make test` passes with all existing tests running async. Zero behavior change.

**Files touched:**
- `src/neuroweave/extraction/llm_client.py` — async protocol + implementations
- `src/neuroweave/extraction/pipeline.py` — async extract()
- `src/neuroweave/graph/store.py` — asyncio.Queue for events
- `src/neuroweave/server/app.py` — asyncio.Queue consumer (simpler, no thread bridge)
- `src/neuroweave/main.py` — async process_message, asyncio.run in main()
- `tests/` — all test files updated for async

#### Step 11: GraphStore Query Engine ✅

**What's added:**
- `GraphStore.query_subgraph()` — structured query method that returns a filtered subgraph
  - Parameters: `entities` (list of names), `relations` (list of types), `min_confidence` (float), `max_hops` (int)
  - Returns: `QueryResult` dataclass with matching nodes, edges, and traversal metadata
  - Supports entity name resolution: "Lena" finds the node regardless of ID
  - Supports hop traversal: start from matched entities, walk N hops, collect everything
- `QueryResult` dataclass — structured return type with nodes, edges, and metadata

**Depends on:** Step 10
**Validates:** Structured queries return expected subgraphs. Test with the 5-message corpus: querying for "Lena" returns her, her preferences, her travel plans.

**Files added:**
- `src/neuroweave/graph/query.py` — `QueryResult`, `query_subgraph()`
- `tests/test_query.py` — structured query tests

#### Step 12: Natural Language Query Planner ✅

**What's added:**
- `NLQueryPlanner` — takes a natural language question, calls LLM with graph schema context, returns a structured query plan
  - Input: `"what does my wife like?"` + graph schema (node names, relation types)
  - LLM output: `{"entities": ["Lena"], "relations": ["prefers", "likes"], "max_hops": 1}`
  - System prompt teaches the LLM about the graph schema and how to translate questions to graph queries
  - Falls back to broad search if LLM returns unparseable output
- Auto-detection in the facade: string input → NL query path, kwargs → structured path

**Depends on:** Steps 10, 11
**Validates:** Natural language queries resolve to correct subgraphs. `"what does my wife like?"` returns Lena's preferences. `"where are we traveling?"` returns Tokyo.

**Files added:**
- `src/neuroweave/graph/nl_query.py` — `NLQueryPlanner`
- `tests/test_nl_query.py` — NL query tests with mock LLM

#### Step 13: Event Subscription System ✅

**What's added:**
- `EventBus` — internal pub/sub that replaces the raw queue approach
  - `subscribe(callback, event_types=None)` — register an async callback, optionally filter by event type
  - `unsubscribe(callback)` — remove a callback
  - `emit(event)` — fire event to all matching subscribers (non-blocking, timeout-protected)
  - Callbacks are invoked via `asyncio.create_task()` — one slow handler doesn't block others
  - 5-second timeout per handler invocation — logs warning if exceeded, does not cancel
- `GraphStore` wired to emit through `EventBus` instead of raw queue
- Visualization server subscribes to `EventBus` like any other consumer

**Depends on:** Step 10
**Validates:** Registering a handler, mutating the graph, and asserting the handler was called with correct event data. Test subscribe/unsubscribe lifecycle. Test that slow handlers don't block emission.

**Files added:**
- `src/neuroweave/events.py` — `EventBus`, event types
- `tests/test_events.py` — subscription lifecycle, emission, timeout handling

**Files modified:**
- `src/neuroweave/graph/store.py` — emit through EventBus
- `src/neuroweave/server/app.py` — subscribe to EventBus instead of polling queue

#### Step 14: NeuroWeave Facade ✅

**What's added:**
- `NeuroWeave` class — the public API entry point
  - `__init__(llm_provider, llm_model, llm_api_key, enable_visualization, server_host, server_port, log_level, log_format, **kwargs)` — programmatic construction
  - `from_config(path)` classmethod — load from YAML file
  - `async start()` — initialize internals, optionally start viz server
  - `async stop()` — graceful shutdown
  - `async __aenter__` / `async __aexit__` — context manager support
  - `async process(message) → ProcessResult` — extract + ingest, return what changed
  - `async query(text_or_entities, ...) → QueryResult` — auto-detect structured vs NL
  - `async get_context(message) → ContextResult` — process + query combined
  - `subscribe(callback, event_types)` / `unsubscribe(callback)` — delegate to EventBus
  - `create_visualization_app() → FastAPI` — for agents that want to mount the viz alongside their own routes
- `ProcessResult` — wraps ExtractionResult + graph delta (nodes_added, edges_added)
- `ContextResult` — wraps ProcessResult + QueryResult

**Depends on:** Steps 10–13
**Validates:** Full lifecycle test: create NeuroWeave, start, process 5 messages, query, get_context, subscribe to events, stop. Assert graph state, query results, and event delivery.

**Files added:**
- `src/neuroweave/api.py` — `NeuroWeave` class, `ProcessResult`, `ContextResult`
- `tests/test_api.py` — facade lifecycle, process, query, get_context, events

**Files modified:**
- `src/neuroweave/__init__.py` — export `NeuroWeave`, `ProcessResult`, `ContextResult`, `QueryResult`, `EventType`

#### Step 15: Demo Agent ✅

**What's added:**
- `examples/demo_agent.py` — minimal async agent that demonstrates NeuroWeave integration
  - Takes user input in a loop
  - Calls `nw.get_context(message)` on every message
  - Prints the context NeuroWeave returned (entities, relations, relevant knowledge)
  - Generates a mock response that incorporates the context
  - Demonstrates event subscription (prints when new entities are discovered)
  - Includes a `/ask` command that queries the graph directly
  - Self-contained, runnable: `python examples/demo_agent.py`
- Integration test that instantiates the demo agent with mock LLM, feeds the 5-message corpus, and asserts context flows correctly

**Depends on:** Step 14
**Validates:** The public API is usable and ergonomic. A developer can look at this file and understand how to integrate NeuroWeave in 5 minutes.

**Files added:**
- `examples/demo_agent.py`
- `tests/test_integration.py` — integration test using the demo agent pattern

#### Step 16: Package Publishing Prep ✅

**What's added:**
- `pyproject.toml` updates: description, author, keywords, classifiers, project URLs, license file
- `LICENSE` file (Apache 2.0)
- `CHANGELOG.md` — v0.1.0 release notes
- `py.typed` marker file for PEP 561
- Clean up `__init__.py` exports — explicit `__all__` with public API only
- Verify: `pip install -e .` works, `from neuroweave import NeuroWeave` works, type hints resolve
- README updated with PyPI installation instructions and comprehensive project docs
- `make publish` target in Makefile (build + twine upload)
- `.readthedocs.yaml` — RTD v2 config with MkDocs, `fail_on_warning`, Python 3.12
- `mkdocs.yml` — full MkDocs Material config with mkdocstrings, mermaid, dark/light mode
- `docs/` — complete documentation site: index, getting-started, user guide (4 pages), API reference (5 pages), architecture, changelog
- `ARCHITECTURE.md` updated with Phase 1 components, test counts, and design decisions

**Depends on:** Steps 10–15
**Validates:** `pip install .` from clean venv works. All exports resolve. `make publish` builds a wheel. `mkdocs build --strict` passes. RTD config valid.

**Files added/modified:**
- `pyproject.toml` — metadata, `[project.optional-dependencies].docs`
- `LICENSE`
- `CHANGELOG.md`
- `src/neuroweave/__init__.py` — `__all__`
- `src/neuroweave/py.typed`
- `Makefile` — `publish`, `docs`, `docs-serve` targets
- `README.md` — installation from PyPI, badges, full project docs
- `.readthedocs.yaml` — RTD build configuration
- `mkdocs.yml` — documentation site configuration
- `docs/` — complete documentation tree
- `ARCHITECTURE.md` — updated for Phase 1

### v0.1.0 Validation Criteria

All of the following must be true before tagging v0.1.0:

1. `make test` passes — all tests green (POC + Phase 1)
2. `from neuroweave import NeuroWeave` — works from a clean install
3. `async with NeuroWeave(llm_provider="mock") as nw:` — lifecycle works
4. `await nw.process(msg)` — extracts entities and relations, updates graph
5. `await nw.query(entities=["Lena"])` — returns structured subgraph
6. `await nw.query("what does my wife like?")` — NL query returns relevant results
7. `await nw.get_context(msg)` — combined process + query works
8. Event subscription fires on graph mutations
9. `enable_visualization=True` starts the Cytoscape.js server
10. `examples/demo_agent.py` runs and demonstrates integration
11. `pip install .` from clean venv works
12. README, ARCHITECTURE.md, and CHANGELOG.md are current

---

## Phase 2 — v0.2.0: Production Storage and Agent Protocol

**Goal:** Replace in-memory backends with production infrastructure. Add MCP interface for standard agent interoperability. Add vector search for semantic queries.

### Scope

| Step | What | Description |
|------|------|-------------|
| **17** | Neo4j backend | `GraphStore` implementation backed by Neo4j. Same interface, Cypher queries under the hood. `graph_backend: neo4j` config switch. Migration path from in-memory. |
| **18** | Vector store integration | Qdrant (or Chroma) for episode embeddings. `query()` gains a semantic mode: embed the query, find similar subgraphs by vector similarity, merge with graph traversal results. |
| **19** | MCP tool interface | Expose NeuroWeave as an MCP server with tools: `em_query`, `em_report_interaction`, `em_get_context`, `em_graph_snapshot`. Any MCP-compatible agent runtime can connect. |
| **20** | Redis event streaming | Replace `asyncio.Queue` events with Redis Streams. Enables multi-process consumers, persistent event history, consumer groups for at-least-once delivery. |
| **21** | Background workers | APScheduler-based workers for: confidence decay (edges lose confidence without reinforcement), fact revision (re-verify public facts against web), and inference (cross-context pattern discovery via LLM). |
| **22** | Multi-stage extraction pipeline | Evolve the single LLM call into the 7-stage pipeline from the architecture docs: entity extraction → relation extraction → sentiment/hedging → temporal scoping → confidence scoring → hallucination detection → graph diff. Each stage independently testable and tunable. |
| **23** | Docker Compose | `docker-compose.yml` with Neo4j, Redis, Qdrant, and NeuroWeave. `docker compose up` for one-command development setup. |
| **24** | CI/CD | GitHub Actions workflow: lint, test (unit + integration), build, publish to PyPI on tag. |

### Architecture After Phase 2

```
┌───────────────────────────────────────────────────────────────────┐
│  Agent Process                                                     │
│                                                                   │
│  ┌──────────┐   ┌──────────┐   ┌──────────────────────────────┐  │
│  │ Agent LLM │   │ MCP      │   │ Direct Python API            │  │
│  │           │   │ Client   │   │ (async with NeuroWeave(...)) │  │
│  └─────┬─────┘   └────┬─────┘   └──────────────┬──────────────┘  │
│        │              │                         │                  │
│        │         ┌────▼─────────────────────────▼──────────┐      │
│        │         │          NeuroWeave Service              │      │
│        │         │                                         │      │
│        │         │  ┌──────────┐  ┌───────────────────┐   │      │
│        │         │  │ Extraction│  │   Query Engine     │   │      │
│        │         │  │ Pipeline  │  │ (Structured + NL   │   │      │
│        │         │  │ (7-stage) │  │  + Semantic Vector) │   │      │
│        │         │  └─────┬─────┘  └──────────┬─────────┘   │      │
│        │         │        │                   │              │      │
│        │         │  ┌─────▼───────────────────▼──────────┐  │      │
│        │         │  │          Neo4j + Qdrant             │  │      │
│        │         │  └─────────────────┬──────────────────┘  │      │
│        │         │                    │                      │      │
│        │         │  ┌─────────────────▼──────────────────┐  │      │
│        │         │  │     Redis Streams (Events)          │  │      │
│        │         │  └─────────────────┬──────────────────┘  │      │
│        │         │                    │                      │      │
│        │         │  ┌─────────────────▼──────────────────┐  │      │
│        │         │  │     Background Workers              │  │      │
│        │         │  │  (Decay, Revision, Inference)       │  │      │
│        │         │  └────────────────────────────────────┘  │      │
│        │         └─────────────────────────────────────────┘      │
└────────┼──────────────────────────────────────────────────────────┘
         │
         ▼
       User
```

### v0.2.0 Validation Criteria

1. `graph_backend: neo4j` — graph persists across restarts
2. Semantic queries return relevant results via vector similarity
3. MCP-compatible agents connect and use NeuroWeave tools
4. Events delivered via Redis Streams to multiple consumers
5. Confidence decay runs on schedule, stale edges archived
6. 7-stage extraction pipeline improves precision over single-call
7. `docker compose up` starts the full stack
8. CI/CD pipeline: push → lint → test → publish

---

## Implementation Order Summary

```
POC (Steps 1–9)                  ✅ COMPLETE
│
├── Phase 1 — v0.1.0 (Steps 10–16) ✅ COMPLETE
│   │
│   ├── Step 10: Async refactor              ✅
│   ├── Step 11: Structured query engine      ✅
│   ├── Step 12: Natural language query       ✅
│   ├── Step 13: Event subscription system    ✅
│   ├── Step 14: NeuroWeave facade            ✅
│   ├── Step 15: Demo agent + integration     ✅
│   └── Step 16: Package publishing prep      ✅
│
└── Phase 2 — v0.2.0 (Steps 17–24)
    │
    ├── Step 17: Neo4j backend
    ├── Step 18: Vector store (Qdrant)
    ├── Step 19: MCP tool interface
    ├── Step 20: Redis event streaming
    ├── Step 21: Background workers
    ├── Step 22: Multi-stage extraction pipeline
    ├── Step 23: Docker Compose
    └── Step 24: CI/CD
```

### Dependency Chain

```
Step 10 (async) ──┬── Step 11 (structured query) ── Step 12 (NL query) ──┐
                  │                                                       │
                  ├── Step 13 (events) ──────────────────────────────────┤
                  │                                                       │
                  └───────────────────────────────── Step 14 (facade) ◄──┘
                                                        │
                                                   Step 15 (demo agent)
                                                        │
                                                   Step 16 (publish)
```

Steps 11, 12, and 13 can be developed in parallel after Step 10. Step 14 integrates all three. Steps 15 and 16 are sequential finishing work.
