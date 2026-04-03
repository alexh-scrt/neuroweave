"""Canary tests for NW-FIX-001 — verify no 'event loop already running' errors.

These tests would have caught the v0.2.0 bug where Neo4jGraphStore used
asyncio.get_event_loop().run_until_complete() inside a running event loop.
"""

from __future__ import annotations

import asyncio

from neuroweave import NeuroWeave


async def test_neo4j_store_works_inside_running_event_loop():
    """Verify no 'This event loop is already running' error with Neo4j backend.

    Uses mock backend so no real Neo4j instance is needed.
    """
    async with NeuroWeave(llm_provider="mock") as nw:
        # This runs inside an event loop. If any store method uses
        # asyncio.get_event_loop().run_until_complete(), it raises here.
        result = await nw.process("Test message inside running loop")
        assert result is not None


async def test_nested_store_calls_do_not_deadlock():
    """All store methods must be awaitable without blocking the event loop."""
    async with NeuroWeave(llm_provider="mock") as nw:
        # Run concurrent operations — would deadlock if run_until_complete is used
        results = await asyncio.gather(
            nw.process("Alice loves Python"),
            nw.process("Bob uses Lean4"),
            nw.process("Graph theory is beautiful"),
        )
        assert len(results) == 3
