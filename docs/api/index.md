# API Reference

This section provides auto-generated documentation from the NeuroWeave source code.

## Core API

The main entry point for library consumers:

| Class | Module | Description |
|-------|--------|-------------|
| [`NeuroWeave`](neuroweave.md) | `neuroweave.api` | The public API facade — start here |
| [`ProcessResult`](neuroweave.md#neuroweave.api.ProcessResult) | `neuroweave.api` | Result of processing a message |
| [`ContextResult`](neuroweave.md#neuroweave.api.ContextResult) | `neuroweave.api` | Combined process + query result |
| [`QueryResult`](graph-store.md#neuroweave.graph.query.QueryResult) | `neuroweave.graph.query` | Structured query results |

## Supporting Modules

| Module | Description |
|--------|-------------|
| [Graph Store](graph-store.md) | `GraphStore`, query engine, NL query planner |
| [Extraction](extraction.md) | LLM clients, extraction pipeline |
| [Events](events.md) | `EventBus` pub/sub system |

## Top-Level Imports

Everything you need is available from the top-level package:

```python
from neuroweave import (
    NeuroWeave,      # Main API facade
    ProcessResult,   # Extraction result + graph delta
    ContextResult,   # Process + query combined
    QueryResult,     # Query results with nodes and edges
    EventType,       # Event type enum for subscription filtering
)
```
