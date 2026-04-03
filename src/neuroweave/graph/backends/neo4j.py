"""Neo4j graph backend for persistent storage."""

from __future__ import annotations

import queue
import threading
from typing import Any

from neuroweave.graph.backends.base import AbstractGraphStore
from neuroweave.graph.store import Edge, GraphEvent, GraphEventType, Node


class Neo4jGraphStore(AbstractGraphStore):
    """Persistent graph backend backed by Neo4j.

    Requires: neo4j>=5.0 (pip install neo4j)
    Config keys:
        neo4j_uri:      str  — "neo4j://localhost:7687"
        neo4j_user:     str  — "neo4j"
        neo4j_password: str  — ""
        neo4j_database: str  — "neo4j"  (default)
    """

    def __init__(
        self,
        uri: str = "neo4j://localhost:7687",
        user: str = "neo4j",
        password: str = "",
        database: str = "neo4j",
    ) -> None:
        from neo4j import AsyncGraphDatabase  # deferred import

        self._driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
        self._database = database
        self._event_queue: queue.Queue[GraphEvent] | None = None
        self._lock = threading.Lock()
        self._node_count: int = 0
        self._edge_count: int = 0

    def set_event_queue(self, q: queue.Queue[GraphEvent]) -> None:  # type: ignore[type-arg]
        self._event_queue = q

    def set_event_bus(self, bus: Any) -> None:
        """Neo4j backend does not use EventBus directly; events go through queue."""
        pass

    def _emit(self, event: GraphEvent) -> None:
        if self._event_queue is not None:
            try:
                self._event_queue.put_nowait(event)
            except queue.Full:
                pass

    def add_node(self, node: Node) -> Node:
        """Upsert a node by id using MERGE. Thread-safe."""
        import asyncio

        asyncio.get_event_loop().run_until_complete(self._async_add_node(node))
        return node

    async def _async_add_node(self, node: Node) -> None:
        async with self._driver.session(database=self._database) as session:
            result = await session.run(
                """
                MERGE (n:NWNode {id: $id})
                ON CREATE SET
                    n.name = $name,
                    n.node_type = $node_type,
                    n.created_at = $created_at,
                    n.properties = $properties
                RETURN n.id AS id, count(*) AS created
                """,
                id=node.id,
                name=node.name,
                node_type=node.node_type.value,
                created_at=node.created_at,
                properties=str(node.properties),
            )
            record = await result.single()
            if record and record["created"]:
                with self._lock:
                    self._node_count += 1
                self._emit(GraphEvent(
                    event_type=GraphEventType.NODE_ADDED,
                    data={"id": node.id, "name": node.name, "node_type": node.node_type.value},
                ))

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        import asyncio

        return asyncio.get_event_loop().run_until_complete(self._async_get_node(node_id))

    async def _async_get_node(self, node_id: str) -> dict[str, Any] | None:
        async with self._driver.session(database=self._database) as session:
            result = await session.run(
                "MATCH (n:NWNode {id: $id}) RETURN n",
                id=node_id,
            )
            record = await result.single()
            if not record:
                return None
            n = record["n"]
            return dict(n)

    def find_nodes(
        self,
        node_type: str | None = None,
        name_contains: str | None = None,
    ) -> list[dict[str, Any]]:
        import asyncio

        return asyncio.get_event_loop().run_until_complete(
            self._async_find_nodes(node_type, name_contains)
        )

    async def _async_find_nodes(
        self,
        node_type: str | None,
        name_contains: str | None,
    ) -> list[dict[str, Any]]:
        clauses = ["MATCH (n:NWNode)"]
        params: dict[str, Any] = {}
        where: list[str] = []
        if node_type:
            where.append("n.node_type = $node_type")
            params["node_type"] = node_type
        if name_contains:
            where.append("toLower(n.name) CONTAINS toLower($name_contains)")
            params["name_contains"] = name_contains
        if where:
            clauses.append("WHERE " + " AND ".join(where))
        clauses.append("RETURN n")
        cypher = "\n".join(clauses)
        async with self._driver.session(database=self._database) as session:
            result = await session.run(cypher, **params)
            return [dict(record["n"]) async for record in result]

    def add_edge(self, edge: Edge) -> Edge:
        import asyncio

        asyncio.get_event_loop().run_until_complete(self._async_add_edge(edge))
        return edge

    async def _async_add_edge(self, edge: Edge) -> None:
        async with self._driver.session(database=self._database) as session:
            await session.run(
                """
                MATCH (src:NWNode {id: $source_id})
                MATCH (tgt:NWNode {id: $target_id})
                MERGE (src)-[r:NW_EDGE {id: $id}]->(tgt)
                ON CREATE SET
                    r.relation = $relation,
                    r.confidence = $confidence,
                    r.created_at = $created_at,
                    r.properties = $properties
                """,
                id=edge.id,
                source_id=edge.source_id,
                target_id=edge.target_id,
                relation=edge.relation,
                confidence=edge.confidence,
                created_at=edge.created_at,
                properties=str(edge.properties),
            )
        with self._lock:
            self._edge_count += 1
        self._emit(GraphEvent(
            event_type=GraphEventType.EDGE_ADDED,
            data={
                "id": edge.id,
                "source_id": edge.source_id,
                "target_id": edge.target_id,
                "relation": edge.relation,
                "confidence": edge.confidence,
            },
        ))

    def get_edges(
        self,
        source_id: str | None = None,
        target_id: str | None = None,
        relation: str | None = None,
    ) -> list[dict[str, Any]]:
        import asyncio

        return asyncio.get_event_loop().run_until_complete(
            self._async_get_edges(source_id, target_id, relation)
        )

    async def _async_get_edges(
        self,
        source_id: str | None,
        target_id: str | None,
        relation: str | None,
    ) -> list[dict[str, Any]]:
        clauses = ["MATCH (src:NWNode)-[r:NW_EDGE]->(tgt:NWNode)"]
        params: dict[str, Any] = {}
        where: list[str] = []
        if source_id:
            where.append("src.id = $source_id")
            params["source_id"] = source_id
        if target_id:
            where.append("tgt.id = $target_id")
            params["target_id"] = target_id
        if relation:
            where.append("r.relation = $relation")
            params["relation"] = relation
        if where:
            clauses.append("WHERE " + " AND ".join(where))
        clauses.append("RETURN r, src.id AS source_id, tgt.id AS target_id")
        cypher = "\n".join(clauses)
        async with self._driver.session(database=self._database) as session:
            result = await session.run(cypher, **params)
            edges = []
            async for record in result:
                e = dict(record["r"])
                e["source_id"] = record["source_id"]
                e["target_id"] = record["target_id"]
                edges.append(e)
            return edges

    def get_neighbors(self, node_id: str, depth: int = 1) -> list[dict[str, Any]]:
        import asyncio

        return asyncio.get_event_loop().run_until_complete(
            self._async_get_neighbors(node_id, depth)
        )

    async def _async_get_neighbors(self, node_id: str, depth: int) -> list[dict[str, Any]]:
        async with self._driver.session(database=self._database) as session:
            result = await session.run(
                f"""
                MATCH (root:NWNode {{id: $node_id}})
                MATCH (root)-[:NW_EDGE*1..{depth}]-(neighbor:NWNode)
                WHERE neighbor.id <> root.id
                RETURN DISTINCT neighbor
                """,
                node_id=node_id,
            )
            return [dict(record["neighbor"]) async for record in result]

    def to_dict(self) -> dict[str, Any]:
        import asyncio

        return asyncio.get_event_loop().run_until_complete(self._async_to_dict())

    async def _async_to_dict(self) -> dict[str, Any]:
        async with self._driver.session(database=self._database) as session:
            node_result = await session.run("MATCH (n:NWNode) RETURN n")
            nodes = [dict(r["n"]) async for r in node_result]
            edge_result = await session.run(
                "MATCH (src:NWNode)-[r:NW_EDGE]->(tgt:NWNode) "
                "RETURN r, src.id AS source_id, tgt.id AS target_id"
            )
            edges = []
            async for r in edge_result:
                e = dict(r["r"])
                e["source_id"] = r["source_id"]
                e["target_id"] = r["target_id"]
                edges.append(e)
        return {
            "nodes": nodes,
            "edges": edges,
            "stats": {"node_count": len(nodes), "edge_count": len(edges)},
        }

    def update_node_properties(self, node_id: str, properties: dict[str, Any]) -> None:
        import asyncio

        asyncio.get_event_loop().run_until_complete(
            self._async_update_node_properties(node_id, properties)
        )

    async def _async_update_node_properties(
        self, node_id: str, properties: dict[str, Any]
    ) -> None:
        async with self._driver.session(database=self._database) as session:
            await session.run(
                """
                MATCH (n:NWNode {id: $id})
                SET n.properties = $properties
                """,
                id=node_id,
                properties=str(properties),
            )
        self._emit(GraphEvent(
            event_type=GraphEventType.NODE_UPDATED,
            data={"id": node_id, "properties": properties},
        ))

    @property
    def node_count(self) -> int:
        with self._lock:
            return self._node_count

    @property
    def edge_count(self) -> int:
        with self._lock:
            return self._edge_count

    async def close(self) -> None:
        """Close the Neo4j driver. Call on shutdown."""
        await self._driver.close()
