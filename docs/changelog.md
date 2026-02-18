# Changelog

For the full changelog, see [CHANGELOG.md](https://github.com/neuroweave/neuroweave/blob/main/CHANGELOG.md) in the repository.

## [0.1.0] — 2026-02-17

First public release. NeuroWeave is an async Python library that transforms AI conversations into a live knowledge graph.

### Highlights

- **`NeuroWeave` facade class** — the single entry point with `process()`, `query()`, and `get_context()` methods.
- **LLM-powered extraction** — entities and relations extracted from conversational messages via Claude or mock LLM.
- **Structured and NL queries** — query by entity names and filters, or ask natural language questions.
- **Event subscription** — async pub/sub for real-time graph mutation notifications.
- **Cytoscape.js visualization** — optional browser-based graph viewer with WebSocket live updates.
- **~308 tests** across 16 test files with full integration coverage.
- **Typed** — full type annotations and PEP 561 `py.typed` marker.

### Dependencies

Python 3.11+, anthropic ≥0.42, networkx ≥3.2, fastapi ≥0.115, structlog ≥25.5.
