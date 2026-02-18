"""NeuroWeave entry point — conversation loop + visualization server.

This module is the standalone CLI for testing and development.
When NeuroWeave is used as a library, agents call the async API in
neuroweave.api instead of running this module.
"""

from __future__ import annotations

import asyncio
import sys

import uvicorn

from neuroweave.config import LLMProvider, NeuroWeaveConfig
from neuroweave.extraction.llm_client import AnthropicLLMClient, LLMClient, MockLLMClient
from neuroweave.extraction.pipeline import ExtractionPipeline
from neuroweave.graph.ingest import ingest_extraction
from neuroweave.graph.store import GraphStore
from neuroweave.logging import configure_logging, get_logger
from neuroweave.server.app import create_app


def create_llm_client(config: NeuroWeaveConfig) -> LLMClient:
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


async def process_message(
    message: str,
    pipeline: ExtractionPipeline,
    store: GraphStore,
) -> dict:
    """Process a single user message: extract → ingest → return stats.

    This is the core loop body, factored out for testability.
    """
    result = await pipeline.extract(message)
    stats = ingest_extraction(store, result)
    return {
        "entities_extracted": len(result.entities),
        "relations_extracted": len(result.relations),
        "extraction_ms": round(result.duration_ms, 1),
        **stats,
    }


async def run_conversation_loop(
    pipeline: ExtractionPipeline,
    store: GraphStore,
    server_url: str,
) -> None:
    """Interactive terminal conversation loop (async)."""
    log = get_logger("main")
    loop = asyncio.get_event_loop()

    print("\n╔══════════════════════════════════════════════════════════╗")
    print(  "║  NeuroWeave v0.1.0 — Knowledge Graph Memory POC          ║")
    print(  "║  Type a message to extract knowledge.                    ║")
    print( f"║  Graph visualization: {server_url:<34s} ║")
    print(  "║  Commands: /graph  /stats  /quit                         ║")
    print(  "╚══════════════════════════════════════════════════════════╝\n")

    while True:
        try:
            message = await loop.run_in_executor(None, lambda: input("You: ").strip())
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not message:
            continue

        if message.startswith("/"):
            _handle_command(message, store)
            continue

        stats = await process_message(message, pipeline, store)

        print(
            f"  → Extracted {stats['entities_extracted']} entities, "
            f"{stats['relations_extracted']} relations "
            f"({stats['extraction_ms']}ms)"
        )
        print(
            f"  → Graph: {store.node_count} nodes, {store.edge_count} edges "
            f"(+{stats['nodes_added']} nodes, +{stats['edges_added']} edges)"
        )
        print()


def _handle_command(command: str, store: GraphStore) -> None:
    """Handle slash commands in the conversation loop."""
    cmd = command.lower().strip()

    if cmd in ("/quit", "/exit"):
        print("Goodbye!")
        sys.exit(0)

    elif cmd == "/stats":
        print(f"  Graph: {store.node_count} nodes, {store.edge_count} edges")

    elif cmd == "/graph":
        data = store.to_dict()
        if not data["nodes"]:
            print("  Graph is empty — start chatting to build it!")
        else:
            print("  Nodes:")
            for node in data["nodes"]:
                print(f"    [{node['node_type']}] {node['name']}")
            print("  Edges:")
            for edge in data["edges"]:
                src = store.get_node(edge["source_id"])
                tgt = store.get_node(edge["target_id"])
                src_name = src["name"] if src else edge["source_id"]
                tgt_name = tgt["name"] if tgt else edge["target_id"]
                print(
                    f"    {src_name} --{edge['relation']}--> "
                    f"{tgt_name} ({edge['confidence']:.2f})"
                )

    else:
        print(f"  Unknown command: {command}. Try /graph, /stats, or /quit")

    print()


async def _run_server(app, host: str, port: int) -> None:
    """Run uvicorn server as an async task."""
    config = uvicorn.Config(
        app, host=host, port=port, log_level="warning", access_log=False,
    )
    server = uvicorn.Server(config)
    await server.serve()


async def async_main() -> None:
    """Run the NeuroWeave conversation loop with visualization server."""
    config = NeuroWeaveConfig.load()
    configure_logging(config)

    log = get_logger("main")
    log.info(
        "neuroweave.started",
        version="0.1.0",
        llm_provider=config.llm_provider.value,
        llm_model=config.llm_model,
        graph_backend=config.graph_backend.value,
    )

    llm_client = create_llm_client(config)
    pipeline = ExtractionPipeline(llm_client)
    store = GraphStore()

    # Start visualization server as a background task in the same event loop
    server_url = f"http://{config.server_host}:{config.server_port}"
    app = create_app(store)
    server_task = asyncio.create_task(_run_server(app, config.server_host, config.server_port))

    log.info("neuroweave.ready", server_url=server_url)

    try:
        await run_conversation_loop(pipeline, store, server_url)
    finally:
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass


def main() -> None:
    """Synchronous entry point for the CLI."""
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
