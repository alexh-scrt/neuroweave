"""Tests for the FastAPI visualization server."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from neuroweave.graph.store import GraphStore, NodeType, make_edge, make_node
from neuroweave.server.app import WebSocketManager, create_app


@pytest.fixture
def store() -> GraphStore:
    return GraphStore()


@pytest.fixture
def client(store: GraphStore) -> TestClient:
    app = create_app(store)
    return TestClient(app)


@pytest.fixture
def populated_store(store: GraphStore) -> GraphStore:
    store.add_node(make_node("Alex", NodeType.ENTITY, node_id="alex"))
    store.add_node(make_node("Python", NodeType.CONCEPT, node_id="python"))
    store.add_edge(make_edge("alex", "python", "prefers", 0.90, edge_id="e1"))
    return store


@pytest.fixture
def populated_client(populated_store: GraphStore) -> TestClient:
    app = create_app(populated_store)
    return TestClient(app)


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_returns_ok(self, client: TestClient):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["graph"]["node_count"] == 0
        assert data["websocket_clients"] == 0

    def test_reflects_graph_state(self, populated_client: TestClient):
        resp = populated_client.get("/api/health")
        data = resp.json()
        assert data["graph"]["node_count"] == 2
        assert data["graph"]["edge_count"] == 1


class TestGraphEndpoint:
    def test_empty_graph(self, client: TestClient):
        resp = client.get("/api/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert data["nodes"] == []
        assert data["edges"] == []
        assert data["stats"]["node_count"] == 0

    def test_returns_full_graph(self, populated_client: TestClient):
        resp = populated_client.get("/api/graph")
        data = resp.json()
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1
        assert data["stats"]["node_count"] == 2
        assert data["stats"]["edge_count"] == 1

    def test_node_fields(self, populated_client: TestClient):
        resp = populated_client.get("/api/graph")
        nodes = resp.json()["nodes"]
        node_names = {n["name"] for n in nodes}
        assert "Alex" in node_names
        assert "Python" in node_names
        for n in nodes:
            assert "id" in n
            assert "node_type" in n

    def test_edge_fields(self, populated_client: TestClient):
        resp = populated_client.get("/api/graph")
        edge = resp.json()["edges"][0]
        assert edge["relation"] == "prefers"
        assert edge["confidence"] == 0.90
        assert "source_id" in edge
        assert "target_id" in edge


class TestIndexPage:
    def test_serves_html(self, client: TestClient):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "NeuroWeave" in resp.text


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

class TestWebSocket:
    def test_snapshot_on_connect(self, populated_client: TestClient):
        with populated_client.websocket_connect("/ws/graph") as ws:
            data = json.loads(ws.receive_text())
            assert data["type"] == "snapshot"
            assert len(data["data"]["nodes"]) == 2
            assert len(data["data"]["edges"]) == 1

    def test_empty_snapshot_on_connect(self, client: TestClient):
        with client.websocket_connect("/ws/graph") as ws:
            data = json.loads(ws.receive_text())
            assert data["type"] == "snapshot"
            assert data["data"]["nodes"] == []


# ---------------------------------------------------------------------------
# WebSocketManager unit tests
# ---------------------------------------------------------------------------

class TestWebSocketManager:
    def test_initial_state(self):
        mgr = WebSocketManager()
        assert mgr.connection_count == 0
