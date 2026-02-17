"""FastAPI server — serves graph visualization UI and real-time WebSocket updates."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from neuroweave.graph.store import GraphEvent, GraphStore
from neuroweave.logging import get_logger

log = get_logger("server")

_STATIC_DIR = Path(__file__).resolve().parent.parent.parent.parent / "static"


class WebSocketManager:
    """Manages active WebSocket connections and broadcasts graph events."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        log.info("ws.client_connected", total=len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.remove(ws)
        log.info("ws.client_disconnected", total=len(self._connections))

    async def broadcast(self, data: dict[str, Any]) -> None:
        """Send data to all connected clients. Drops failed connections."""
        dead: list[WebSocket] = []
        message = json.dumps(data)
        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.remove(ws)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


# ---------------------------------------------------------------------------
# Event broadcaster — reads from GraphStore event queue, pushes to WebSockets
# ---------------------------------------------------------------------------

async def _event_broadcaster(
    queue: asyncio.Queue[GraphEvent],
    ws_manager: WebSocketManager,
    store: GraphStore,
) -> None:
    """Background task: consume graph events and broadcast to WebSocket clients."""
    while True:
        event = await queue.get()
        await ws_manager.broadcast({
            "type": event.event_type.value,
            "data": event.data,
            "stats": {
                "node_count": store.node_count,
                "edge_count": store.edge_count,
            },
        })


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(store: GraphStore) -> FastAPI:
    """Create the FastAPI app wired to a GraphStore.

    Args:
        store: The graph store to serve. Must already be the same instance
               used by the conversation loop.
    """
    ws_manager = WebSocketManager()
    event_queue: asyncio.Queue[GraphEvent] = asyncio.Queue(maxsize=1000)
    store.set_event_queue(event_queue)

    broadcaster_task: asyncio.Task | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal broadcaster_task
        broadcaster_task = asyncio.create_task(
            _event_broadcaster(event_queue, ws_manager, store)
        )
        log.info("server.started", static_dir=str(_STATIC_DIR))
        yield
        broadcaster_task.cancel()
        try:
            await broadcaster_task
        except asyncio.CancelledError:
            pass

    app = FastAPI(title="NeuroWeave Graph Visualizer", lifespan=lifespan)

    # --- Routes ---

    @app.get("/", response_class=HTMLResponse)
    async def index():
        index_path = _STATIC_DIR / "index.html"
        if index_path.exists():
            return FileResponse(index_path)
        return HTMLResponse("<h1>NeuroWeave</h1><p>static/index.html not found.</p>")

    @app.get("/api/graph")
    async def get_graph():
        return store.to_dict()

    @app.get("/api/health")
    async def health():
        return {
            "status": "ok",
            "graph": {
                "node_count": store.node_count,
                "edge_count": store.edge_count,
            },
            "websocket_clients": ws_manager.connection_count,
        }

    @app.websocket("/ws/graph")
    async def graph_websocket(ws: WebSocket):
        await ws_manager.connect(ws)
        # Send full graph snapshot on connect
        try:
            await ws.send_text(json.dumps({
                "type": "snapshot",
                "data": store.to_dict(),
            }))
            # Keep alive — wait for disconnect
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            ws_manager.disconnect(ws)

    # Mount static files (CSS, JS if we add any later)
    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    return app
