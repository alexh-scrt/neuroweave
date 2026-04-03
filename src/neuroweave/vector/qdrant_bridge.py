"""Qdrant vector search bridge for NeuroWeave."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from qdrant_client import AsyncQdrantClient

from neuroweave.graph.query import QueryResult


@dataclass
class VectorContextResult:
    """Combined result from graph traversal + vector similarity search."""

    graph_context: QueryResult
    vector_matches: list[dict[str, Any]]
    combined_node_ids: set[str]
    query: str
    vector_collection: str

    def all_node_names(self) -> list[str]:
        names = [n.get("name", "") for n in self.graph_context.nodes]
        for hit in self.vector_matches:
            payload = hit.get("payload", {})
            if "name" in payload:
                names.append(payload["name"])
        return list(dict.fromkeys(names))  # deduplicated, order preserved


class QdrantBridge:
    """Combines NeuroWeave graph traversal with Qdrant vector similarity search."""

    def __init__(
        self,
        store: Any,
        qdrant_client: AsyncQdrantClient,
        collection: str = "ravennest_papers",
    ) -> None:
        self._store = store
        self._qdrant = qdrant_client
        self._collection = collection

    async def get_context_with_vectors(
        self,
        query: str,
        query_vector: list[float],
        top_k: int = 10,
        qdrant_filter: dict[str, Any] | None = None,
        graph_hops: int = 2,
    ) -> VectorContextResult:
        """Run graph NL query and vector search concurrently, merge results."""
        graph_task = asyncio.create_task(self._graph_query(query, graph_hops))
        vector_task = asyncio.create_task(self._vector_search(query_vector, top_k, qdrant_filter))
        graph_result, vector_hits = await asyncio.gather(graph_task, vector_task)

        graph_ids = {n.get("id", "") for n in graph_result.nodes}
        vector_ids = {hit.get("id", "") for hit in vector_hits}

        return VectorContextResult(
            graph_context=graph_result,
            vector_matches=vector_hits,
            combined_node_ids=graph_ids | vector_ids,
            query=query,
            vector_collection=self._collection,
        )

    async def _graph_query(self, query: str, max_hops: int) -> QueryResult:
        """Run a broad name-based graph search as fallback for NL queries."""
        words = [w for w in query.split() if len(w) > 4][:3]
        nodes: list[dict[str, Any]] = []
        for word in words:
            nodes.extend(await self._store.find_nodes(name_contains=word))
        if not nodes:
            return QueryResult(nodes=[], edges=[])
        node_ids = list({n["id"] for n in nodes})[:5]
        neighbors: list[dict[str, Any]] = []
        for nid in node_ids:
            neighbors.extend(await self._store.get_neighbors(nid, depth=max_hops))
        all_nodes = list({n["id"]: n for n in [*nodes, *neighbors]}.values())
        all_ids = {n["id"] for n in all_nodes}
        store_edges = await self._store.get_edges()
        all_edges = [
            e for e in store_edges
            if e.get("source_id") in all_ids and e.get("target_id") in all_ids
        ]
        return QueryResult(nodes=all_nodes, edges=all_edges)

    async def _vector_search(
        self,
        query_vector: list[float],
        top_k: int,
        qdrant_filter: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        filter_obj = None
        if qdrant_filter:
            from qdrant_client.models import Filter

            filter_obj = Filter(**qdrant_filter)
        results = await self._qdrant.search(
            collection_name=self._collection,
            query_vector=query_vector,
            limit=top_k,
            query_filter=filter_obj,
            with_payload=True,
        )
        return [
            {
                "id": str(hit.id),
                "score": hit.score,
                "payload": hit.payload or {},
            }
            for hit in results
        ]

    async def upsert_node_vectors(
        self,
        node_id: str,
        vector: list[float],
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Store a node's vector embedding in Qdrant alongside the graph node."""
        from qdrant_client.models import PointStruct

        node = await self._store.get_node(node_id)
        full_payload = {**(node or {}), **(payload or {})}
        await self._qdrant.upsert(
            collection_name=self._collection,
            points=[PointStruct(id=node_id, vector=vector, payload=full_payload)],
        )
