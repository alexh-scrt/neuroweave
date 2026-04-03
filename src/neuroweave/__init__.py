"""NeuroWeave — Real-time knowledge graph memory for agentic AI platforms."""

__version__ = "0.2.0"

from neuroweave.api import ContextResult, EventType, NeuroWeave, ProcessResult
from neuroweave.graph.query import QueryResult, get_domain_graph, get_proof_chain, query_by_type
from neuroweave.graph.store import NodeType, RelationType
from neuroweave.ingest.document import ChunkStrategy, DocumentIngestionResult
from neuroweave.vector.qdrant_bridge import QdrantBridge, VectorContextResult

__all__ = [
    "ChunkStrategy",
    "ContextResult",
    "DocumentIngestionResult",
    "EventType",
    "NeuroWeave",
    "NodeType",
    "ProcessResult",
    "QdrantBridge",
    "QueryResult",
    "RelationType",
    "VectorContextResult",
    "get_domain_graph",
    "get_proof_chain",
    "query_by_type",
]
