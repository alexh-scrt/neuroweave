# Graph Store

The knowledge graph storage and query layer.

## GraphStore

::: neuroweave.graph.store.GraphStore
    options:
      members:
        - add_node
        - add_edge
        - get_node
        - get_edge
        - node_count
        - edge_count
        - to_dict
        - set_event_bus
        - set_event_queue

## Query Engine

### query_subgraph

::: neuroweave.graph.query.query_subgraph

### QueryResult

::: neuroweave.graph.query.QueryResult
    options:
      members:
        - nodes
        - edges
        - metadata
        - node_count
        - edge_count
        - is_empty
        - node_names
        - relation_types
        - to_dict

## NL Query Planner

### NLQueryPlanner

::: neuroweave.graph.nl_query.NLQueryPlanner
    options:
      members:
        - plan
        - execute
        - query

### QueryPlan

::: neuroweave.graph.nl_query.QueryPlan

## Ingestion

### ingest_extraction

::: neuroweave.graph.ingest.ingest_extraction

## Data Factories

::: neuroweave.graph.store.make_node

::: neuroweave.graph.store.make_edge
