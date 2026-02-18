"""NeuroWeave public API — the main entry point for library consumers.

This module provides the `NeuroWeave` class that agents import and use.
It wires together the extraction pipeline, graph store, query engines,
event bus, and optional visualization server behind a clean async API.

Usage:
    from neuroweave import NeuroWeave

    async with NeuroWeave(llm_provider="mock") as nw:
        result = await nw.process("My wife Lena loves Malbec")
        context = await nw.get_context("what does my wife like?")
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

import uvicorn

from neuroweave.config import LLMProvider, LogFormat, NeuroWeaveConfig
from neuroweave.events import EventBus
from neuroweave.extraction.llm_client import (
    AnthropicLLMClient,
    LLMClient,
    MockLLMClient,
)
from neuroweave.extraction.pipeline import ExtractionPipeline, ExtractionResult
from neuroweave.graph.ingest import ingest_extraction
from neuroweave.graph.nl_query import NLQueryPlanner, QueryPlan
from neuroweave.graph.query import QueryResult, query_subgraph
from neuroweave.graph.store import GraphEvent, GraphEventType, GraphStore
from neuroweave.logging import configure_logging, get_logger

log = get_logger("api")

# Re-export EventType for convenience
EventType = GraphEventType

# Type alias for event handlers
EventHandler = Callable[[GraphEvent], Awaitable[None]]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """Result of processing a single message through the extraction pipeline.

    Attributes:
        extraction: Raw extraction result (entities, relations, timing).
        nodes_added: Number of new nodes created in the graph.
        edges_added: Number of new edges created in the graph.
        edges_skipped: Number of edges skipped (unknown entities, etc.).
    """

    extraction: ExtractionResult
    nodes_added: int = 0
    edges_added: int = 0
    edges_skipped: int = 0

    @property
    def entity_count(self) -> int:
        return len(self.extraction.entities)

    @property
    def relation_count(self) -> int:
        return len(self.extraction.relations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entities_extracted": self.entity_count,
            "relations_extracted": self.relation_count,
            "nodes_added": self.nodes_added,
            "edges_added": self.edges_added,
            "edges_skipped": self.edges_skipped,
            "extraction_ms": round(self.extraction.duration_ms, 1),
        }


@dataclass(frozen=True, slots=True)
class ContextResult:
    """Combined result of processing a message AND querying relevant context.

    This is the main return type for `get_context()` — the most common
    operation in agent integration.

    Attributes:
        process: What was extracted from this message.
        relevant: Knowledge graph context relevant to this message.
        plan: The NL query plan used (for debugging/transparency).
    """

    process: ProcessResult
    relevant: QueryResult
    plan: QueryPlan | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "process": self.process.to_dict(),
            "relevant": self.relevant.to_dict(),
            "plan": self.plan.to_dict() if self.plan else None,
        }


# ---------------------------------------------------------------------------
# NeuroWeave facade
# ---------------------------------------------------------------------------


class NeuroWeave:
    """The public API for NeuroWeave — knowledge graph memory for AI agents.

    NeuroWeave manages the full lifecycle: extraction pipeline, graph store,
    query engines, event bus, and optional visualization server. Agents
    interact through three main methods:

    - `process(message)` — Extract knowledge from a message, update the graph.
    - `query(...)` — Query the graph (structured or natural language).
    - `get_context(message)` — Process + query in one call (most common).

    Usage:
        # Programmatic construction
        nw = NeuroWeave(llm_provider="mock")
        await nw.start()
        context = await nw.get_context("My wife Lena loves sushi")
        await nw.stop()

        # Context manager (recommended)
        async with NeuroWeave(llm_provider="mock") as nw:
            context = await nw.get_context("My wife Lena loves sushi")

        # From config file
        async with NeuroWeave.from_config("config/default.yaml") as nw:
            ...
    """

    def __init__(
        self,
        *,
        llm_provider: str | None = None,
        llm_model: str | None = None,
        llm_api_key: str | None = None,
        enable_visualization: bool = False,
        server_host: str | None = None,
        server_port: int | None = None,
        log_level: str | None = None,
        log_format: str | None = None,
    ) -> None:
        # Build config from .env / env vars / YAML first, then overlay
        # any explicit kwargs. This ensures .env values are picked up for
        # any parameter not explicitly provided by the caller.
        base = NeuroWeaveConfig.load()
        overrides: dict[str, Any] = {}
        if llm_provider is not None:
            overrides["llm_provider"] = LLMProvider(llm_provider)
        if llm_model is not None:
            overrides["llm_model"] = llm_model
        if llm_api_key is not None:
            overrides["llm_api_key"] = llm_api_key
        if server_host is not None:
            overrides["server_host"] = server_host
        if server_port is not None:
            overrides["server_port"] = server_port
        if log_level is not None:
            overrides["log_level"] = log_level
        if log_format is not None:
            overrides["log_format"] = LogFormat(log_format)

        if overrides:
            self._config = base.model_copy(update=overrides)
        else:
            self._config = base

        self._enable_visualization = enable_visualization

        # Core components (initialized in start())
        self._store: GraphStore | None = None
        self._pipeline: ExtractionPipeline | None = None
        self._event_bus: EventBus | None = None
        self._nl_planner: NLQueryPlanner | None = None

        # Visualization server
        self._server_task: asyncio.Task | None = None

        # Lifecycle state
        self._started = False

    @classmethod
    def from_config(
        cls, path: str | Path, *, enable_visualization: bool = False,
    ) -> NeuroWeave:
        """Create a NeuroWeave instance from a YAML config file.

        The YAML file is loaded first, then `.env` and `NEUROWEAVE_*`
        environment variables are overlaid (env vars win).

        Args:
            path: Path to the YAML configuration file.
            enable_visualization: Whether to start the graph visualizer.

        Returns:
            NeuroWeave instance (not yet started — call start() or use as context manager).
        """
        config = NeuroWeaveConfig.load(Path(path))
        instance = cls.__new__(cls)
        instance._config = config
        instance._enable_visualization = enable_visualization
        instance._store = None
        instance._pipeline = None
        instance._event_bus = None
        instance._nl_planner = None
        instance._server_task = None
        instance._started = False
        return instance

    # -- Lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Initialize all components and optionally start the visualization server.

        This must be called before using process/query/get_context.
        Prefer using the async context manager instead of calling start/stop manually.
        """
        if self._started:
            return

        configure_logging(self._config)

        # Core components
        llm_client = _create_llm_client(self._config)
        self._store = GraphStore()
        self._pipeline = ExtractionPipeline(llm_client)
        self._event_bus = EventBus()
        self._nl_planner = NLQueryPlanner(llm_client, self._store)

        # Wire event bus to graph store
        self._store.set_event_bus(self._event_bus)

        # Optional visualization server
        if self._enable_visualization:
            await self._start_visualization_server()

        self._started = True
        log.info(
            "neuroweave.started",
            llm_provider=self._config.llm_provider.value,
            visualization=self._enable_visualization,
        )

    async def stop(self) -> None:
        """Gracefully shut down all components.

        Safe to call multiple times.
        """
        if not self._started:
            return

        if self._server_task is not None:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
            self._server_task = None

        self._started = False
        log.info("neuroweave.stopped")

    async def __aenter__(self) -> NeuroWeave:
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.stop()

    # -- Write path: process messages ---------------------------------------

    async def process(self, message: str) -> ProcessResult:
        """Extract knowledge from a message and update the graph.

        Args:
            message: A user's conversational message.

        Returns:
            ProcessResult with extraction details and graph delta.

        Raises:
            RuntimeError: If NeuroWeave hasn't been started.
        """
        self._ensure_started()

        extraction = await self._pipeline.extract(message)  # type: ignore[union-attr]
        stats = ingest_extraction(self._store, extraction)  # type: ignore[arg-type]

        return ProcessResult(
            extraction=extraction,
            nodes_added=stats["nodes_added"],
            edges_added=stats["edges_added"],
            edges_skipped=stats["edges_skipped"],
        )

    # -- Read path: query the graph -----------------------------------------

    async def query(
        self,
        text_or_entities: str | list[str] | None = None,
        *,
        relations: list[str] | None = None,
        min_confidence: float = 0.0,
        max_hops: int = 1,
    ) -> QueryResult:
        """Query the knowledge graph.

        Auto-detects the query mode:
        - **String input** → Natural language query (LLM translates to graph query).
        - **List input** → Structured query (entity names passed directly).
        - **None** → Whole-graph query.

        Args:
            text_or_entities: Natural language question (str), entity names (list),
                              or None for whole-graph.
            relations: Relation types to filter on (structured mode only).
            min_confidence: Minimum edge confidence (structured mode only).
            max_hops: Hop traversal depth (structured mode only).

        Returns:
            QueryResult with matching nodes and edges.
        """
        self._ensure_started()

        if isinstance(text_or_entities, str):
            # NL query path
            return await self._nl_planner.query(text_or_entities)  # type: ignore[union-attr]
        else:
            # Structured query path
            entities = text_or_entities if text_or_entities else None
            return query_subgraph(
                self._store,  # type: ignore[arg-type]
                entities=entities,
                relations=relations,
                min_confidence=min_confidence,
                max_hops=max_hops,
            )

    # -- Combined path: process + query ------------------------------------

    async def get_context(self, message: str) -> ContextResult:
        """Process a message AND query for relevant context — in one call.

        This is the most common operation for agent integration:
        1. Extract entities/relations from the message and update the graph.
        2. Use the NL query planner to find relevant existing knowledge.
        3. Return both results together.

        Args:
            message: A user's conversational message.

        Returns:
            ContextResult with extraction details and relevant graph context.
        """
        self._ensure_started()

        # Step 1: Extract and ingest
        process_result = await self.process(message)

        # Step 2: Query for relevant context using the message as an NL query
        plan = await self._nl_planner.plan(message)  # type: ignore[union-attr]
        relevant = self._nl_planner.execute(plan)  # type: ignore[union-attr]

        return ContextResult(
            process=process_result,
            relevant=relevant,
            plan=plan,
        )

    # -- Event subscription -------------------------------------------------

    def subscribe(
        self,
        handler: EventHandler,
        *,
        event_types: set[GraphEventType] | None = None,
    ) -> None:
        """Register an async callback to receive graph mutation events.

        Args:
            handler: Async function that takes a GraphEvent.
            event_types: Set of event types to filter on. None = all events.

        Raises:
            RuntimeError: If NeuroWeave hasn't been started.
        """
        self._ensure_started()
        self._event_bus.subscribe(handler, event_types=event_types)  # type: ignore[union-attr]

    def unsubscribe(self, handler: EventHandler) -> None:
        """Remove a previously registered event handler.

        Args:
            handler: The same function object passed to subscribe().
        """
        if self._event_bus is not None:
            self._event_bus.unsubscribe(handler)

    # -- Visualization ------------------------------------------------------

    def create_visualization_app(self) -> Any:
        """Create a FastAPI app for the graph visualizer.

        Use this if you want to mount the visualization alongside your own
        FastAPI routes instead of running it as a standalone server.

        Returns:
            FastAPI application instance.

        Raises:
            RuntimeError: If NeuroWeave hasn't been started.
        """
        self._ensure_started()
        from neuroweave.server.app import create_app

        return create_app(self._store, event_bus=self._event_bus)  # type: ignore[arg-type]

    # -- Properties ---------------------------------------------------------

    @property
    def graph(self) -> GraphStore:
        """Direct access to the graph store (for advanced use cases)."""
        self._ensure_started()
        return self._store  # type: ignore[return-value]

    @property
    def event_bus(self) -> EventBus:
        """Direct access to the event bus (for advanced use cases)."""
        self._ensure_started()
        return self._event_bus  # type: ignore[return-value]

    @property
    def is_started(self) -> bool:
        return self._started

    # -- Internal -----------------------------------------------------------

    def _ensure_started(self) -> None:
        if not self._started:
            raise RuntimeError(
                "NeuroWeave is not started. Call await nw.start() or use "
                "'async with NeuroWeave(...) as nw:'"
            )

    async def _start_visualization_server(self) -> None:
        """Start the Cytoscape.js visualization server as a background task."""
        from neuroweave.server.app import create_app

        app = create_app(self._store, event_bus=self._event_bus)  # type: ignore[arg-type]
        config = uvicorn.Config(
            app,
            host=self._config.server_host,
            port=self._config.server_port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)
        self._server_task = asyncio.create_task(server.serve())
        log.info(
            "neuroweave.visualization_started",
            url=f"http://{self._config.server_host}:{self._config.server_port}",
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _create_llm_client(config: NeuroWeaveConfig) -> LLMClient:
    """Create the appropriate LLM client based on configuration."""
    if config.llm_provider == LLMProvider.MOCK:
        return MockLLMClient()
    elif config.llm_provider == LLMProvider.ANTHROPIC:
        if not config.llm_api_key:
            raise ValueError(
                "NEUROWEAVE_LLM_API_KEY must be set when using the anthropic provider."
            )
        return AnthropicLLMClient(api_key=config.llm_api_key, model=config.llm_model)
    else:
        raise ValueError(f"Unknown LLM provider: {config.llm_provider}")
