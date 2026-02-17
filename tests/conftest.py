"""Shared test fixtures for NeuroWeave."""

import pytest

from neuroweave.config import NeuroWeaveConfig
from neuroweave.extraction.llm_client import MockLLMClient
from neuroweave.extraction.pipeline import ExtractionPipeline
from neuroweave.graph.store import GraphStore
from neuroweave.logging import configure_logging


@pytest.fixture
def test_config() -> NeuroWeaveConfig:
    """Config with mock LLM provider — no real API calls."""
    return NeuroWeaveConfig(llm_provider="mock", log_level="DEBUG", log_format="json")


@pytest.fixture(autouse=True)
def _setup_logging(test_config: NeuroWeaveConfig) -> None:
    """Ensure structured logging is configured for all tests."""
    configure_logging(test_config)


@pytest.fixture
def graph_store() -> GraphStore:
    """Fresh empty graph store."""
    return GraphStore()


@pytest.fixture
def mock_llm_with_corpus() -> MockLLMClient:
    """MockLLMClient pre-loaded with the standard 5-message conversation corpus.

    This is the shared corpus used by both test_extraction.py and test_e2e.py.
    """
    mock = MockLLMClient()

    mock.set_response("my name is alex", {
        "entities": [
            {"name": "Alex", "entity_type": "person", "properties": {"is_user": True}},
            {"name": "software engineering", "entity_type": "concept"},
        ],
        "relations": [
            {"source": "User", "target": "Alex", "relation": "named", "confidence": 0.95},
            {"source": "User", "target": "software engineering", "relation": "occupation", "confidence": 0.90},
        ],
    })

    mock.set_response("going to tokyo in march", {
        "entities": [
            {"name": "User", "entity_type": "person"},
            {"name": "Lena", "entity_type": "person"},
            {"name": "Tokyo", "entity_type": "place"},
        ],
        "relations": [
            {"source": "User", "target": "Lena", "relation": "married_to", "confidence": 0.90},
            {"source": "User", "target": "Tokyo", "relation": "traveling_to", "confidence": 0.85,
             "properties": {"timeframe": "March 2026"}},
            {"source": "Lena", "target": "Tokyo", "relation": "traveling_to", "confidence": 0.85},
        ],
    })

    mock.set_response("loves sushi but i prefer ramen", {
        "entities": [
            {"name": "Lena", "entity_type": "person"},
            {"name": "User", "entity_type": "person"},
            {"name": "sushi", "entity_type": "concept"},
            {"name": "ramen", "entity_type": "concept"},
        ],
        "relations": [
            {"source": "Lena", "target": "sushi", "relation": "prefers", "confidence": 0.90},
            {"source": "User", "target": "ramen", "relation": "prefers", "confidence": 0.85},
        ],
    })

    mock.set_response("two kids", {
        "entities": [
            {"name": "User", "entity_type": "person"},
            {"name": "children", "entity_type": "person", "properties": {"count": 2, "school": "elementary"}},
        ],
        "relations": [
            {"source": "User", "target": "children", "relation": "has_children", "confidence": 0.90},
        ],
    })

    mock.set_response("using python for 10 years", {
        "entities": [
            {"name": "User", "entity_type": "person"},
            {"name": "Python", "entity_type": "tool"},
        ],
        "relations": [
            {"source": "User", "target": "Python", "relation": "experienced_with", "confidence": 0.90,
             "properties": {"duration": "10 years"}},
        ],
    })

    return mock


@pytest.fixture
def pipeline_with_corpus(mock_llm_with_corpus: MockLLMClient) -> ExtractionPipeline:
    """ExtractionPipeline wired to the standard test corpus."""
    return ExtractionPipeline(mock_llm_with_corpus)
