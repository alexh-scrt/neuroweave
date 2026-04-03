"""Bulk document ingestion for full scientific papers."""

from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from neuroweave.extraction.pipeline import ExtractionPipeline
from neuroweave.graph.ingest import ingest_extraction


class ChunkStrategy(str, Enum):
    PARAGRAPH = "paragraph"  # split on blank lines
    FIXED = "fixed"  # split on fixed token count
    SECTION = "section"  # split on LaTeX \section{} markers
    SENTENCE = "sentence"  # split on sentence boundaries


@dataclass(frozen=True, slots=True)
class DocumentIngestionResult:
    doc_type: str
    chunk_count: int
    total_entities: int
    total_relations: int
    duration_ms: float
    chunks_failed: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class DocumentIngester:
    """Ingests full documents into the NeuroWeave knowledge graph.

    Chunks the document, runs extraction on each chunk concurrently,
    and materialises results into the graph store.
    """

    def __init__(
        self,
        pipeline: ExtractionPipeline,
        store: Any,
        chunk_strategy: ChunkStrategy = ChunkStrategy.PARAGRAPH,
        max_chunk_tokens: int = 2000,
        concurrent_chunks: int = 5,
    ) -> None:
        self._pipeline = pipeline
        self._store = store
        self._strategy = chunk_strategy
        self._max_chunk_tokens = max_chunk_tokens
        self._concurrency = concurrent_chunks

    async def ingest_document(
        self,
        text: str,
        doc_type: str = "paper",
        metadata: dict[str, Any] | None = None,
    ) -> DocumentIngestionResult:
        """Chunk text and extract entities/relations from each chunk concurrently."""
        import time

        start = time.time()
        chunks = self._chunk(text)
        semaphore = asyncio.Semaphore(self._concurrency)
        total_entities = 0
        total_relations = 0
        chunks_failed = 0

        async def process_chunk(chunk: str) -> None:
            nonlocal total_entities, total_relations, chunks_failed
            async with semaphore:
                result = await self._pipeline.extract(chunk)
                if result.entities or result.relations:
                    stats = ingest_extraction(self._store, result)
                    total_entities += stats.get("nodes_added", 0)
                    total_relations += stats.get("edges_added", 0)
                else:
                    chunks_failed += 1

        await asyncio.gather(*[process_chunk(c) for c in chunks])

        # If doc_type is "paper", create a PAPER node with metadata
        if doc_type == "paper" and metadata:
            from neuroweave.graph.store import Node, NodeType

            paper_node = Node(
                id=f"paper_{uuid.uuid4().hex[:12]}",
                name=metadata.get("title", "Unknown Paper"),
                node_type=NodeType.PAPER,
                properties=metadata,
            )
            self._store.add_node(paper_node)

        return DocumentIngestionResult(
            doc_type=doc_type,
            chunk_count=len(chunks),
            total_entities=total_entities,
            total_relations=total_relations,
            duration_ms=(time.time() - start) * 1000,
            chunks_failed=chunks_failed,
            metadata=metadata or {},
        )

    def _chunk(self, text: str) -> list[str]:
        """Split text into chunks according to the configured strategy."""
        if self._strategy == ChunkStrategy.PARAGRAPH:
            return self._chunk_by_paragraph(text)
        if self._strategy == ChunkStrategy.SECTION:
            return self._chunk_by_section(text)
        if self._strategy == ChunkStrategy.SENTENCE:
            return self._chunk_by_sentence(text)
        return self._chunk_fixed(text)

    def _chunk_by_paragraph(self, text: str) -> list[str]:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        return self._merge_short_chunks(paragraphs)

    def _chunk_by_section(self, text: str) -> list[str]:
        sections = re.split(r"(?=\\(?:sub)*section\{)", text)
        return [s.strip() for s in sections if s.strip()]

    def _chunk_by_sentence(self, text: str) -> list[str]:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        return self._merge_short_chunks(sentences)

    def _chunk_fixed(self, text: str) -> list[str]:
        words = text.split()
        chunks: list[str] = []
        current: list[str] = []
        for word in words:
            current.append(word)
            if len(current) >= self._max_chunk_tokens:
                chunks.append(" ".join(current))
                current = []
        if current:
            chunks.append(" ".join(current))
        return chunks

    def _merge_short_chunks(self, chunks: list[str], min_words: int = 50) -> list[str]:
        """Merge chunks shorter than min_words with the next chunk."""
        merged: list[str] = []
        buffer = ""
        for chunk in chunks:
            buffer = (buffer + " " + chunk).strip() if buffer else chunk
            if len(buffer.split()) >= min_words:
                merged.append(buffer)
                buffer = ""
        if buffer:
            merged.append(buffer)
        return merged
