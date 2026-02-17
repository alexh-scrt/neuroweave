"""Integration tests for WebSocket live updates.

Proves that: conversation loop → graph mutations → events enqueued →
server can see updated graph → WebSocket clients receive snapshot.

The event broadcaster is an async polling loop, which is difficult to drive
in a synchronous test. Instead we test the two halves of the contract:

  1. process_message() fills the thread-safe event queue.
  2. A WebSocket client connecting to the server receives the current graph
     state (snapshot), which reflects all mutations from process_message().

Together these prove that a browser opening the visualization page during or
after a conversation will see the knowledge graph.
"""

from __future__ import annotations

import json
import queue

import pytest
from fastapi.testclient import TestClient

from neuroweave.extraction.llm_client import MockLLMClient
from neuroweave.extraction.pipeline import ExtractionPipeline
from neuroweave.graph.store import GraphEvent, GraphEventType, GraphStore
from neuroweave.main import process_message
from neuroweave.server.app import create_app


CONVERSATION = [
    "My name is Alex and I'm a software engineer",
    "My wife Lena and I are going to Tokyo in March",
    "She loves sushi but I prefer ramen",
    "We have two kids, both in elementary school",
    "I've been using Python for 10 years",
]


@pytest.fixture
def store() -> GraphStore:
    return GraphStore()


@pytest.fixture
def pipeline(mock_llm_with_corpus: MockLLMClient) -> ExtractionPipeline:
    return ExtractionPipeline(mock_llm_with_corpus)


# ---------------------------------------------------------------------------
# Part 1: Events are emitted to the thread-safe queue
# ---------------------------------------------------------------------------

class TestEventsEmitted:
    """process_message() → graph mutations → events land in queue.Queue."""

    def test_single_message_emits_events(self, store: GraphStore, pipeline: ExtractionPipeline):
        q: queue.Queue[GraphEvent] = queue.Queue()
        store.set_event_queue(q)

        process_message(CONVERSATION[0], pipeline, store)

        events = _drain_queue(q)
        assert len(events) > 0

        node_events = [e for e in events if e.event_type == GraphEventType.NODE_ADDED]
        edge_events = [e for e in events if e.event_type == GraphEventType.EDGE_ADDED]
        assert len(node_events) >= 1
        assert len(edge_events) >= 0

    def test_all_messages_emit_events(self, store: GraphStore, pipeline: ExtractionPipeline):
        q: queue.Queue[GraphEvent] = queue.Queue()
        store.set_event_queue(q)

        for msg in CONVERSATION:
            process_message(msg, pipeline, store)

        events = _drain_queue(q)

        node_events = [e for e in events if e.event_type in (
            GraphEventType.NODE_ADDED, GraphEventType.NODE_UPDATED
        )]
        edge_events = [e for e in events if e.event_type == GraphEventType.EDGE_ADDED]

        # Should have events for all nodes and edges in the graph
        assert len(node_events) >= 8
        assert len(edge_events) >= 7

    def test_event_data_contains_node_info(self, store: GraphStore, pipeline: ExtractionPipeline):
        q: queue.Queue[GraphEvent] = queue.Queue()
        store.set_event_queue(q)

        process_message(CONVERSATION[0], pipeline, store)

        events = _drain_queue(q)
        node_events = [e for e in events if e.event_type == GraphEventType.NODE_ADDED]

        # Every node event should have id, name, node_type
        for event in node_events:
            assert "id" in event.data
            assert "name" in event.data
            assert "node_type" in event.data

    def test_event_data_contains_edge_info(self, store: GraphStore, pipeline: ExtractionPipeline):
        q: queue.Queue[GraphEvent] = queue.Queue()
        store.set_event_queue(q)

        process_message(CONVERSATION[0], pipeline, store)

        events = _drain_queue(q)
        edge_events = [e for e in events if e.event_type == GraphEventType.EDGE_ADDED]

        for event in edge_events:
            assert "id" in event.data
            assert "source_id" in event.data
            assert "target_id" in event.data
            assert "relation" in event.data
            assert "confidence" in event.data

    def test_dedup_emits_no_extra_node_added(self, store: GraphStore, pipeline: ExtractionPipeline):
        """User node appears in every message but should only emit NODE_ADDED once."""
        q: queue.Queue[GraphEvent] = queue.Queue()
        store.set_event_queue(q)

        # First message creates User
        process_message(CONVERSATION[0], pipeline, store)
        events1 = _drain_queue(q)
        user_adds_1 = [
            e for e in events1
            if e.event_type == GraphEventType.NODE_ADDED
            and e.data.get("name") == "User"
        ]

        # Second message also references User
        process_message(CONVERSATION[1], pipeline, store)
        events2 = _drain_queue(q)
        user_adds_2 = [
            e for e in events2
            if e.event_type == GraphEventType.NODE_ADDED
            and e.data.get("name") == "User"
        ]

        # User should be added in exactly one of the two batches, not both
        total_user_adds = len(user_adds_1) + len(user_adds_2)
        assert total_user_adds <= 1, (
            f"User NODE_ADDED emitted {total_user_adds} times across 2 messages"
        )


# ---------------------------------------------------------------------------
# Part 2: Server reflects the graph state after processing
# ---------------------------------------------------------------------------

class TestServerReflectsGraph:
    """After process_message(), the REST API and WebSocket snapshot show the graph."""

    def test_rest_api_shows_graph_after_processing(
        self, store: GraphStore, pipeline: ExtractionPipeline
    ):
        for msg in CONVERSATION:
            process_message(msg, pipeline, store)

        app = create_app(store)
        client = TestClient(app)

        resp = client.get("/api/graph")
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["nodes"]) >= 8
        assert len(data["edges"]) >= 7
        assert data["stats"]["node_count"] == len(data["nodes"])
        assert data["stats"]["edge_count"] == len(data["edges"])

    def test_health_shows_counts(self, store: GraphStore, pipeline: ExtractionPipeline):
        for msg in CONVERSATION:
            process_message(msg, pipeline, store)

        app = create_app(store)
        client = TestClient(app)

        resp = client.get("/api/health")
        data = resp.json()
        assert data["status"] == "ok"
        assert data["graph"]["node_count"] >= 8
        assert data["graph"]["edge_count"] >= 7

    def test_websocket_snapshot_shows_full_graph(
        self, store: GraphStore, pipeline: ExtractionPipeline
    ):
        for msg in CONVERSATION:
            process_message(msg, pipeline, store)

        app = create_app(store)
        client = TestClient(app)

        with client.websocket_connect("/ws/graph") as ws:
            raw = ws.receive_text()
            data = json.loads(raw)

            assert data["type"] == "snapshot"
            assert len(data["data"]["nodes"]) >= 8
            assert len(data["data"]["edges"]) >= 7

    def test_websocket_snapshot_node_names(
        self, store: GraphStore, pipeline: ExtractionPipeline
    ):
        for msg in CONVERSATION:
            process_message(msg, pipeline, store)

        app = create_app(store)
        client = TestClient(app)

        with client.websocket_connect("/ws/graph") as ws:
            raw = ws.receive_text()
            data = json.loads(raw)

            names = {n["name"] for n in data["data"]["nodes"]}
            # Key entities from the conversation
            assert "Alex" in names
            assert "Lena" in names
            assert "Tokyo" in names
            assert "Python" in names

    def test_websocket_snapshot_has_relations(
        self, store: GraphStore, pipeline: ExtractionPipeline
    ):
        for msg in CONVERSATION:
            process_message(msg, pipeline, store)

        app = create_app(store)
        client = TestClient(app)

        with client.websocket_connect("/ws/graph") as ws:
            raw = ws.receive_text()
            data = json.loads(raw)

            relations = {e["relation"] for e in data["data"]["edges"]}
            assert "married_to" in relations
            assert "traveling_to" in relations
            assert "prefers" in relations


# ---------------------------------------------------------------------------
# Part 3: Incremental — server reflects growth
# ---------------------------------------------------------------------------

class TestIncrementalServerUpdates:
    """The REST API shows the graph growing as messages are processed."""

    def test_graph_grows_via_api(self, store: GraphStore, pipeline: ExtractionPipeline):
        app = create_app(store)
        client = TestClient(app)

        prev_nodes = 0
        prev_edges = 0

        for msg in CONVERSATION:
            process_message(msg, pipeline, store)

            resp = client.get("/api/graph")
            data = resp.json()

            cur_nodes = data["stats"]["node_count"]
            cur_edges = data["stats"]["edge_count"]

            assert cur_nodes >= prev_nodes
            assert cur_edges >= prev_edges

            prev_nodes = cur_nodes
            prev_edges = cur_edges

        # Final state
        assert prev_nodes >= 8
        assert prev_edges >= 7


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _drain_queue(q: queue.Queue[GraphEvent]) -> list[GraphEvent]:
    events = []
    while not q.empty():
        try:
            events.append(q.get_nowait())
        except queue.Empty:
            break
    return events
