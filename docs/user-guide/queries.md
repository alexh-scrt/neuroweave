# Querying the Graph

NeuroWeave supports two query modes — **structured** queries with explicit parameters, and **natural language** queries that an LLM translates into graph operations.

Both modes return a `QueryResult` containing matching nodes, edges, and traversal metadata.

## Structured Queries

Pass entity names as a list with optional filters:

```python
# Find Lena and her 1-hop neighbors
result = await nw.query(["Lena"])

# Filter by relation type
result = await nw.query(["Lena"], relations=["prefers"], max_hops=1)

# Multiple entities with confidence filter
result = await nw.query(["User", "Lena"], min_confidence=0.8, max_hops=2)

# Whole-graph query (no entity filter)
result = await nw.query()
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `text_or_entities` | `list[str]` \| `None` | `None` | Entity names to start from. `None` = whole graph. |
| `relations` | `list[str]` \| `None` | `None` | Only include edges with these relation types. |
| `min_confidence` | `float` | `0.0` | Minimum edge confidence to include. |
| `max_hops` | `int` | `1` | How many hops to traverse from seed entities. |

### Entity Resolution

Entity names are resolved case-insensitively. `"lena"`, `"Lena"`, and `"LENA"` all match the same node. If an entity name isn't found, it's silently skipped.

### Hop Traversal

Starting from matched entities, NeuroWeave walks outward along edges up to `max_hops` steps, collecting all nodes and edges encountered.

```
max_hops=0 → Just the seed entity, no neighbors.
max_hops=1 → Seed + direct neighbors.
max_hops=2 → Seed + neighbors + neighbors-of-neighbors.
```

## Natural Language Queries

Pass a string to trigger the NL query path:

```python
result = await nw.query("what does my wife like?")
result = await nw.query("where are we traveling?")
result = await nw.query("what do you know about me?")
```

The NL query planner:

1. Reads the current graph schema (entity names, relation types, node types).
2. Sends the question + schema to the LLM.
3. Parses the LLM's response into a structured query plan (entities, relations, hops).
4. Executes the plan against the graph store.
5. Falls back to a broad whole-graph search if the LLM returns unparseable output.

!!! tip
    NL queries work best when the graph has enough context for the LLM to
    understand the schema. After processing a few messages, the LLM can
    resolve references like "my wife" → Lena.

## Working with QueryResult

```python
result = await nw.query(["User"], max_hops=2)

# Node and edge counts
result.node_count
result.edge_count

# Is the result empty?
result.is_empty

# Get all node names
result.node_names()      # ['User', 'Lena', 'Tokyo', ...]

# Get all relation types used
result.relation_types()  # ['married_to', 'traveling_to', ...]

# Access raw data
result.nodes   # list of node dicts
result.edges   # list of edge dicts

# Serialize
result.to_dict()  # {'nodes': [...], 'edges': [...], 'metadata': {...}}
```

## Combined: `get_context()`

For agent integration, `get_context()` processes a message AND queries for relevant context in one call:

```python
context = await nw.get_context("remind me about dinner plans")

# What was extracted from this message
context.process.entity_count
context.process.nodes_added

# Relevant context from the graph
context.relevant.node_names()

# The NL query plan (for debugging)
context.plan.entities
context.plan.reasoning

# Serialize everything
context.to_dict()
```
