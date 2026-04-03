# Changelog

All notable changes to NeuroWeave will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2026-04-03

### Summary

Major feature release adding persistent storage backends, scientific knowledge graph
support, bulk document ingestion, vector search integration, and cross-session
entity deduplication.

### Added

**NW-001 — Persistent Graph Backend (Neo4j)**

- `AbstractGraphStore` ABC — common interface for all graph backends.
- `MemoryGraphStore` — existing in-memory backend, now extends `AbstractGraphStore`.
- `Neo4jGraphStore` — persistent graph backend using Neo4j (optional dependency).
- `_build_graph_store()` factory in API — selects backend from `graph_backend` config.
- Neo4j config fields: `neo4j_uri`, `neo4j_user`, `neo4j_password`, `neo4j_database`.
- `GraphBackend` enum extended with `NEO4J` and `POSTGRESQL` (reserved).

**NW-002 — Scientific Entity Schema**

- 12 new `NodeType` values: `THEOREM`, `LEMMA`, `CONJECTURE`, `PROOF`, `DEFINITION`,
  `EXAMPLE`, `PAPER`, `AUTHOR`, `DOMAIN`, `MATH_OBJECT`, `OPEN_PROBLEM`, `ALGORITHM`.
- `RelationType` enum with 18 typed scientific relations (e.g. `PROVES`, `CITES`,
  `FOLLOWS_FROM`, `BELONGS_TO`).
- Scientific extraction prompt (`_SCIENTIFIC_SYSTEM_PROMPT`) for mathematical text.
- `ExtractionPipeline` now accepts `mode` parameter (`"general"` | `"scientific"`).
- `query_by_type()` — query all nodes of a given type with optional relation filter.
- `get_proof_chain()` — traverse theorem dependency chains.
- `get_domain_graph()` — retrieve all entities belonging to a mathematical domain.
- `extraction_mode` config field.

**NW-003 — Bulk Document Ingestion**

- `DocumentIngester` — chunks full documents and extracts concurrently.
- `ChunkStrategy` enum: `PARAGRAPH`, `FIXED`, `SECTION`, `SENTENCE`.
- `DocumentIngestionResult` — result with entity/relation counts and timing.
- `NeuroWeave.ingest_document()` facade method.
- Short chunk merging to avoid tiny extraction windows.

**NW-004 — Qdrant Integration Bridge**

- `QdrantBridge` — combines graph traversal with Qdrant vector similarity search.
- `VectorContextResult` — merged result from graph + vector with deduplicated names.
- `NeuroWeave.get_context_with_vectors()` facade method.
- Concurrent graph + vector search via `asyncio.gather()`.
- `upsert_node_vectors()` — store node embeddings in Qdrant.
- Optional dependency: `qdrant-client>=1.9`.

**NW-005 — Node Merge / Deduplication**

- Cross-session entity deduplication via `_resolve_entity_name()`.
- `update_node_properties()` — merge new properties into existing nodes (new wins).
- Property merging on entity reuse during ingestion.
- `NODE_UPDATED` events emitted on property merge.

**NW-006 — Configuration & Exports**

- All new public symbols exported from `neuroweave.__init__` and `__all__`.
- Updated `config/default.yaml` with all new fields.
- Optional dependency groups: `neo4j`, `qdrant`.

### Changed

- `ExtractionPipeline.__init__` now accepts `mode` and `confidence_threshold` parameters.
- `ingest_extraction()` uses cross-session dedup (queries persistent store).
- Entity type mapping extended with all scientific types.

### Testing

- 377 tests total (313 original + 64 new) across 20 test files.
- New test files: `test_neo4j_backend.py`, `test_scientific_schema.py`,
  `test_document_ingestion.py`, `test_qdrant_bridge.py`, `test_deduplication.py`.

---

## [0.1.0] — 2026-02-17

### Summary

First public release. NeuroWeave is an async Python library that transforms AI
conversations into a live knowledge graph. This release includes the full
extraction pipeline, graph store, structured and natural language queries,
event subscription, and an optional real-time visualization server.

### Added

**Public API (`neuroweave.api`)**

- `NeuroWeave` facade class — the single entry point for library consumers.
  - `async process(message)` — extract entities and relations, update the graph.
  - `async query(...)` — structured or natural language graph queries.
  - `async get_context(message)` — process + query combined (the primary integration point).
  - `subscribe()` / `unsubscribe()` — event-driven notifications on graph mutations.
  - `from_config(path)` — YAML-based configuration.
  - Async context manager support (`async with NeuroWeave(...) as nw:`).
- `ProcessResult` — extraction details and graph delta.
- `ContextResult` — extraction + relevant graph context in one response.
- `QueryResult` — structured query results with nodes, edges, and metadata.
- `EventType` — event type enum for subscription filtering.

**Extraction Pipeline (`neuroweave.extraction`)**

- LLM-powered entity and relation extraction from conversational messages.
- `LLMClient` protocol — supports Anthropic (Claude) and mock implementations.
- JSON repair layer — handles markdown fences, trailing commas, truncated output.
- Defensive parsing — malformed LLM output never crashes the pipeline.

**Graph Store (`neuroweave.graph`)**

- In-memory knowledge graph backed by NetworkX `MultiDiGraph`.
- Node deduplication by name (case-insensitive).
- `query_subgraph()` — structured queries with entity resolution, hop traversal,
  relation filtering, and confidence thresholds.
- `NLQueryPlanner` — translates natural language questions into structured queries
  via LLM, with schema injection and fallback to broad search.
- `ingest_extraction()` — bridges extraction results into graph mutations.

**Event System (`neuroweave.events`)**

- `EventBus` — async pub/sub with type filtering, timeout monitoring, and error isolation.
- Non-blocking emission via `asyncio.create_task()`.
- Graph store emits `NODE_ADDED`, `NODE_UPDATED`, `EDGE_ADDED`, `EDGE_UPDATED` events.

**Visualization Server (`neuroweave.server`)**

- FastAPI-based Cytoscape.js graph visualizer at `localhost:8787`.
- WebSocket live updates — graph re-layouts with animation as nodes/edges are added.
- Full graph snapshot on WebSocket connect.
- Can be started standalone or mounted alongside agent routes via `create_visualization_app()`.

**Configuration (`neuroweave.config`)**

- Three-tier configuration: field defaults → YAML → environment variables.
- Pydantic-based validation with typed settings.
- `NEUROWEAVE_` prefixed env vars override all settings.

**Logging (`neuroweave.logging`)**

- Structured logging via structlog.
- Console (colored, human-readable) and JSON (machine-parseable) output modes.

**CLI**

- `neuroweave` command — interactive terminal conversation loop with live visualization.

**Demo & Examples**

- `examples/demo_agent.py` — self-contained demo showing NeuroWeave integration.
  Runs with mock LLM (no API key needed) or Anthropic. Includes canned demo and
  interactive modes.

**Testing**

- ~308 tests across 16 test files covering all components.
- Integration tests verify the full flow: 5-message corpus → graph with 9 nodes,
  9 edges → structured and NL queries return expected results.

### Dependencies

- Python 3.11+
- anthropic ≥0.42, networkx ≥3.2, fastapi ≥0.115, structlog ≥25.5
- Full list in `pyproject.toml`

[0.1.0]: https://github.com/neuroweave/neuroweave/releases/tag/v0.1.0
