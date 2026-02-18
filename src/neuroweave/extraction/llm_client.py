"""LLM client abstraction — async protocol + mock and Anthropic implementations.

The protocol allows the extraction pipeline to work with any LLM backend.
Tests use MockLLMClient; production uses AnthropicLLMClient.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from neuroweave.logging import get_logger

log = get_logger("llm")


class LLMClient(Protocol):
    """Protocol for LLM clients used by the extraction pipeline."""

    async def extract(self, system_prompt: str, user_message: str) -> str:
        """Send extraction prompt to LLM and return raw text response.

        Args:
            system_prompt: System instructions for extraction.
            user_message: The user's conversational message to extract from.

        Returns:
            Raw LLM response text (expected to be JSON).

        Raises:
            LLMError: If the LLM call fails.
        """
        ...


class LLMError(Exception):
    """Raised when an LLM call fails."""


# ---------------------------------------------------------------------------
# Mock client — deterministic, no API calls
# ---------------------------------------------------------------------------

class MockLLMClient:
    """Mock LLM that returns predetermined extraction results.

    Register responses with `set_response(message_substring, json_response)`.
    Falls back to an empty extraction if no match is found.
    """

    def __init__(self) -> None:
        self._responses: list[tuple[str, dict[str, Any]]] = []
        self._call_count: int = 0
        self._last_system_prompt: str = ""
        self._last_user_message: str = ""

    def set_response(self, message_contains: str, response: dict[str, Any]) -> None:
        """Register a canned response for messages containing the given substring."""
        self._responses.append((message_contains.lower(), response))

    async def extract(self, system_prompt: str, user_message: str) -> str:
        self._call_count += 1
        self._last_system_prompt = system_prompt
        self._last_user_message = user_message

        for substring, response in self._responses:
            if substring in user_message.lower():
                log.debug("mock_llm.matched", substring=substring, message=user_message[:80])
                return json.dumps(response)

        log.debug("mock_llm.no_match", message=user_message[:80])
        return json.dumps({"entities": [], "relations": []})

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def last_system_prompt(self) -> str:
        return self._last_system_prompt

    @property
    def last_user_message(self) -> str:
        return self._last_user_message


# ---------------------------------------------------------------------------
# Anthropic client — real LLM calls
# ---------------------------------------------------------------------------

class AnthropicLLMClient:
    """LLM client using the Anthropic async API (Claude Haiku for extraction)."""

    def __init__(self, api_key: str, model: str) -> None:
        try:
            import anthropic
        except ImportError as e:
            raise ImportError("pip install anthropic") from e

        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def extract(self, system_prompt: str, user_message: str) -> str:
        import anthropic

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            text = response.content[0].text
            log.info(
                "anthropic.extract_complete",
                model=self._model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )
            return text
        except anthropic.APIError as e:
            log.error("anthropic.api_error", error=str(e))
            raise LLMError(f"Anthropic API error: {e}") from e
