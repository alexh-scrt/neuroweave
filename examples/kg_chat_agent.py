#!/usr/bin/env python3
"""NeuroWeave KG Chat Agent — a conversational agent powered by a live knowledge graph.

Every message you send is:
  1. Processed by NeuroWeave (entities and relations extracted, graph updated).
  2. Queried against the growing knowledge graph for relevant context.
  3. Fed — along with conversation history and KG context — to a chat LLM
     that responds with awareness of everything it has learned about you.

The agent becomes increasingly intuitive: it notices connections, recalls
details from earlier in the conversation, and proactively surfaces insights
("Valentine's Day is approaching — would you like to plan something with Lena?").

Run:
    python examples/kg_chat_agent.py

    # With visualization (default):
    python examples/kg_chat_agent.py --port 8787
    # Then open http://127.0.0.1:8787 in your browser

    # Without visualization:
    python examples/kg_chat_agent.py --no-viz

    # Use a different chat model (default: claude-sonnet-4-5-20250514):
    python examples/kg_chat_agent.py --chat-model claude-haiku-4-5-20251001

Requires:
    NEUROWEAVE_LLM_API_KEY in .env or environment (Anthropic API key).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Add project root to path so we can import neuroweave
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import anthropic

from neuroweave import ContextResult, EventType, NeuroWeave
from neuroweave.graph.query import QueryResult
from neuroweave.graph.store import GraphEvent, GraphStore


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CHAT_MODEL = "claude-sonnet-4-6"
DEFAULT_EXTRACTION_MODEL = "claude-haiku-4-5-20251001"
MAX_HISTORY_TURNS = 20  # Keep last N turns in chat context


# ---------------------------------------------------------------------------
# System prompt for the chat LLM
# ---------------------------------------------------------------------------

CHAT_SYSTEM_PROMPT = """\
You are a warm, perceptive conversational companion. You have access to a \
live knowledge graph that accumulates everything the user shares with you \
across the conversation.

Your core behaviors:

1. **Be naturally conversational.** Respond like a thoughtful friend, not \
a database. Never say "according to my knowledge graph" or reference the \
system mechanics. Just *know* things.

2. **Use knowledge proactively.** When you see connections between facts \
the user has shared, surface them naturally. If they mentioned a wife \
named Lena and later mention Valentine's Day, suggest a dinner plan. If \
they work in engineering and mention stress, connect it to work-life balance.

3. **Ask insightful follow-up questions.** Don't just acknowledge — dig \
deeper based on what you know. If someone mentions they love cooking and \
are traveling to Tokyo, ask about the food they're most excited to try.

4. **Remember and reference earlier details.** The knowledge graph context \
below contains everything learned so far. Weave prior details into your \
responses naturally, showing the user you truly listen and remember.

5. **Spot patterns and suggest connections.** Notice when interests, plans, \
or relationships interrelate. Suggest ideas, recommendations, or observations \
that the user might not have thought of themselves.

6. **Stay grounded.** Only reference things actually in the knowledge graph \
or conversation. Never fabricate facts about the user.

Today's date is {today}.
"""

KG_CONTEXT_TEMPLATE = """\
<knowledge_graph>
What you know about the user so far (from the conversation):

{graph_summary}
</knowledge_graph>

<relevant_context>
Context most relevant to the user's latest message:

{relevant_summary}
</relevant_context>
"""


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ChatMessage:
    """A single message in the conversation."""
    role: str       # "user" or "assistant"
    content: str


@dataclass
class AgentState:
    """Mutable state for the chat agent."""
    history: list[ChatMessage] = field(default_factory=list)
    total_entities: int = 0
    total_relations: int = 0
    turn_count: int = 0


# ---------------------------------------------------------------------------
# KG → text formatting
# ---------------------------------------------------------------------------

def format_graph_summary(store: GraphStore) -> str:
    """Format the full graph as a readable text summary for the LLM."""
    data = store.to_dict()

    if not data["nodes"]:
        return "(No knowledge accumulated yet.)"

    # Build a node name lookup
    id_to_name: dict[str, str] = {}
    for node in data["nodes"]:
        id_to_name[node["id"]] = node["name"]

    lines: list[str] = []

    # Group nodes by type
    by_type: dict[str, list[str]] = {}
    for node in data["nodes"]:
        ntype = node["node_type"]
        by_type.setdefault(ntype, []).append(node["name"])

    for ntype, names in sorted(by_type.items()):
        lines.append(f"  {ntype.title()}s: {', '.join(sorted(names))}")

    lines.append("")
    lines.append("  Relationships:")
    for edge in data["edges"]:
        src = id_to_name.get(edge["source_id"], "?")
        tgt = id_to_name.get(edge["target_id"], "?")
        conf = edge.get("confidence", 0.0)
        lines.append(f"    {src} --[{edge['relation']}]--> {tgt} ({conf:.0%})")

    return "\n".join(lines)


def format_relevant_context(result: QueryResult, store: GraphStore) -> str:
    """Format the relevant query result as text for the LLM."""
    if result.is_empty:
        return "(No specific relevant context for this message.)"

    id_to_name: dict[str, str] = {}
    for node in result.nodes:
        id_to_name[node["id"]] = node["name"]

    lines: list[str] = []
    if result.nodes:
        names = sorted(n["name"] for n in result.nodes)
        lines.append(f"  Related entities: {', '.join(names)}")

    if result.edges:
        lines.append("  Related facts:")
        for edge in result.edges:
            src = id_to_name.get(edge["source_id"], "?")
            tgt = id_to_name.get(edge["target_id"], "?")
            lines.append(f"    {src} --[{edge['relation']}]--> {tgt}")

    return "\n".join(lines) if lines else "(No specific relevant context.)"


# ---------------------------------------------------------------------------
# Chat agent core
# ---------------------------------------------------------------------------

class KGChatAgent:
    """A conversational agent backed by a NeuroWeave knowledge graph.

    Each user message triggers:
      1. KG extraction + context retrieval (via NeuroWeave)
      2. Full graph summary + relevant context formatting
      3. Chat LLM call with conversation history + KG context
    """

    def __init__(
        self,
        nw: NeuroWeave,
        *,
        chat_model: str = DEFAULT_CHAT_MODEL,
        api_key: str = "",
    ) -> None:
        self._nw = nw
        self._chat_model = chat_model
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._state = AgentState()

    async def chat(self, user_message: str) -> str:
        """Process a user message and return the agent's response.

        1. Send message through NeuroWeave (extract + query).
        2. Build LLM prompt with KG context + conversation history.
        3. Get chat response from the LLM.
        4. Update conversation history.
        """
        self._state.turn_count += 1

        # --- Step 1: NeuroWeave extraction + context ---
        context = await self._nw.get_context(user_message)

        self._state.total_entities += context.process.entity_count
        self._state.total_relations += context.process.relation_count

        # --- Step 2: Format KG context ---
        graph_summary = format_graph_summary(self._nw.graph)
        relevant_summary = format_relevant_context(context.relevant, self._nw.graph)

        kg_context = KG_CONTEXT_TEMPLATE.format(
            graph_summary=graph_summary,
            relevant_summary=relevant_summary,
        )

        # --- Step 3: Build messages for chat LLM ---
        system = CHAT_SYSTEM_PROMPT.format(today=datetime.now().strftime("%A, %B %d, %Y"))
        system += "\n\n" + kg_context

        # Conversation history (trimmed to last N turns)
        messages = []
        history_window = self._state.history[-(MAX_HISTORY_TURNS * 2):]
        for msg in history_window:
            messages.append({"role": msg.role, "content": msg.content})

        # Current user message
        messages.append({"role": "user", "content": user_message})

        # --- Step 4: Call chat LLM ---
        response = await self._client.messages.create(
            model=self._chat_model,
            max_tokens=1024,
            system=system,
            messages=messages,
        )
        assistant_text = response.content[0].text

        # --- Step 5: Update history ---
        self._state.history.append(ChatMessage(role="user", content=user_message))
        self._state.history.append(ChatMessage(role="assistant", content=assistant_text))

        return assistant_text

    @property
    def state(self) -> AgentState:
        return self._state


# ---------------------------------------------------------------------------
# Event handler (optional debug output)
# ---------------------------------------------------------------------------

_show_kg_events = False


async def on_graph_event(event: GraphEvent) -> None:
    """Print KG mutation events when debug mode is on."""
    if not _show_kg_events:
        return
    etype = event.event_type.value
    name = event.data.get("name", event.data.get("relation", "?"))
    print(f"  \033[90m📡 KG: {etype} → {name}\033[0m")


# ---------------------------------------------------------------------------
# Interactive loop
# ---------------------------------------------------------------------------

async def run_agent(
    *,
    chat_model: str = DEFAULT_CHAT_MODEL,
    enable_viz: bool = True,
    server_port: int = 8787,
    show_debug: bool = False,
) -> None:
    """Run the interactive KG chat agent."""
    global _show_kg_events
    _show_kg_events = show_debug

    # Resolve API key
    api_key = os.environ.get("NEUROWEAVE_LLM_API_KEY", "")
    if not api_key:
        # Try loading from .env manually
        env_path = Path(__file__).resolve().parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("NEUROWEAVE_LLM_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    break

    if not api_key:
        print("❌ NEUROWEAVE_LLM_API_KEY not found in environment or .env")
        print("   Set it with: export NEUROWEAVE_LLM_API_KEY=sk-ant-...")
        sys.exit(1)

    # Initialize NeuroWeave
    nw = NeuroWeave(
        llm_provider="anthropic",
        enable_visualization=enable_viz,
        server_port=server_port,
    )
    await nw.start()
    nw.subscribe(on_graph_event)

    # Initialize chat agent
    agent = KGChatAgent(nw, chat_model=chat_model, api_key=api_key)

    viz_url = f"http://127.0.0.1:{server_port}"

    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  NeuroWeave KG Chat Agent                                    ║")
    print("║  Every message builds your personal knowledge graph          ║")
    print("╠══════════════════════════════════════════════════════════════╣")
    print(f"║  Chat model:  {chat_model:<45}║")
    print(f"║  KG extract:  {DEFAULT_EXTRACTION_MODEL:<45}║")
    if enable_viz:
        print(f"║  Graph viz:   {viz_url:<45}║")
    print("╠══════════════════════════════════════════════════════════════╣")
    print("║  Commands:                                                    ║")
    print("║    /graph   — show knowledge graph contents                   ║")
    print("║    /stats   — show session statistics                         ║")
    print("║    /debug   — toggle KG event output                          ║")
    print("║    /quit    — exit                                            ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()

    if enable_viz:
        print(f"  🌐 Open \033[4m{viz_url}\033[0m in your browser to see the graph grow!\n")

    loop = asyncio.get_event_loop()

    try:
        while True:
            try:
                user_input = await loop.run_in_executor(
                    None, lambda: input("\033[1mYou:\033[0m ").strip()
                )
            except (EOFError, KeyboardInterrupt):
                break

            if not user_input:
                continue

            # --- Commands ---
            cmd = user_input.lower()

            if cmd in ("/quit", "/exit", "/q"):
                break

            if cmd == "/debug":
                _show_kg_events = not _show_kg_events
                state = "ON" if _show_kg_events else "OFF"
                print(f"  \033[90mKG debug events: {state}\033[0m\n")
                continue

            if cmd == "/stats":
                s = agent.state
                g = nw.graph
                print(f"  📊 Turns: {s.turn_count}")
                print(f"  📊 Graph: {g.node_count} nodes, {g.edge_count} edges")
                print(f"  📊 Extracted: {s.total_entities} entities, {s.total_relations} relations")
                print(f"  📊 Events: {nw.event_bus.emit_count} emitted\n")
                continue

            if cmd == "/graph":
                summary = format_graph_summary(nw.graph)
                print(f"\n{summary}\n")
                continue

            # --- Chat ---
            print()  # visual spacing
            try:
                response = await agent.chat(user_input)
                # Allow event handlers to fire
                await asyncio.sleep(0)
                await asyncio.sleep(0)
            except anthropic.APIError as e:
                print(f"  ❌ API error: {e}\n")
                continue
            except Exception as e:
                print(f"  ❌ Error: {e}\n")
                continue

            # Print response with wrapping
            print(f"\033[1mAgent:\033[0m", end=" ")
            wrapped = textwrap.fill(response, width=78, subsequent_indent="  ")
            print(wrapped)
            print()

    finally:
        await nw.stop()
        print("\n👋 Goodbye!\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="NeuroWeave KG Chat Agent — a conversational agent with live knowledge graph memory",
    )
    parser.add_argument(
        "--chat-model", default=DEFAULT_CHAT_MODEL,
        help=f"Chat LLM model (default: {DEFAULT_CHAT_MODEL})",
    )
    parser.add_argument(
        "--no-viz", action="store_true",
        help="Disable the graph visualization server",
    )
    parser.add_argument(
        "--port", type=int, default=8787,
        help="Visualization server port (default: 8787)",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Show KG mutation events in the terminal",
    )
    args = parser.parse_args()

    asyncio.run(run_agent(
        chat_model=args.chat_model,
        enable_viz=not args.no_viz,
        server_port=args.port,
        show_debug=args.debug,
    ))


if __name__ == "__main__":
    main()
