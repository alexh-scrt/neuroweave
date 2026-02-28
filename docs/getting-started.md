# Getting Started

This guide walks you through installing NeuroWeave, configuring an LLM backend, and running your first knowledge graph session.

## Prerequisites

- **Python 3.11+**
- An **Anthropic API key** (optional — use mock mode for zero-cost testing)

## Installation

### From PyPI

```bash
pip install neuroweave-python
```

### From Source (development)

```bash
git clone https://github.com/alexh-scrt/neuroweave.git
cd neuroweave
pip install -e ".[dev]"
```

## Your First Session

### Option 1: Mock Mode (no API key)

```python
import asyncio
from neuroweave import NeuroWeave

async def main():
    async with NeuroWeave(llm_provider="mock") as nw:
        result = await nw.process("My wife Lena loves sushi")
        print(f"Extracted {result.entity_count} entities, {result.relation_count} relations")
        print(f"Graph: {nw.graph.node_count} nodes, {nw.graph.edge_count} edges")

asyncio.run(main())
```

!!! note
    The mock LLM returns empty extractions for unknown messages. Register
    canned responses for deterministic testing — see the
    [demo agent](https://github.com/alexh-scrt/neuroweave/blob/main/examples/demo_agent.py)
    for an example.

### Option 2: With Anthropic Claude

```python
import asyncio
from neuroweave import NeuroWeave

async def main():
    async with NeuroWeave(
        llm_provider="anthropic",
        llm_api_key="sk-ant-...",
        llm_model="claude-haiku-4-5-20251001",
    ) as nw:
        result = await nw.process("My wife Lena and I are going to Tokyo in March")
        print(f"Extracted {result.entity_count} entities")

        context = await nw.get_context("She loves sushi but I prefer ramen")
        print(f"Relevant context: {context.relevant.node_names()}")

asyncio.run(main())
```

### Option 3: CLI Mode

```bash
# With real LLM
export NEUROWEAVE_LLM_API_KEY=sk-ant-...
neuroweave

# With mock LLM
NEUROWEAVE_LLM_PROVIDER=mock neuroweave
```

This starts an interactive terminal loop with a live graph visualizer at
[http://127.0.0.1:8787](http://127.0.0.1:8787).

## The Three API Paths

NeuroWeave has three main methods, corresponding to write, read, and combined flows:

### Write: `process()`

Extract knowledge from a message and update the graph.

```python
result = await nw.process("My name is Alex and I'm a software engineer")
print(result.entity_count)    # Number of entities extracted
print(result.nodes_added)     # New nodes added to the graph
print(result.edges_added)     # New edges added to the graph
```

### Read: `query()`

Query the knowledge graph. Accepts structured parameters or natural language.

```python
# Structured query
result = await nw.query(["Lena"], relations=["prefers"], max_hops=1)

# Natural language query (auto-detected from string input)
result = await nw.query("what does my wife like?")

# Whole-graph query
result = await nw.query()
```

### Combined: `get_context()`

Process a message AND query for relevant context — in one call. This is the primary integration point for agents.

```python
context = await nw.get_context("remind me about dinner plans")

# What was extracted from this specific message
print(context.process.entity_count)

# Relevant knowledge from the entire graph
print(context.relevant.node_names())

# The query plan used (for debugging)
print(context.plan.reasoning)
```

## Running the Demo

NeuroWeave ships with a self-contained demo agent:

```bash
# Canned demo (no API key needed)
python examples/demo_agent.py

# Interactive mode
python examples/demo_agent.py --interactive

# With Anthropic
python examples/demo_agent.py --provider anthropic
```

## Running the Tests

```bash
make test           # All ~308 tests
make test-cov       # With coverage report
make lint           # Ruff linting
```

## Next Steps

- [Configuration](user-guide/configuration.md) — YAML files, environment variables, all settings.
- [Querying the Graph](user-guide/queries.md) — Structured and natural language queries.
- [Event Subscription](user-guide/events.md) — Real-time notifications on graph changes.
- [Visualization](user-guide/visualization.md) — Browser-based graph viewer.
