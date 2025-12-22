"""
Schema definitions for the memory system.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime
import uuid


@dataclass
class MemoryItem:
    """A single memory item stored in the vector database."""
    id: str
    text: str
    role: str  # "user" | "assistant" | "system"
    timestamp: str  # ISO8601
    conversation_id: str
    tags: List[str] = field(default_factory=list)
    imported_at: Optional[str] = None  # Set during bulk import
    
    @classmethod
    def create(cls, text: str, role: str, conversation_id: str, 
               tags: List[str] = None) -> "MemoryItem":
        """Factory method to create a new MemoryItem with generated ID and timestamp."""
        return cls(
            id=str(uuid.uuid4()),
            text=text,
            role=role,
            timestamp=datetime.utcnow().isoformat() + "Z",
            conversation_id=conversation_id,
            tags=tags or [],
        )
    
    def to_payload(self) -> dict:
        """Convert to Qdrant payload format."""
        return {
            "text": self.text,
            "role": self.role,
            "timestamp": self.timestamp,
            "conversation_id": self.conversation_id,
            "tags": self.tags,
            "imported_at": self.imported_at,
        }
    
    @classmethod
    def from_payload(cls, id: str, payload: dict) -> "MemoryItem":
        """Create from Qdrant payload."""
        return cls(
            id=id,
            text=payload.get("text", ""),
            role=payload.get("role", ""),
            timestamp=payload.get("timestamp", ""),
            conversation_id=payload.get("conversation_id", ""),
            tags=payload.get("tags", []),
            imported_at=payload.get("imported_at"),
        )
