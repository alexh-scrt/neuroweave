"""Tests for the extraction pipeline — LLM client, JSON repair, and entity/relation extraction."""

from __future__ import annotations

import json

import pytest

from neuroweave.extraction.llm_client import MockLLMClient
from neuroweave.extraction.pipeline import (
    ExtractionPipeline,
    ExtractionResult,
    repair_llm_json,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _mock_with_responses() -> MockLLMClient:
    """Create a MockLLMClient pre-loaded with a standard test corpus."""
    mock = MockLLMClient()

    mock.set_response("my wife's name is lena", {
        "entities": [
            {"name": "User", "entity_type": "person"},
            {"name": "Lena", "entity_type": "person"},
        ],
        "relations": [
            {"source": "User", "target": "Lena", "relation": "married_to", "confidence": 0.90},
        ],
    })

    mock.set_response("my name is alex", {
        "entities": [
            {"name": "Alex", "entity_type": "person", "properties": {"is_user": True}},
        ],
        "relations": [
            {"source": "User", "target": "Alex", "relation": "named", "confidence": 0.95},
        ],
    })

    mock.set_response("software engineer", {
        "entities": [
            {"name": "User", "entity_type": "person"},
            {"name": "software engineering", "entity_type": "concept"},
        ],
        "relations": [
            {"source": "User", "target": "software engineering", "relation": "occupation", "confidence": 0.90},
        ],
    })

    mock.set_response("i love python", {
        "entities": [
            {"name": "User", "entity_type": "person"},
            {"name": "Python", "entity_type": "tool"},
        ],
        "relations": [
            {"source": "User", "target": "Python", "relation": "prefers", "confidence": 0.90},
        ],
    })

    mock.set_response("i don't like java", {
        "entities": [
            {"name": "User", "entity_type": "person"},
            {"name": "Java", "entity_type": "tool"},
        ],
        "relations": [
            {"source": "User", "target": "Java", "relation": "dislikes", "confidence": 0.85},
        ],
    })

    mock.set_response("i might try rust", {
        "entities": [
            {"name": "User", "entity_type": "person"},
            {"name": "Rust", "entity_type": "tool"},
        ],
        "relations": [
            {"source": "User", "target": "Rust", "relation": "interested_in", "confidence": 0.45},
        ],
    })

    mock.set_response("going to tokyo in march", {
        "entities": [
            {"name": "User", "entity_type": "person"},
            {"name": "Lena", "entity_type": "person"},
            {"name": "Tokyo", "entity_type": "place"},
        ],
        "relations": [
            {"source": "User", "target": "Tokyo", "relation": "traveling_to", "confidence": 0.85,
             "properties": {"timeframe": "March 2026"}},
            {"source": "Lena", "target": "Tokyo", "relation": "traveling_to", "confidence": 0.85},
        ],
    })

    mock.set_response("loves sushi but i prefer ramen", {
        "entities": [
            {"name": "Lena", "entity_type": "person"},
            {"name": "User", "entity_type": "person"},
            {"name": "sushi", "entity_type": "concept"},
            {"name": "ramen", "entity_type": "concept"},
        ],
        "relations": [
            {"source": "Lena", "target": "sushi", "relation": "prefers", "confidence": 0.90},
            {"source": "User", "target": "ramen", "relation": "prefers", "confidence": 0.85},
        ],
    })

    mock.set_response("two kids", {
        "entities": [
            {"name": "User", "entity_type": "person"},
            {"name": "children", "entity_type": "person", "properties": {"count": 2}},
        ],
        "relations": [
            {"source": "User", "target": "children", "relation": "has_children", "confidence": 0.90},
        ],
    })

    mock.set_response("using python for 10 years", {
        "entities": [
            {"name": "User", "entity_type": "person"},
            {"name": "Python", "entity_type": "tool"},
        ],
        "relations": [
            {"source": "User", "target": "Python", "relation": "experienced_with", "confidence": 0.90,
             "properties": {"duration": "10 years"}},
        ],
    })

    return mock


@pytest.fixture
def mock_llm() -> MockLLMClient:
    return _mock_with_responses()


@pytest.fixture
def pipeline(mock_llm: MockLLMClient) -> ExtractionPipeline:
    return ExtractionPipeline(mock_llm)


# ---------------------------------------------------------------------------
# JSON repair
# ---------------------------------------------------------------------------

class TestRepairLLMJson:
    def test_clean_json(self):
        result = repair_llm_json('{"entities": [], "relations": []}')
        assert result == {"entities": [], "relations": []}

    def test_markdown_fences(self):
        raw = '```json\n{"entities": [], "relations": []}\n```'
        result = repair_llm_json(raw)
        assert result is not None
        assert result["entities"] == []

    def test_preamble_text(self):
        raw = 'Here is the extraction:\n{"entities": [], "relations": []}'
        result = repair_llm_json(raw)
        assert result is not None

    def test_trailing_comma(self):
        raw = '{"entities": [{"name": "Alex", "entity_type": "person",},], "relations": []}'
        result = repair_llm_json(raw)
        assert result is not None
        assert result["entities"][0]["name"] == "Alex"

    def test_unclosed_bracket(self):
        raw = '{"entities": [{"name": "Alex", "entity_type": "person"}], "relations": ['
        result = repair_llm_json(raw)
        assert result is None

    def test_empty_string(self):
        assert repair_llm_json("") is None

    def test_no_json_at_all(self):
        assert repair_llm_json("This is just plain text with no JSON") is None

    def test_markdown_fences_with_preamble(self):
        raw = 'Sure! Here you go:\n```json\n{"entities": [{"name": "X", "entity_type": "tool"}], "relations": []}\n```\nHope that helps!'
        result = repair_llm_json(raw)
        assert result is not None
        assert result["entities"][0]["name"] == "X"


# ---------------------------------------------------------------------------
# Mock LLM client
# ---------------------------------------------------------------------------

class TestMockLLMClient:
    def test_matches_substring(self, mock_llm: MockLLMClient):
        response = mock_llm.extract("system", "I love Python")
        parsed = json.loads(response)
        assert any(e["name"] == "Python" for e in parsed["entities"])

    def test_case_insensitive_match(self, mock_llm: MockLLMClient):
        response = mock_llm.extract("system", "I LOVE PYTHON")
        parsed = json.loads(response)
        assert any(e["name"] == "Python" for e in parsed["entities"])

    def test_no_match_returns_empty(self, mock_llm: MockLLMClient):
        response = mock_llm.extract("system", "Hello there!")
        parsed = json.loads(response)
        assert parsed["entities"] == []
        assert parsed["relations"] == []

    def test_tracks_call_count(self, mock_llm: MockLLMClient):
        assert mock_llm.call_count == 0
        mock_llm.extract("sys", "msg1")
        mock_llm.extract("sys", "msg2")
        assert mock_llm.call_count == 2

    def test_tracks_last_prompts(self, mock_llm: MockLLMClient):
        mock_llm.extract("my system prompt", "hello world")
        assert mock_llm.last_system_prompt == "my system prompt"
        assert mock_llm.last_user_message == "hello world"


# ---------------------------------------------------------------------------
# Extraction pipeline — entity extraction
# ---------------------------------------------------------------------------

class TestEntityExtraction:
    def test_explicit_person(self, pipeline: ExtractionPipeline):
        result = pipeline.extract("My wife's name is Lena")
        names = {e.name for e in result.entities}
        assert "Lena" in names

    def test_tool_entity(self, pipeline: ExtractionPipeline):
        result = pipeline.extract("I love Python")
        types = {e.entity_type for e in result.entities if e.name == "Python"}
        assert "tool" in types

    def test_place_entity(self, pipeline: ExtractionPipeline):
        result = pipeline.extract("Lena and I are going to Tokyo in March")
        names = {e.name for e in result.entities}
        assert "Tokyo" in names

    def test_no_entities_from_filler(self, pipeline: ExtractionPipeline):
        result = pipeline.extract("Thanks!")
        assert result.entities == []
        assert result.relations == []

    def test_entity_properties_preserved(self, pipeline: ExtractionPipeline):
        result = pipeline.extract("My name is Alex and I'm a software engineer")
        alex = next((e for e in result.entities if e.name == "Alex"), None)
        assert alex is not None
        assert alex.properties.get("is_user") is True


# ---------------------------------------------------------------------------
# Extraction pipeline — relation extraction
# ---------------------------------------------------------------------------

class TestRelationExtraction:
    def test_explicit_relation(self, pipeline: ExtractionPipeline):
        result = pipeline.extract("My wife's name is Lena")
        assert any(r.relation == "married_to" for r in result.relations)

    def test_preference_relation(self, pipeline: ExtractionPipeline):
        result = pipeline.extract("I love Python")
        pref = next((r for r in result.relations if r.relation == "prefers"), None)
        assert pref is not None
        assert pref.target == "Python"
        assert pref.confidence >= 0.85

    def test_negative_relation(self, pipeline: ExtractionPipeline):
        result = pipeline.extract("I don't like Java")
        rel = next((r for r in result.relations if r.target == "Java"), None)
        assert rel is not None
        assert rel.relation == "dislikes"
        assert rel.confidence >= 0.80

    def test_hedged_relation_lower_confidence(self, pipeline: ExtractionPipeline):
        result = pipeline.extract("I might try Rust")
        rel = next((r for r in result.relations if r.target == "Rust"), None)
        assert rel is not None
        assert rel.confidence < 0.60

    def test_multi_entity_attribution(self, pipeline: ExtractionPipeline):
        result = pipeline.extract("She loves sushi but I prefer ramen")
        lena_pref = next(
            (r for r in result.relations if r.source == "Lena" and r.target == "sushi"), None
        )
        user_pref = next(
            (r for r in result.relations if r.source == "User" and r.target == "ramen"), None
        )
        assert lena_pref is not None
        assert user_pref is not None

    def test_relation_properties_preserved(self, pipeline: ExtractionPipeline):
        result = pipeline.extract("Lena and I are going to Tokyo in March")
        travel = next(
            (r for r in result.relations if r.relation == "traveling_to" and r.source == "User"),
            None,
        )
        assert travel is not None
        assert "timeframe" in travel.properties


# ---------------------------------------------------------------------------
# Extraction pipeline — result metadata
# ---------------------------------------------------------------------------

class TestExtractionResultMetadata:
    def test_duration_tracked(self, pipeline: ExtractionPipeline):
        result = pipeline.extract("I love Python")
        assert result.duration_ms >= 0

    def test_raw_response_captured(self, pipeline: ExtractionPipeline):
        result = pipeline.extract("I love Python")
        assert result.raw_response != ""
        # Should be valid JSON
        parsed = json.loads(result.raw_response)
        assert "entities" in parsed

    def test_empty_message_handled(self, pipeline: ExtractionPipeline):
        result = pipeline.extract("")
        assert isinstance(result, ExtractionResult)
        assert result.entities == []


# ---------------------------------------------------------------------------
# Extraction pipeline — resilience
# ---------------------------------------------------------------------------

class TestExtractionResilience:
    def test_llm_error_returns_empty_result(self):
        """If the LLM raises, the pipeline returns an empty result (never crashes)."""
        from neuroweave.extraction.llm_client import LLMError

        class FailingLLM:
            def extract(self, system_prompt: str, user_message: str) -> str:
                raise LLMError("API timeout")

        pipeline = ExtractionPipeline(FailingLLM())
        result = pipeline.extract("test message")
        assert result.entities == []
        assert result.relations == []

    def test_malformed_json_returns_empty_result(self):
        """If the LLM returns garbage, the pipeline returns an empty result."""

        class GarbageLLM:
            def extract(self, system_prompt: str, user_message: str) -> str:
                return "This is not JSON at all, just random text."

        pipeline = ExtractionPipeline(GarbageLLM())
        result = pipeline.extract("test message")
        assert result.entities == []
        assert result.relations == []

    def test_partial_entities_skipped(self):
        """Malformed entity dicts are skipped, valid ones are kept."""

        class PartialLLM:
            def extract(self, system_prompt: str, user_message: str) -> str:
                return json.dumps({
                    "entities": [
                        {"name": "Valid", "entity_type": "person"},
                        {"bad": "missing name field"},
                        "not a dict",
                        {"name": "", "entity_type": "person"},  # empty name
                    ],
                    "relations": [],
                })

        pipeline = ExtractionPipeline(PartialLLM())
        result = pipeline.extract("test")
        assert len(result.entities) == 1
        assert result.entities[0].name == "Valid"

    def test_confidence_clamped(self):
        """Confidence values outside [0, 1] are clamped."""

        class BadConfidenceLLM:
            def extract(self, system_prompt: str, user_message: str) -> str:
                return json.dumps({
                    "entities": [
                        {"name": "A", "entity_type": "person"},
                        {"name": "B", "entity_type": "person"},
                    ],
                    "relations": [
                        {"source": "A", "target": "B", "relation": "knows", "confidence": 1.5},
                        {"source": "B", "target": "A", "relation": "knows", "confidence": -0.3},
                    ],
                })

        pipeline = ExtractionPipeline(BadConfidenceLLM())
        result = pipeline.extract("test")
        assert result.relations[0].confidence == 1.0
        assert result.relations[1].confidence == 0.0
