# Visualization

NeuroWeave includes an optional browser-based graph visualizer built with [Cytoscape.js](https://js.cytoscape.org/). It shows the knowledge graph updating in real time as entities and relations are extracted.

## Enabling Visualization

### Standalone Server

```python
async with NeuroWeave(
    llm_provider="mock",
    enable_visualization=True,
    server_host="127.0.0.1",
    server_port=8787,
) as nw:
    # Visualization available at http://127.0.0.1:8787
    await nw.process("My wife Lena loves sushi")
```

### Mounting Alongside Your Own Routes

If you already have a FastAPI application, you can mount the visualizer as a sub-application:

```python
from fastapi import FastAPI

app = FastAPI()

async with NeuroWeave(llm_provider="mock") as nw:
    viz_app = nw.create_visualization_app()
    app.mount("/viz", viz_app)
```

### CLI Mode

```bash
neuroweave  # Starts at http://127.0.0.1:8787 by default
```

## How It Works

The visualization server provides:

- **REST endpoint** `GET /api/graph` — Returns the full graph as JSON.
- **WebSocket** `ws://host:port/ws` — Pushes incremental updates as nodes and edges are added.
- **Static files** — Serves the Cytoscape.js single-page app.

On WebSocket connect, the browser receives a full graph snapshot. As the graph grows, the server pushes delta events that the frontend merges and re-layouts with animation.

## Features

- **Force-directed layout** — Nodes automatically arrange themselves.
- **Color coding** — Different colors for entity types (person, place, concept, etc.).
- **Edge labels** — Relation types displayed on edges.
- **Confidence opacity** — Lower confidence edges appear more transparent.
- **Live updates** — Graph re-layouts smoothly as new data arrives.

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `server_host` | `"127.0.0.1"` | Bind address |
| `server_port` | `8787` | Port number |
| `enable_visualization` | `false` | Start the server on `nw.start()` |
