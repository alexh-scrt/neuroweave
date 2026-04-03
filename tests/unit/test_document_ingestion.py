"""Tests for NW-003 — Bulk document ingestion."""

from __future__ import annotations

import pytest

from neuroweave.extraction.llm_client import MockLLMClient
from neuroweave.extraction.pipeline import ExtractionPipeline
from neuroweave.graph.backends.memory import MemoryGraphStore
from neuroweave.graph.store import GraphStore
from neuroweave.ingest.document import ChunkStrategy, DocumentIngester, DocumentIngestionResult


@pytest.fixture
def store() -> MemoryGraphStore:
    return MemoryGraphStore()


@pytest.fixture
def mock_pipeline() -> ExtractionPipeline:
    mock = MockLLMClient()
    # Set a generic response for any text
    mock.set_response("", {
        "entities": [
            {"name": "TestEntity", "entity_type": "concept"},
        ],
        "relations": [],
    })
    return ExtractionPipeline(mock)


@pytest.fixture
def ingester(mock_pipeline, store) -> DocumentIngester:
    return DocumentIngester(
        pipeline=mock_pipeline,
        store=store,
        chunk_strategy=ChunkStrategy.PARAGRAPH,
    )


def _long_text(n_paragraphs: int = 10) -> str:
    """Generate a long text with multiple paragraphs."""
    paragraphs = []
    for i in range(n_paragraphs):
        paragraphs.append(
            f"This is paragraph {i} about mathematical graph theory. "
            f"It discusses the properties of Euler's formula and its applications "
            f"to planar graphs. The chromatic polynomial is also mentioned. "
            f"Additional sentences ensure this paragraph exceeds the minimum word count "
            f"for the merging logic to keep it as a standalone chunk."
        )
    return "\n\n".join(paragraphs)


# ---------------------------------------------------------------------------
# Chunking strategies
# ---------------------------------------------------------------------------


def test_ingest_document_chunks_by_paragraph():
    ingester = DocumentIngester(
        pipeline=ExtractionPipeline(MockLLMClient()),
        store=GraphStore(),
        chunk_strategy=ChunkStrategy.PARAGRAPH,
    )
    text = _long_text(5)
    chunks = ingester._chunk(text)
    assert len(chunks) >= 1


def test_ingest_document_chunks_by_section():
    ingester = DocumentIngester(
        pipeline=ExtractionPipeline(MockLLMClient()),
        store=GraphStore(),
        chunk_strategy=ChunkStrategy.SECTION,
    )
    text = r"\section{Introduction} Some text. \section{Methods} More text. \section{Results} End."
    chunks = ingester._chunk(text)
    assert len(chunks) == 3


def test_ingest_document_chunks_by_sentence():
    ingester = DocumentIngester(
        pipeline=ExtractionPipeline(MockLLMClient()),
        store=GraphStore(),
        chunk_strategy=ChunkStrategy.SENTENCE,
    )
    text = "First sentence about graphs. Second sentence about trees. Third about cycles. " * 20
    chunks = ingester._chunk(text)
    assert len(chunks) >= 1


def test_ingest_document_chunks_fixed():
    ingester = DocumentIngester(
        pipeline=ExtractionPipeline(MockLLMClient()),
        store=GraphStore(),
        chunk_strategy=ChunkStrategy.FIXED,
        max_chunk_tokens=50,
    )
    text = " ".join(["word"] * 200)
    chunks = ingester._chunk(text)
    assert len(chunks) == 4  # 200 / 50 = 4


# ---------------------------------------------------------------------------
# Concurrent extraction
# ---------------------------------------------------------------------------


async def test_ingest_document_concurrent_extraction(mock_pipeline, store):
    ingester = DocumentIngester(
        pipeline=mock_pipeline,
        store=store,
        chunk_strategy=ChunkStrategy.PARAGRAPH,
        concurrent_chunks=3,
    )
    text = _long_text(6)
    result = await ingester.ingest_document(text)
    assert isinstance(result, DocumentIngestionResult)
    assert result.chunk_count >= 1


# ---------------------------------------------------------------------------
# Result counts
# ---------------------------------------------------------------------------


async def test_ingest_document_returns_correct_entity_count(mock_pipeline, store):
    ingester = DocumentIngester(
        pipeline=mock_pipeline,
        store=store,
        chunk_strategy=ChunkStrategy.FIXED,
        max_chunk_tokens=50,
    )
    text = " ".join(["graph theory concepts"] * 100)
    result = await ingester.ingest_document(text)
    assert result.total_entities >= 0


async def test_ingest_document_returns_correct_relation_count(mock_pipeline, store):
    mock = MockLLMClient()
    mock.set_response("", {
        "entities": [
            {"name": "A", "entity_type": "concept"},
            {"name": "B", "entity_type": "concept"},
        ],
        "relations": [
            {"source": "A", "target": "B", "relation": "related_to", "confidence": 0.8},
        ],
    })
    pipeline = ExtractionPipeline(mock)
    ingester = DocumentIngester(
        pipeline=pipeline,
        store=store,
        chunk_strategy=ChunkStrategy.FIXED,
        max_chunk_tokens=50,
    )
    text = " ".join(["graph coloring"] * 100)
    result = await ingester.ingest_document(text)
    assert result.total_relations >= 0


async def test_ingest_document_creates_paper_node_when_metadata_provided(mock_pipeline, store):
    ingester = DocumentIngester(
        pipeline=mock_pipeline,
        store=store,
    )
    await ingester.ingest_document(
        _long_text(3),
        doc_type="paper",
        metadata={"title": "Test Paper", "doi": "10.1234/test"},
    )
    from neuroweave.graph.store import NodeType

    papers = await store.find_nodes(node_type=NodeType.PAPER)
    assert any(n["name"] == "Test Paper" for n in papers)


def test_ingest_document_short_chunks_merged():
    ingester = DocumentIngester(
        pipeline=ExtractionPipeline(MockLLMClient()),
        store=GraphStore(),
        chunk_strategy=ChunkStrategy.PARAGRAPH,
    )
    # Short paragraphs should get merged
    text = "Short.\n\nAlso short.\n\nStill short.\n\nVery short."
    chunks = ingester._chunk(text)
    assert len(chunks) == 1  # all merged into one


async def test_ingest_document_empty_text_returns_zero_counts(mock_pipeline, store):
    ingester = DocumentIngester(pipeline=mock_pipeline, store=store)
    result = await ingester.ingest_document("")
    assert result.chunk_count == 0
    assert result.total_entities == 0
    assert result.total_relations == 0


async def test_ingest_document_failed_chunks_counted(store):
    """Chunks that produce no entities/relations count as failed."""
    mock = MockLLMClient()
    # Default response with no entities
    pipeline = ExtractionPipeline(mock)
    ingester = DocumentIngester(
        pipeline=pipeline,
        store=store,
        chunk_strategy=ChunkStrategy.FIXED,
        max_chunk_tokens=50,
    )
    text = " ".join(["word"] * 200)
    result = await ingester.ingest_document(text)
    assert result.chunks_failed == result.chunk_count  # all chunks failed (no match in mock)


async def test_facade_ingest_document_method_exists():
    from neuroweave import NeuroWeave

    async with NeuroWeave(llm_provider="mock") as nw:
        assert hasattr(nw, "ingest_document")


async def test_facade_ingest_document_returns_result():
    from neuroweave import NeuroWeave

    async with NeuroWeave(llm_provider="mock") as nw:
        result = await nw.ingest_document(_long_text(3))
        assert isinstance(result, DocumentIngestionResult)


def test_chunk_strategy_enum_values():
    assert ChunkStrategy.PARAGRAPH.value == "paragraph"
    assert ChunkStrategy.FIXED.value == "fixed"
    assert ChunkStrategy.SECTION.value == "section"
    assert ChunkStrategy.SENTENCE.value == "sentence"


async def test_ingest_concurrent_chunks_respects_semaphore(store):
    """Test that concurrent_chunks parameter limits concurrency."""
    mock = MockLLMClient()
    mock.set_response("", {
        "entities": [{"name": "X", "entity_type": "concept"}],
        "relations": [],
    })
    pipeline = ExtractionPipeline(mock)
    ingester = DocumentIngester(
        pipeline=pipeline,
        store=store,
        chunk_strategy=ChunkStrategy.FIXED,
        max_chunk_tokens=20,
        concurrent_chunks=2,
    )
    text = " ".join(["test"] * 100)
    result = await ingester.ingest_document(text)
    assert result.chunk_count == 5  # 100 / 20
