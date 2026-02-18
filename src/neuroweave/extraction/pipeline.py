"""Extraction pipeline — transforms a user message into knowledge graph entities and relations.

POC implementation: single LLM call that returns both entities and relations.
The 7-stage pipeline from the architecture docs will evolve from this foundation.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from neuroweave.extraction.llm_client import LLMClient, LLMError
from neuroweave.logging import get_logger

log = get_logger("extraction")


# ---------------------------------------------------------------------------
# Extraction result types
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ExtractedEntity:
    """An entity extracted from a user message."""

    name: str
    entity_type: str  # person, organization, tool, place, concept, preference
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExtractedRelation:
    """A relation extracted between two entities."""

    source: str  # entity name
    target: str  # entity name
    relation: str
    confidence: float
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Complete result from processing a single message."""

    entities: list[ExtractedEntity]
    relations: list[ExtractedRelation]
    raw_response: str = ""
    duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM_PROMPT = """\
You are a knowledge extraction engine. Your task is to extract entities and \
relationships from a user's conversational message.

Extract ONLY observable facts from the message. Do not infer information that \
is not clearly stated or strongly implied.

RULES:
- The user speaking is always referred to as "User" in your output.
- Extract people, organizations, tools, technologies, places, and concepts.
- Extract relationships between entities with a confidence score (0.0 to 1.0).
- CRITICAL: Every entity name referenced in a relation MUST also appear in the \
entities array. If a relation uses "engineer" as source or target, "engineer" \
must be in the entities list. Never reference an entity in a relation without \
declaring it first.
- For explicit statements ("My name is Alex"), use high confidence (0.85-0.95).
- For preferences ("I love Python"), use high confidence (0.85-0.95).
- For hedged statements ("I might try Rust"), use lower confidence (0.40-0.60).
- For negations ("I don't like Java"), extract as a negative relation (dislikes) \
with high confidence.
- If the message contains no extractable entities or facts (e.g. "Thanks!", \
"OK", "Got it"), return empty entities and relations arrays.

Respond with ONLY valid JSON in this exact format, no other text:

{
  "entities": [
    {"name": "entity name", "entity_type": "person|organization|tool|place|concept|preference", "properties": {}}
  ],
  "relations": [
    {"source": "source entity name", "target": "target entity name", "relation": "relation_type", "confidence": 0.85, "properties": {}}
  ]
}
"""


# ---------------------------------------------------------------------------
# JSON repair — handles common LLM output issues
# ---------------------------------------------------------------------------
def _strip_code_fences(text: str) -> str:
    """
    If a fenced block exists, prefer its content. Otherwise return original text.
    Supports ```json ... ``` and ``` ... ```, even if surrounded by prose.
    """
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    return text.strip()


def _extract_first_json_block(text: str) -> str | None:
    """
    Extract the first syntactically complete JSON object/array from text by
    matching brackets while respecting JSON strings and escape sequences.
    """
    if not text:
        return None

    # Find first JSON opener
    start = None
    opener = None
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            opener = ch
            break
    if start is None or opener is None:
        return None

    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        ch = text[i]

        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = False
            continue

        # not in string
        if ch == '"':
            in_string = True
            continue

        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

        # Allow nested opposite brackets too (they don't change depth for outer type),
        # but we still need to skip over them safely when they occur inside strings
        # (already handled). No extra action needed here.

    # No complete block found
    return None


def repair_llm_json(raw_output: str) -> dict[str, Any] | list[Any] | None:
    """Attempt to parse and repair common LLM JSON output issues.

    Handles:
      - Markdown fences / prose around fenced blocks
      - Preamble / trailing extra text (extracts first complete JSON object/array)
      - Trailing commas before closing braces/brackets
      - Unclosed top-level brackets/braces (best-effort)

    Returns:
        Parsed dict/list or None if repair fails.
    """
    if not raw_output or not raw_output.strip():
        return None

    text = _strip_code_fences(raw_output)

    # Extract only the first complete JSON payload, dropping trailing extra text.
    candidate = _extract_first_json_block(text)

    # Fallback: sometimes fences were stripped but prose remains; try on original too.
    if candidate is None:
        candidate = _extract_first_json_block(raw_output)

    if candidate is None:
        log.error("extraction.json_candidate_none", raw_output=raw_output[:200])
        return None

    # Fix trailing commas before closing brackets/braces in the candidate only
    candidate = re.sub(r",\s*([}\]])", r"\1", candidate)

    # First parse attempt
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        log.warning("extraction.json_parse_failed", error=str(e))
        pass

    # Best-effort: close unclosed brackets/braces (top-level and nested)
    # This is heuristic; only apply to candidate, not the entire message.
    open_sq = candidate.count("[") - candidate.count("]")
    open_cu = candidate.count("{") - candidate.count("}")
    repaired = candidate + ("]" * max(0, open_sq)) + ("}" * max(0, open_cu))

    # Re-apply trailing comma fix after appending closers
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)

    try:
        return json.loads(repaired)
    except json.JSONDecodeError as e:
        log.error("extraction.json_repair_failed", error=str(e))
        return None

# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class ExtractionPipeline:
    """Extracts entities and relations from conversational messages using an LLM.

    Usage:
        pipeline = ExtractionPipeline(llm_client)
        result = pipeline.extract("My wife's name is Lena")
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm = llm_client

    async def extract(self, message: str) -> ExtractionResult:
        """Extract entities and relations from a user message.

        Args:
            message: The user's conversational message.

        Returns:
            ExtractionResult with entities, relations, and timing info.
            On failure, returns an empty result (never raises).
        """
        log.info("extraction.start", message_length=len(message))
        start = time.monotonic()

        try:
            raw_response = await self._llm.extract(EXTRACTION_SYSTEM_PROMPT, message)
        except LLMError as e:
            log.error("extraction.llm_error", error=str(e))
            return ExtractionResult(
                entities=[], relations=[], duration_ms=_elapsed_ms(start)
            )

        parsed = repair_llm_json(raw_response)
        if parsed is None:
            log.warning("extraction.parse_failed", raw_response=raw_response[:200])
            return ExtractionResult(
                entities=[], relations=[], raw_response=raw_response,
                duration_ms=_elapsed_ms(start),
            )

        entities = _parse_entities(parsed.get("entities", []))
        relations = _parse_relations(parsed.get("relations", []))

        duration = _elapsed_ms(start)
        log.info(
            "extraction.complete",
            entity_count=len(entities),
            relation_count=len(relations),
            duration_ms=round(duration, 1),
        )

        return ExtractionResult(
            entities=entities,
            relations=relations,
            raw_response=raw_response,
            duration_ms=duration,
        )


# ---------------------------------------------------------------------------
# Internal parsers — defensive, never raise
# ---------------------------------------------------------------------------

def _parse_entities(raw_entities: list[Any]) -> list[ExtractedEntity]:
    """Parse raw entity dicts into ExtractedEntity objects, skipping malformed ones."""
    entities = []
    for item in raw_entities:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        entity_type = item.get("entity_type", "concept")
        if not name or not isinstance(name, str):
            continue
        props = item.get("properties", {})
        if isinstance(props, dict):
            # Strip keys that duplicate top-level fields
            props = {k: v for k, v in props.items()
                     if k not in ("name", "entity_type")}
        else:
            props = {}
        entities.append(ExtractedEntity(
            name=name,
            entity_type=entity_type,
            properties=props,
        ))
    return entities


def _parse_relations(raw_relations: list[Any] | None) -> list[ExtractedRelation]:
    """Parse raw relation dicts into ExtractedRelation objects, skipping malformed ones."""
    if not raw_relations:
        return []
    relations = []
    for item in raw_relations:
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        target = item.get("target")
        relation = item.get("relation")
        confidence = item.get("confidence", 0.5)
        if not all(isinstance(v, str) for v in [source, target, relation]):
            continue
        # Clamp confidence to [0.0, 1.0]
        confidence = max(0.0, min(1.0, float(confidence)))
        props = item.get("properties", {})
        if isinstance(props, dict):
            # Strip keys that duplicate top-level fields
            props = {k: v for k, v in props.items()
                     if k not in ("source", "target", "relation", "confidence")}
        else:
            props = {}
        relations.append(ExtractedRelation(
            source=source,
            target=target,
            relation=relation,
            confidence=confidence,
            properties=props,
        ))
    return relations


def _elapsed_ms(start: float) -> float:
    return (time.monotonic() - start) * 1000
