#!/usr/bin/env python3
"""NeuroWeave Demo Agent — shows how to integrate NeuroWeave into an AI agent.

This is a minimal, self-contained example that demonstrates:
1. Creating a NeuroWeave instance (with mock LLM — no API key needed)
2. Processing messages to build the knowledge graph
3. Querying for relevant context
4. Subscribing to graph events
5. Using get_context() for the combined process + query flow

Run:
    python examples/demo_agent.py

Or with the Anthropic API (requires NEUROWEAVE_LLM_API_KEY):
    python examples/demo_agent.py --provider anthropic
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path so we can import neuroweave
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from neuroweave import ContextResult, EventType, NeuroWeave
from neuroweave.extraction.llm_client import MockLLMClient
from neuroweave.extraction.pipeline import ExtractionPipeline
from neuroweave.graph.nl_query import NLQueryPlanner
from neuroweave.graph.store import GraphEvent


# ---------------------------------------------------------------------------
# Mock LLM with realistic extraction responses
# ---------------------------------------------------------------------------

def _build_corpus_mock() -> MockLLMClient:
    """Create a MockLLMClient that returns realistic extraction results.

    These canned responses simulate what a real LLM (Claude Haiku) produces
    for the 5-message conversation corpus. They allow the demo to show
    meaningful graph construction without needing an API key.
    """
    mock = MockLLMClient()

    # Message 1: "My name is Alex and I'm a software engineer."
    mock.set_response("alex", {
        "entities": [
            {"name": "User", "entity_type": "person"},
            {"name": "Alex", "entity_type": "person"},
            {"name": "software engineering", "entity_type": "concept"},
        ],
        "relations": [
            {"source": "User", "target": "Alex", "relation": "named", "confidence": 0.95},
            {"source": "User", "target": "software engineering", "relation": "occupation", "confidence": 0.90},
        ],
    })

    # Message 2: "My wife Lena and I are going to Tokyo in March."
    mock.set_response("lena", {
        "entities": [
            {"name": "User", "entity_type": "person"},
            {"name": "Lena", "entity_type": "person"},
            {"name": "Tokyo", "entity_type": "place"},
        ],
        "relations": [
            {"source": "User", "target": "Lena", "relation": "married_to", "confidence": 0.90},
            {"source": "User", "target": "Tokyo", "relation": "traveling_to", "confidence": 0.85},
            {"source": "Lena", "target": "Tokyo", "relation": "traveling_to", "confidence": 0.85},
        ],
    })

    # Message 3: "She loves sushi but I prefer ramen."
    mock.set_response("sushi", {
        "entities": [
            {"name": "sushi", "entity_type": "preference"},
            {"name": "ramen", "entity_type": "preference"},
        ],
        "relations": [
            {"source": "Lena", "target": "sushi", "relation": "prefers", "confidence": 0.90},
            {"source": "User", "target": "ramen", "relation": "prefers", "confidence": 0.85},
        ],
    })

    # Message 4: "We have two kids in elementary school."
    mock.set_response("kids", {
        "entities": [
            {"name": "children", "entity_type": "person"},
        ],
        "relations": [
            {"source": "User", "target": "children", "relation": "has_children", "confidence": 0.90},
        ],
    })

    # Message 5: "I've been using Python for 10 years."
    mock.set_response("python", {
        "entities": [
            {"name": "Python", "entity_type": "tool"},
        ],
        "relations": [
            {"source": "User", "target": "Python", "relation": "experienced_with", "confidence": 0.90},
        ],
    })

    # NL query responses (for query path demonstrations)
    mock.set_response("wife", {
        "entities": ["Lena"],
        "relations": ["prefers", "likes"],
        "max_hops": 1,
        "min_confidence": 0.0,
        "reasoning": "User's wife is Lena, looking for her preferences",
    })
    mock.set_response("traveling", {
        "entities": ["User"],
        "relations": ["traveling_to"],
        "max_hops": 1,
        "min_confidence": 0.0,
        "reasoning": "Looking for travel plans connected to the user",
    })
    mock.set_response("know about me", {
        "entities": ["User"],
        "relations": None,
        "max_hops": 2,
        "min_confidence": 0.0,
        "reasoning": "Broad user query, return full user context",
    })
    mock.set_response("tokyo", {
        "entities": ["Tokyo"],
        "relations": None,
        "max_hops": 2,
        "min_confidence": 0.0,
        "reasoning": "Everything about Tokyo and related entities",
    })

    return mock


# ---------------------------------------------------------------------------
# Demo event handler
# ---------------------------------------------------------------------------

async def on_graph_event(event: GraphEvent) -> None:
    """Prints a notification when the graph is updated."""
    event_type = event.event_type.value
    name = event.data.get("name", event.data.get("relation", "unknown"))
    print(f"  📡 Event: {event_type} → {name}")


# ---------------------------------------------------------------------------
# Demo conversation
# ---------------------------------------------------------------------------

DEMO_MESSAGES = [
    "My name is Alex and I'm a software engineer.",
    "My wife Lena and I are going to Tokyo in March.",
    "She loves sushi but I prefer ramen.",
    "We have two kids in elementary school.",
    "I've been using Python for 10 years.",
]

DEMO_QUERIES = [
    "what does my wife like?",
    "where are we traveling?",
    "what do you know about me?",
]


async def run_demo(
    provider: str = "mock",
    enable_viz: bool = True,
    server_port: int = 8787,
) -> None:
    """Run the complete demo showing NeuroWeave's capabilities."""

    print("\n╔══════════════════════════════════════════════════════════════╗")
    print(  "║  NeuroWeave Demo Agent                                       ║")
    print(  "║  Demonstrates knowledge graph memory for AI agents           ║")
    print(  "╚══════════════════════════════════════════════════════════════╝\n")

    # --- Setup ---
    viz_url = f"http://127.0.0.1:{server_port}"
    if provider == "mock":
        mock_llm = _build_corpus_mock()
        nw = NeuroWeave(
            llm_provider="mock", log_level="WARNING",
            enable_visualization=enable_viz, server_port=server_port,
        )
        await nw.start()
        # Replace the pipeline and planner with our pre-configured mock
        nw._pipeline = ExtractionPipeline(mock_llm)
        nw._nl_planner = NLQueryPlanner(mock_llm, nw.graph)
    else:
        nw = NeuroWeave(
            llm_provider=provider, log_level="WARNING",
            enable_visualization=enable_viz, server_port=server_port,
        )
        await nw.start()

    if enable_viz:
        print(f"  🌐 Graph visualizer: {viz_url}\n")

    # Subscribe to events
    nw.subscribe(on_graph_event, event_types={EventType.NODE_ADDED, EventType.EDGE_ADDED})

    try:
        # --- Phase 1: Process messages (build the graph) ---
        print("━━━ Phase 1: Processing messages ━━━\n")

        for i, message in enumerate(DEMO_MESSAGES, 1):
            print(f"  [{i}/{len(DEMO_MESSAGES)}] User: \"{message}\"")
            result = await nw.process(message)
            await asyncio.sleep(0)  # Let event handlers fire
            await asyncio.sleep(0)
            print(
                f"  ✅ Extracted {result.entity_count} entities, "
                f"{result.relation_count} relations "
                f"(+{result.nodes_added} nodes, +{result.edges_added} edges)\n"
            )

        print(f"  📊 Graph total: {nw.graph.node_count} nodes, {nw.graph.edge_count} edges\n")

        # --- Phase 2: Query the graph ---
        print("━━━ Phase 2: Querying the knowledge graph ━━━\n")

        for question in DEMO_QUERIES:
            print(f"  🔍 Query: \"{question}\"")
            result = await nw.query(question)
            print(f"     Nodes: {', '.join(result.node_names())}")
            print(f"     Relations: {', '.join(result.relation_types())}")
            print(f"     ({result.node_count} nodes, {result.edge_count} edges)\n")

        # --- Phase 3: Structured query ---
        print("━━━ Phase 3: Structured query ━━━\n")

        result = await nw.query(["Lena"], relations=["prefers"], max_hops=1)
        print(f"  🔎 query(['Lena'], relations=['prefers'])")
        print(f"     Nodes: {', '.join(result.node_names())}")
        print(f"     Edges: {result.edge_count}")
        for edge in result.edges:
            src = nw.graph.get_node(edge["source_id"])
            tgt = nw.graph.get_node(edge["target_id"])
            src_name = src["name"] if src else "?"
            tgt_name = tgt["name"] if tgt else "?"
            print(f"     {src_name} --{edge['relation']}--> {tgt_name} ({edge['confidence']:.2f})")
        print()

        # --- Phase 4: get_context (combined) ---
        print("━━━ Phase 4: get_context (process + query combined) ━━━\n")

        context = await nw.get_context("Lena also loves hiking in the mountains.")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        print(f"  💬 Message: \"Lena also loves hiking in the mountains.\"")
        print(f"     Extracted: {context.process.entity_count} entities, {context.process.relation_count} relations")
        print(f"     Relevant context: {context.relevant.node_count} nodes, {context.relevant.edge_count} edges")
        if context.plan:
            print(f"     Plan reasoning: {context.plan.reasoning}")
        print()

        # --- Summary ---
        print("━━━ Summary ━━━\n")
        print(f"  Final graph: {nw.graph.node_count} nodes, {nw.graph.edge_count} edges")
        print(f"  Event bus: {nw.event_bus.emit_count} events emitted")
        print()
        print("  Graph contents:")
        data = nw.graph.to_dict()
        for node in data["nodes"]:
            print(f"    [{node['node_type']}] {node['name']}")
        for edge in data["edges"]:
            src = nw.graph.get_node(edge["source_id"])
            tgt = nw.graph.get_node(edge["target_id"])
            src_name = src["name"] if src else edge["source_id"]
            tgt_name = tgt["name"] if tgt else edge["target_id"]
            print(f"    {src_name} --{edge['relation']}--> {tgt_name} ({edge['confidence']:.2f})")

    finally:
        await nw.stop()

    print("\n✨ Demo complete!\n")


# ---------------------------------------------------------------------------
# Interactive mode
# ---------------------------------------------------------------------------

async def run_interactive(
    provider: str = "mock",
    enable_viz: bool = True,
    server_port: int = 8787,
) -> None:
    """Run an interactive conversation loop."""

    viz_url = f"http://127.0.0.1:{server_port}"
    if provider == "mock":
        mock_llm = _build_corpus_mock()
        nw = NeuroWeave(
            llm_provider="mock", log_level="WARNING",
            enable_visualization=enable_viz, server_port=server_port,
        )
        await nw.start()
        nw._pipeline = ExtractionPipeline(mock_llm)
        nw._nl_planner = NLQueryPlanner(mock_llm, nw.graph)
    else:
        nw = NeuroWeave(
            llm_provider=provider, log_level="WARNING",
            enable_visualization=enable_viz, server_port=server_port,
        )
        await nw.start()

    nw.subscribe(on_graph_event)

    print("\n╔══════════════════════════════════════════════════════════════╗")
    print("║  NeuroWeave Interactive Agent                                ║")
    print("║  Commands: /ask <question>  /graph  /stats  /quit           ║")
    print("╚══════════════════════════════════════════════════════════════╝\n")
    if enable_viz:
        print(f"  🌐 Graph visualizer: {viz_url}\n")

    loop = asyncio.get_event_loop()

    try:
        while True:
            try:
                message = await loop.run_in_executor(None, lambda: input("You: ").strip())
            except (EOFError, KeyboardInterrupt):
                break

            if not message:
                continue

            if message.lower() in ("/quit", "/exit"):
                break

            if message.lower() == "/stats":
                print(f"  📊 {nw.graph.node_count} nodes, {nw.graph.edge_count} edges")
                print(f"  📡 {nw.event_bus.emit_count} events emitted\n")
                continue

            if message.lower() == "/graph":
                data = nw.graph.to_dict()
                if not data["nodes"]:
                    print("  Graph is empty — start chatting!\n")
                    continue
                for node in data["nodes"]:
                    print(f"  [{node['node_type']}] {node['name']}")
                for edge in data["edges"]:
                    src = nw.graph.get_node(edge["source_id"])
                    tgt = nw.graph.get_node(edge["target_id"])
                    print(f"  {src['name'] if src else '?'} --{edge['relation']}--> {tgt['name'] if tgt else '?'}")
                print()
                continue

            if message.lower().startswith("/ask "):
                question = message[5:].strip()
                result = await nw.query(question)
                print(f"  🔍 Nodes: {', '.join(result.node_names()) or '(none)'}")
                print(f"  🔍 Relations: {', '.join(result.relation_types()) or '(none)'}\n")
                continue

            # Normal message → get_context
            context = await nw.get_context(message)
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            print(
                f"  ✅ Extracted {context.process.entity_count} entities, "
                f"{context.process.relation_count} relations"
            )
            if not context.relevant.is_empty:
                print(f"  💡 Relevant: {', '.join(context.relevant.node_names())}")
            print()

    finally:
        await nw.stop()
        print("\nGoodbye!")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="NeuroWeave Demo Agent")
    parser.add_argument(
        "--provider", default="mock", choices=["mock", "anthropic"],
        help="LLM provider (default: mock — no API key needed)",
    )
    parser.add_argument(
        "--interactive", "-i", action="store_true",
        help="Run in interactive mode instead of the canned demo",
    )
    parser.add_argument(
        "--no-viz", action="store_true",
        help="Disable the graph visualization server",
    )
    parser.add_argument(
        "--port", type=int, default=8787,
        help="Visualization server port (default: 8787)",
    )
    args = parser.parse_args()

    viz = not args.no_viz
    if args.interactive:
        asyncio.run(run_interactive(args.provider, enable_viz=viz, server_port=args.port))
    else:
        asyncio.run(run_demo(args.provider, enable_viz=viz, server_port=args.port))


if __name__ == "__main__":
    main()
