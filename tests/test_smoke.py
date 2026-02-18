"""Smoke test — validates that the package installs, imports, and core wiring works."""

import neuroweave
from neuroweave.extraction.llm_client import MockLLMClient
from neuroweave.extraction.pipeline import ExtractionPipeline
from neuroweave.graph.store import GraphStore
from neuroweave.main import process_message


def test_version():
    assert neuroweave.__version__ == "0.1.0"


async def test_process_message_wiring():
    """The core loop — message → extraction → graph — works end to end."""
    mock = MockLLMClient()
    mock.set_response("i love python", {
        "entities": [
            {"name": "User", "entity_type": "person"},
            {"name": "Python", "entity_type": "tool"},
        ],
        "relations": [
            {"source": "User", "target": "Python", "relation": "prefers", "confidence": 0.90},
        ],
    })

    pipeline = ExtractionPipeline(mock)
    store = GraphStore()

    stats = await process_message("I love Python", pipeline, store)

    assert stats["entities_extracted"] == 2
    assert stats["relations_extracted"] == 1
    assert stats["nodes_added"] == 2
    assert stats["edges_added"] == 1
    assert store.node_count == 2
    assert store.edge_count == 1
