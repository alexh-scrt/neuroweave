"""Neo4j graph backend for persistent storage — fully async."""

from __future__ import annotations

import queue
import threading
from typing import Any

from neuroweave.graph.backends.base import AbstractGraphStore
from neuroweave.graph.store import Edge, GraphEvent, GraphEventType, Node


class Neo4jGraphStore(AbstractGraphStore):
    """Persistent graph backend backed by Neo4j.

    All public methods are natively async — no sync-to-async bridging needed.

    Requires: neo4j>=5.0 (pip install neuroweave-python[neo4j])
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
        self._event_bus: Any | None = None
        self._lock = threading.Lock()
        self._node_count: int = 0
        self._edge_count: int = 0

    def _emit(self, event: GraphEvent) -> None:
        if self._event_bus is not None:
            self._event_bus.emit(event)
        elif self._event_queue is not None:
            try:
                self._event_queue.put_nowait(event)
            except queue.Full:
                pass

    def set_event_bus(self, bus: Any) -> None:
        self._event_bus = bus

    async def initialize(self) -> None:
        """Create uniqueness constraints and indexes. Idempotent."""
        async with self._driver.session(database=self._database) as session:
            await session.run(
                "CREATE CONSTRAINT nwnode_id_unique IF NOT EXISTS "
                "FOR (n:NWNode) REQUIRE n.id IS UNIQUE"
            )
            await session.run(
                "CREATE INDEX nwnode_name_idx IF NOT EXISTS "
                "FOR (n:NWNode) ON (n.name)"
            )
            await session.run(
                "CREATE INDEX nwnode_type_idx IF NOT EXISTS "
                "FOR (n:NWNode) ON (n.node_type)"
            )
            await session.run(
                "CREATE INDEX nwedge_relation_idx IF NOT EXISTS "
                "FOR ()-[r:NW_EDGE]-() ON (r.relation)"
            )

    async def set_event_queue(self, q: queue.Queue[GraphEvent]) -> None:  # type: ignore[override]
        self._event_queue = q

    async def add_node(self, node: Node) -> Node:
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
                node_type=node.node_type.value if hasattr(node.node_type, "value") else node.node_type,
                created_at=node.created_at,
                properties=str(node.properties),
            )
            record = await result.single()
            if record and record["created"]:
                with self._lock:
                    self._node_count += 1
                self._emit(GraphEvent(
                    event_type=GraphEventType.NODE_ADDED,
                    data={"id": node.id, "name": node.name, "node_type": str(node.node_type)},
                ))
        return node

    async def get_node(self, node_id: str) -> dict[str, Any] | None:
        async with self._driver.session(database=self._database) as session:
            result = await session.run(
                "MATCH (n:NWNode {id: $id}) RETURN properties(n) AS props",
                id=node_id,
            )
            record = await result.single()
            return dict(record["props"]) if record else None

    async def find_nodes(
        self,
        node_type: str | None = None,
        name_contains: str | None = None,
    ) -> list[dict[str, Any]]:
        parts = ["MATCH (n:NWNode)"]
        params: dict[str, Any] = {}
        where: list[str] = []
        if node_type:
            where.append("n.node_type = $node_type")
            params["node_type"] = node_type
        if name_contains:
            where.append("toLower(n.name) CONTAINS toLower($name_contains)")
            params["name_contains"] = name_contains
        if where:
            parts.append("WHERE " + " AND ".join(where))
        parts.append("RETURN properties(n) AS props")
        cypher = "\n".join(parts)
        async with self._driver.session(database=self._database) as session:
            result = await session.run(cypher, **params)
            return [dict(r["props"]) async for r in result]

    async def add_edge(self, edge: Edge) -> Edge:
        async with self._driver.session(database=self._database) as session:
            await session.run(
                """
                MATCH (src:NWNode {id: $source_id})
                MATCH (tgt:NWNode {id: $target_id})
                MERGE (src)-[r:NW_EDGE {id: $id}]->(tgt)
                ON CREATE SET
                    r.relation   = $relation,
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
        return edge

    async def get_edges(
        self,
        source_id: str | None = None,
        target_id: str | None = None,
        relation: str | None = None,
    ) -> list[dict[str, Any]]:
        parts = ["MATCH (src:NWNode)-[r:NW_EDGE]->(tgt:NWNode)"]
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
            parts.append("WHERE " + " AND ".join(where))
        parts.append("RETURN properties(r) AS props, src.id AS source_id, tgt.id AS target_id")
        cypher = "\n".join(parts)
        async with self._driver.session(database=self._database) as session:
            result = await session.run(cypher, **params)
            rows = []
            async for record in result:
                e = dict(record["props"])
                e["source_id"] = record["source_id"]
                e["target_id"] = record["target_id"]
                rows.append(e)
            return rows

    async def get_neighbors(self, node_id: str, depth: int = 1) -> list[dict[str, Any]]:
        async with self._driver.session(database=self._database) as session:
            result = await session.run(
                f"""
                MATCH (root:NWNode {{id: $id}})
                MATCH (root)-[:NW_EDGE*1..{int(depth)}]-(neighbor:NWNode)
                WHERE neighbor.id <> root.id
                RETURN DISTINCT properties(neighbor) AS props
                """,
                id=node_id,
            )
            return [dict(r["props"]) async for r in result]

    async def update_node_properties(self, node_id: str, properties: dict[str, Any]) -> None:
        async with self._driver.session(database=self._database) as session:
            result = await session.run(
                "MATCH (n:NWNode {id: $id}) RETURN properties(n) AS props",
                id=node_id,
            )
            record = await result.single()
            if not record:
                return
            existing = dict(record["props"]).get("properties", {})
            if isinstance(existing, str):
                import ast
                try:
                    existing = ast.literal_eval(existing)
                except Exception:
                    existing = {}
            merged = {**existing, **properties}
            await session.run(
                "MATCH (n:NWNode {id: $id}) SET n.properties = $props",
                id=node_id,
                props=str(merged),
            )
        self._emit(GraphEvent(
            event_type=GraphEventType.NODE_UPDATED,
            data={"id": node_id, "properties": merged},
        ))

    async def to_dict(self) -> dict[str, Any]:
        async with self._driver.session(database=self._database) as session:
            node_result = await session.run(
                "MATCH (n:NWNode) RETURN properties(n) AS props"
            )
            nodes = [dict(r["props"]) async for r in node_result]
            edge_result = await session.run(
                """
                MATCH (src:NWNode)-[r:NW_EDGE]->(tgt:NWNode)
                RETURN properties(r) AS props, src.id AS source_id, tgt.id AS target_id
                """
            )
            edges = []
            async for r in edge_result:
                e = dict(r["props"])
                e["source_id"] = r["source_id"]
                e["target_id"] = r["target_id"]
                edges.append(e)
        return {
            "nodes": nodes,
            "edges": edges,
            "stats": {"node_count": len(nodes), "edge_count": len(edges)},
        }

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
