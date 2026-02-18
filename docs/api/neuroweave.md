# NeuroWeave API

The main entry point for library consumers.

## NeuroWeave

::: neuroweave.api.NeuroWeave
    options:
      members:
        - __init__
        - from_config
        - start
        - stop
        - process
        - query
        - get_context
        - subscribe
        - unsubscribe
        - create_visualization_app
        - graph
        - event_bus
        - is_started

## ProcessResult

::: neuroweave.api.ProcessResult
    options:
      members:
        - extraction
        - nodes_added
        - edges_added
        - edges_skipped
        - entity_count
        - relation_count
        - to_dict

## ContextResult

::: neuroweave.api.ContextResult
    options:
      members:
        - process
        - relevant
        - plan
        - to_dict
