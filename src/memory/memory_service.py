"""
Memory service - business logic for the memory system.
"""

from typing import List, Optional, Callable, Dict, Any
from datetime import datetime

from .schema import MemoryItem
from .memory_repository import MemoryRepository
from .embedding_provider import EmbeddingProvider, get_embedding_provider, get_dimension_for_model


class MemoryService:
    """Service for managing conversation memories."""
    
    def __init__(
        self,
        db_path: str,
        embedding_mode: str = "local",
        embedding_model: str = "all-MiniLM-L6-v2",
        api_key: str = None,
        endpoint: str = None,
        dimension: int = None,
        event_bus=None,
        settings_manager=None
    ):
        """
        Initialize the memory service.
        
        Parameters
        ----------
        db_path : str
            Path to the Qdrant database directory
        embedding_mode : str
            One of: "local", "openai", "gemini", "cohere", "custom"
        embedding_model : str
            Model name for embeddings
        api_key : str
            API key for hosted providers
        endpoint : str
            Custom endpoint URL (for "custom" mode)
        dimension : int
            Vector dimension for custom models
        event_bus : EventBus
            Optional event bus for publishing events
        settings_manager : SettingsManager
            Optional settings manager for configuration
        """
        self.event_bus = event_bus
        self.settings_manager = settings_manager
        
        # Initialize embedding provider
        self._provider = get_embedding_provider(
            embedding_mode, embedding_model, api_key,
            endpoint=endpoint, dimension=dimension
        )
        
        # Initialize repository with correct vector size
        self._repository = MemoryRepository(db_path, self._provider.dimension)
    
    def add_memory(
        self,
        text: str,
        role: str,
        conversation_id: str,
        tags: List[str] = None
    ) -> str:
        """
        Add a memory item.
        
        Returns the ID of the created memory.
        """
        if not text or not text.strip():
            return None
        
        item = MemoryItem.create(text, role, conversation_id, tags)
        vector = self._provider.embed(text)
        self._repository.add(item, vector)
        
        print(f"[Memory] Stored {role} message ({len(text)} chars) from conversation {conversation_id[:20]}...")
        
        if self.event_bus:
            from events import EventType, Event
            self.event_bus.publish(Event(
                type=EventType.MEMORY_ADDED,
                data={"id": item.id, "conversation_id": conversation_id}
            ))
        
        return item.id
    
    def query_memory(
        self,
        query_text: str,
        k: int = 5,
        min_score: float = 0.0,
        exclude_conversation_id: str = None,
        role: str = None
    ) -> List[tuple]:
        """
        Query memories by semantic similarity.
        
        Returns list of (MemoryItem, score) tuples.
        """
        if not query_text or not query_text.strip():
            return []
        
        query_vector = self._provider.embed(query_text)
        results = self._repository.search(
            query_vector=query_vector,
            k=k,
            min_score=min_score,
            exclude_conversation_id=exclude_conversation_id,
            role=role
        )
        
        if results:
            print(f"[Memory] Query matched {len(results)} memories (min_score={min_score})")
            for item, score in results[:3]:  # Log top 3
                print(f"[Memory]   - score={score:.3f}: {item.text[:60]}...")
        
        if self.event_bus:
            from events import EventType, Event
            self.event_bus.publish(Event(
                type=EventType.MEMORY_QUERIED,
                data={"query": query_text, "results_count": len(results)}
            ))
        
        return results
    
    def get_context_for_llm(
        self,
        query_text: str,
        k: int = 5,
        min_score: float = 0.3,
        exclude_conversation_id: str = None
    ) -> str:
        """
        Get formatted memory context for injection into LLM prompt.
        
        Returns empty string if no relevant memories found.
        """
        results = self.query_memory(
            query_text,
            k=k,
            min_score=min_score,
            exclude_conversation_id=exclude_conversation_id
        )
        
        if not results:
            return ""
        
        lines = ["[Retrieved from past conversations:]"]
        for item, score in results:
            role_label = "User" if item.role == "user" else "Assistant"
            # Don't truncate with ... if text is short
            text_preview = item.text[:500] + "..." if len(item.text) > 500 else item.text
            lines.append(f"- {role_label}: {text_preview}")
        
        return "\n".join(lines)
    
    def delete_memory(self, memory_id: str) -> bool:
        """Delete a specific memory by ID."""
        result = self._repository.delete(memory_id)
        
        if self.event_bus:
            from events import EventType, Event
            self.event_bus.publish(Event(
                type=EventType.MEMORY_DELETED,
                data={"id": memory_id}
            ))
        
        return result
    
    def delete_conversation_memories(self, conversation_id: str) -> int:
        """Delete all memories for a conversation. Returns count deleted."""
        return self._repository.delete_by_conversation(conversation_id)
    
    def clear_all_memories(self) -> None:
        """Delete all memories."""
        self._repository.delete_all()
        
        if self.event_bus:
            from events import EventType, Event
            self.event_bus.publish(Event(
                type=EventType.MEMORY_CLEARED,
                data={}
            ))
    
    def is_conversation_imported(self, conversation_id: str) -> bool:
        """Check if a conversation is already in the memory database."""
        existing_ids = self._repository.get_conversation_ids()
        return conversation_id in existing_ids
    
    def import_conversation(
        self,
        conversation_id: str,
        messages: List[dict],
        store_mode: str = "all"
    ) -> int:
        """
        Import a conversation's messages into memory.
        
        Parameters
        ----------
        conversation_id : str
            The conversation ID
        messages : List[dict]
            List of message dicts with 'role' and 'content' keys
        store_mode : str
            "all", "user", or "assistant"
        
        Returns
        -------
        int
            Number of messages imported
        """
        items = []
        texts = []
        now = datetime.utcnow().isoformat() + "Z"
        
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            
            # Skip system messages and empty content
            if role == "system" or not content or not content.strip():
                continue
            
            # Filter by store_mode
            if store_mode == "user" and role != "user":
                continue
            if store_mode == "assistant" and role != "assistant":
                continue
            
            # Handle content that might be a list (vision messages)
            if isinstance(content, list):
                text_parts = [p.get("text", "") for p in content if p.get("type") == "text"]
                content = " ".join(text_parts)
            
            if not content.strip():
                continue
            
            item = MemoryItem.create(content, role, conversation_id)
            item.imported_at = now
            items.append(item)
            texts.append(content)
        
        if not items:
            return 0
        
        # Batch embed and store
        vectors = self._provider.embed_batch(texts)
        self._repository.add_batch(items, vectors)
        
        return len(items)
    
    def import_all_conversations(
        self,
        history_repo,
        store_mode: str = "all",
        progress_callback: Callable[[int, int, str], None] = None
    ) -> Dict[str, int]:
        """
        Import all existing conversations from history.
        
        Parameters
        ----------
        history_repo : ChatHistoryRepository
            The chat history repository
        store_mode : str
            "all", "user", or "assistant"
        progress_callback : Callable
            Called with (current, total, conversation_id) for progress updates
        
        Returns
        -------
        dict
            {"imported": n, "skipped": n, "messages": n}
        """
        existing_ids = self._repository.get_conversation_ids()
        all_chats = history_repo.list_all()
        
        imported = 0
        skipped = 0
        total_messages = 0
        
        for i, chat_id in enumerate(all_chats):
            if progress_callback:
                progress_callback(i, len(all_chats), chat_id)
            
            if chat_id in existing_ids:
                skipped += 1
                continue
            
            history = history_repo.get(chat_id)
            if history:
                count = self.import_conversation(chat_id, history, store_mode)
                total_messages += count
                imported += 1
        
        if progress_callback:
            progress_callback(len(all_chats), len(all_chats), "")
        
        if self.event_bus:
            from events import EventType, Event
            self.event_bus.publish(Event(
                type=EventType.MEMORY_IMPORT_COMPLETE,
                data={"imported": imported, "skipped": skipped, "messages": total_messages}
            ))
        
        return {"imported": imported, "skipped": skipped, "messages": total_messages}
    
    def get_stats(self) -> Dict[str, Any]:
        """Get memory database statistics."""
        return self._repository.get_stats()
    
    def close(self):
        """Close the memory service and release resources."""
        if self._repository:
            self._repository.close()
