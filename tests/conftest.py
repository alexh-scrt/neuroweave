"""Shared test fixtures for NeuroWeave."""

import pytest

from neuroweave.config import NeuroWeaveConfig
from neuroweave.graph.store import GraphStore, NodeType, make_edge, make_node
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
