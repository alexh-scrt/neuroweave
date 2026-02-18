# NeuroWeave

**Real-time knowledge graph memory for agentic AI platforms.**

*Agents that learn. Memory that compounds. Privacy that's provable.*

---

## What is NeuroWeave?

NeuroWeave is an async Python library that transforms AI conversations into a **live knowledge graph**. As a user chats with an AI agent, NeuroWeave extracts entities and relationships from each message and materializes them into a graph that grows over time. Agents can then query this graph to recall facts, preferences, and connections — giving them persistent, structured memory.

```python
from neuroweave import NeuroWeave

async with NeuroWeave(llm_provider="anthropic") as nw:
    # Agent feeds user messages — graph builds automatically
    await nw.process("My wife Lena and I are going to Tokyo in March")
    await nw.process("She loves sushi but I prefer ramen")

    # Later, query for relevant context
    result = await nw.query("what does my wife like?")
    # → Lena, sushi (with confidence scores and graph structure)
```

## Key Features

- **Extract** — LLM-powered entity and relation extraction from conversational messages.
- **Store** — In-memory knowledge graph (NetworkX) with entity deduplication.
- **Query** — Structured queries with hop traversal, or natural language questions translated by LLM.
- **Events** — Async pub/sub for real-time notifications on graph mutations.
- **Visualize** — Optional Cytoscape.js browser UI with WebSocket live updates.
- **Typed** — Full type annotations and PEP 561 `py.typed` marker.

## Quick Example

```python
import asyncio
from neuroweave import NeuroWeave

async def main():
    async with NeuroWeave(llm_provider="mock") as nw:  # no API key needed
        # Build the graph
        await nw.process("My name is Alex and I'm a software engineer")
        await nw.process("My wife Lena loves sushi")

        # Query it
        result = await nw.query(["Lena"], relations=["prefers"], max_hops=1)
        print(result.node_names())  # ['Lena', 'sushi']

        # Or use natural language
        result = await nw.query("what does my wife like?")

        # Combined: process + query in one call
        context = await nw.get_context("remind me about dinner plans")
        print(context.relevant.node_names())

asyncio.run(main())
```

## Installation

```bash
pip install neuroweave
```

Or install from source:

```bash
git clone https://github.com/neuroweave/neuroweave.git
cd neuroweave
pip install -e ".[dev]"
```

## Next Steps

- [Getting Started](getting-started.md) — Installation, configuration, and first steps.
- [User Guide](user-guide/configuration.md) — Configuration, queries, events, and visualization.
- [API Reference](api/index.md) — Full API documentation.
- [Architecture](architecture.md) — System design and component breakdown.
