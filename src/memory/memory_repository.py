"""
Memory repository using Qdrant for vector storage.
"""

from typing import List, Optional, Set, Dict, Any
from pathlib import Path
import os

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
)

from .schema import MemoryItem


class MemoryRepository:
    """Repository for storing and retrieving memory items using Qdrant."""
    
    COLLECTION_NAME = "memory"
    
    def __init__(self, path: str, vector_size: int = 384):
        """
        Initialize the memory repository.
        
        Parameters
        ----------
        path : str
            Path to the Qdrant database directory
        vector_size : int
            Dimension of the embedding vectors
        """
        self.path = path
        self.vector_size = vector_size
        
        # Ensure directory exists
        Path(path).mkdir(parents=True, exist_ok=True)
        
        # Initialize Qdrant client in embedded mode
        self._client = QdrantClient(path=path)
        self._ensure_collection()
    
    def _ensure_collection(self):
        """Create collection if it doesn't exist. Raises error if dimension mismatches."""
        collections = self._client.get_collections().collections
        exists = any(c.name == self.COLLECTION_NAME for c in collections)
        
        if exists:
            info = self._client.get_collection(self.COLLECTION_NAME)
            current_size = info.config.params.vectors.size
            if current_size != self.vector_size:
                raise ValueError(
                    f"Embedding dimension mismatch: database has {current_size}, "
                    f"but model produces {self.vector_size}. "
                    f"To switch models: Settings → Memory → Clear, then Import to rebuild."
                )
        
        if not exists:
            self._client.create_collection(
                collection_name=self.COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=self.vector_size,
                    distance=Distance.COSINE
                )
            )
    
    def add(self, item: MemoryItem, vector: List[float]) -> None:
        """Add a memory item with its embedding vector."""
        point = PointStruct(
            id=item.id,
            vector=vector,
            payload=item.to_payload()
        )
        self._client.upsert(
            collection_name=self.COLLECTION_NAME,
            points=[point]
        )
    
    def add_batch(self, items: List[MemoryItem], vectors: List[List[float]]) -> None:
        """Add multiple memory items with their embedding vectors."""
        if not items:
            return
        points = [
            PointStruct(id=item.id, vector=vec, payload=item.to_payload())
            for item, vec in zip(items, vectors)
        ]
        self._client.upsert(
            collection_name=self.COLLECTION_NAME,
            points=points
        )
    
    def search(
        self,
        query_vector: List[float],
        k: int = 5,
        min_score: float = 0.0,
        conversation_id: Optional[str] = None,
        exclude_conversation_id: Optional[str] = None,
        role: Optional[str] = None
    ) -> List[tuple]:
        """
        Search for similar memories.
        
        Returns list of (MemoryItem, score) tuples sorted by relevance.
        """
        query_filter = None
        conditions = []
        
        if conversation_id:
            conditions.append(
                FieldCondition(key="conversation_id", match=MatchValue(value=conversation_id))
            )
        if role:
            conditions.append(
                FieldCondition(key="role", match=MatchValue(value=role))
            )
        
        if conditions:
            query_filter = Filter(must=conditions)
        
        results = self._client.query_points(
            collection_name=self.COLLECTION_NAME,
            query=query_vector,
            limit=k * 2 if exclude_conversation_id else k,  # Fetch extra if filtering
            query_filter=query_filter,
            score_threshold=min_score
        ).points
        
        items = []
        for r in results:
            if exclude_conversation_id and r.payload.get("conversation_id") == exclude_conversation_id:
                continue
            item = MemoryItem.from_payload(r.id, r.payload)
            items.append((item, r.score))
            if len(items) >= k:
                break
        
        return items
    
    def delete(self, id: str) -> bool:
        """Delete a memory item by ID."""
        self._client.delete(
            collection_name=self.COLLECTION_NAME,
            points_selector=[id]
        )
        return True
    
    def delete_by_conversation(self, conversation_id: str) -> int:
        """Delete all memories for a conversation. Returns count deleted."""
        # Get count first
        results = self._client.scroll(
            collection_name=self.COLLECTION_NAME,
            scroll_filter=Filter(
                must=[FieldCondition(key="conversation_id", match=MatchValue(value=conversation_id))]
            ),
            limit=10000
        )
        count = len(results[0])
        
        if count > 0:
            ids = [p.id for p in results[0]]
            self._client.delete(
                collection_name=self.COLLECTION_NAME,
                points_selector=ids
            )
        return count
    
    def delete_all(self) -> None:
        """Delete all memories."""
        self._client.delete_collection(self.COLLECTION_NAME)
        self._ensure_collection()
    
    def get_conversation_ids(self) -> Set[str]:
        """Get all unique conversation IDs in the database."""
        ids = set()
        offset = None
        
        while True:
            results, offset = self._client.scroll(
                collection_name=self.COLLECTION_NAME,
                limit=1000,
                offset=offset,
                with_payload=["conversation_id"]
            )
            for point in results:
                if point.payload and "conversation_id" in point.payload:
                    ids.add(point.payload["conversation_id"])
            if offset is None:
                break
        
        return ids
    
    def get_stats(self) -> Dict[str, Any]:
        """Get collection statistics."""
        try:
            info = self._client.get_collection(self.COLLECTION_NAME)
            return {
                "count": info.points_count,
                "vector_size": info.config.params.vectors.size,
                "status": info.status.value if hasattr(info.status, 'value') else str(info.status),
            }
        except Exception as e:
            return {"count": 0, "error": str(e)}
    
    def close(self):
        """Close the Qdrant client."""
        if self._client:
            self._client.close()
