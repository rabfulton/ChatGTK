"""
Repository for managing chat history persistence.
"""

import os
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from .base import Repository
from conversation import ConversationHistory, Message
from config import HISTORY_DIR


@dataclass
class ChatMetadata:
    """Metadata about a chat conversation."""
    chat_id: str
    title: str
    timestamp: datetime
    message_count: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'chat_id': self.chat_id,
            'title': self.title,
            'timestamp': self.timestamp.isoformat(),
            'message_count': self.message_count,
        }


@dataclass
class SearchResult:
    """Result from a chat history search."""
    chat_id: str
    chat_title: str
    matches: List[str]
    relevance_score: float = 1.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'chat_id': self.chat_id,
            'chat_title': self.chat_title,
            'matches': self.matches,
            'relevance_score': self.relevance_score,
        }


class ChatHistoryRepository(Repository[ConversationHistory]):
    """
    Repository for managing chat conversation history.
    
    This repository handles loading, saving, and searching chat histories
    stored as JSON files in the history directory.
    """
    
    def __init__(self, history_dir: str = None):
        """
        Initialize the chat history repository.
        
        Parameters
        ----------
        history_dir : str, optional
            Directory where chat histories are stored.
            Defaults to HISTORY_DIR from config.
        """
        self.history_dir = Path(history_dir or HISTORY_DIR)
        self._ensure_history_dir()
    
    def _ensure_history_dir(self) -> None:
        """Ensure the history directory exists."""
        self.history_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_chat_path(self, chat_id: str) -> Path:
        """Get the file path for a chat ID."""
        # Strip .json if already present to avoid .json.json
        if chat_id.endswith('.json'):
            chat_id = chat_id[:-5]
        return self.history_dir / f"{chat_id}.json"
    
    def get(self, chat_id: str) -> Optional[ConversationHistory]:
        """
        Load a chat history by ID.
        
        Parameters
        ----------
        chat_id : str
            The unique identifier of the chat.
            
        Returns
        -------
        Optional[ConversationHistory]
            The conversation history if found, None otherwise.
        """
        chat_path = self._get_chat_path(chat_id)
        
        if not chat_path.exists():
            return None
        
        try:
            with open(chat_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            messages = data.get('messages', [])
            metadata = data.get('metadata', {})
            system_message = "You are a helpful assistant."
            
            # Extract system message if present
            if messages and messages[0].get('role') == 'system':
                system_message = messages[0].get('content', system_message)
            
            return ConversationHistory.from_list(messages, default_system=system_message, metadata=metadata)
            
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading chat {chat_id}: {e}")
            return None
    
    def save(self, chat_id: str, history, metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        Save a chat history.
        
        Parameters
        ----------
        chat_id : str
            The unique identifier for the chat.
        history : ConversationHistory or List[Dict]
            The conversation history to save.
        metadata : Optional[Dict[str, Any]]
            Optional metadata to save with the chat.
        """
        chat_path = self._get_chat_path(chat_id)
        
        try:
            # Handle both ConversationHistory and list formats
            if isinstance(history, ConversationHistory):
                messages = history.to_list()
                meta = history.metadata or {}
            else:
                messages = history
                meta = {}
            
            # Merge with provided metadata
            if metadata:
                meta.update(metadata)
            
            data = {
                'messages': messages,
                'timestamp': datetime.now().isoformat(),
            }
            if meta:
                data['metadata'] = meta
            
            with open(chat_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
        except IOError as e:
            print(f"Error saving chat {chat_id}: {e}")
            raise
    
    def delete(self, chat_id: str) -> bool:
        """
        Delete a chat history.
        
        Parameters
        ----------
        chat_id : str
            The unique identifier of the chat to delete.
            
        Returns
        -------
        bool
            True if the chat was deleted, False if not found.
        """
        chat_path = self._get_chat_path(chat_id)
        
        if not chat_path.exists():
            return False
        
        try:
            chat_path.unlink()
            
            # Also delete associated images/audio directory if it exists
            chat_dir = self.history_dir / chat_id
            if chat_dir.exists() and chat_dir.is_dir():
                import shutil
                shutil.rmtree(chat_dir)
            
            return True
            
        except IOError as e:
            print(f"Error deleting chat {chat_id}: {e}")
            return False
    
    def list_all(self) -> List[ChatMetadata]:
        """
        List all available chat histories.
        
        Returns
        -------
        List[ChatMetadata]
            A list of metadata for all chats, sorted by timestamp (newest first).
        """
        chats = []
        
        for chat_file in self.history_dir.glob("*.json"):
            chat_id = chat_file.stem
            
            try:
                with open(chat_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                messages = data.get('messages', [])
                metadata = data.get('metadata', {})
                timestamp_str = data.get('timestamp', '')
                
                # Parse timestamp
                try:
                    timestamp = datetime.fromisoformat(timestamp_str)
                except (ValueError, TypeError):
                    timestamp = datetime.fromtimestamp(chat_file.stat().st_mtime)
                
                # Use metadata title if set, otherwise generate from messages
                title = metadata.get('title') or self._generate_title(messages, chat_id)
                
                chats.append(ChatMetadata(
                    chat_id=chat_id,
                    title=title,
                    timestamp=timestamp,
                    message_count=len(messages),
                ))
                
            except (json.JSONDecodeError, IOError) as e:
                print(f"Error reading chat metadata for {chat_id}: {e}")
                continue
        
        # Sort by timestamp, newest first
        chats.sort(key=lambda c: c.timestamp, reverse=True)
        return chats
    
    def _generate_title(self, messages: List[Dict[str, Any]], fallback: str) -> str:
        """
        Generate a title for a chat from its messages.
        
        Parameters
        ----------
        messages : List[Dict[str, Any]]
            The chat messages.
        fallback : str
            Fallback title if no suitable message found.
            
        Returns
        -------
        str
            The generated title.
        """
        for msg in messages:
            if msg.get('role') == 'user':
                content = msg.get('content', '').strip()
                if content:
                    # Clean and truncate
                    content = re.sub(r'\s+', ' ', content)
                    if len(content) > 50:
                        content = content[:47] + '...'
                    return content
        
        return fallback
    
    def search(self, query: str, limit: int = 10, exclude_chat_id: str = None) -> List[SearchResult]:
        """
        Search chat histories for a keyword.
        
        Parameters
        ----------
        query : str
            The search query (word or phrase).
        limit : int
            Maximum number of results to return.
        exclude_chat_id : str, optional
            Chat ID to exclude from search (e.g., current chat).
            
        Returns
        -------
        List[SearchResult]
            List of search results, sorted by relevance.
        """
        if not query:
            return []
        
        # Build word-boundary regex pattern
        pattern = re.compile(r'\b' + re.escape(query) + r'\b', re.IGNORECASE)
        results = []
        
        for chat_file in self.history_dir.glob("*.json"):
            chat_id = chat_file.stem
            
            # Skip excluded chat
            if exclude_chat_id and chat_id == exclude_chat_id:
                continue
            
            if len(results) >= limit:
                break
            
            try:
                with open(chat_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                messages = data.get('messages', [])
                matching_messages = []
                
                for msg in messages:
                    role = msg.get('role', '')
                    if role == 'system':
                        continue
                    
                    content = msg.get('content', '')
                    if pattern.search(content):
                        # Truncate long messages
                        display_content = content[:500]
                        if len(content) > 500:
                            display_content += '...'
                        matching_messages.append(f"[{role}]: {display_content}")
                
                if matching_messages:
                    title = self._generate_title(messages, chat_id)
                    results.append(SearchResult(
                        chat_id=chat_id,
                        chat_title=title,
                        matches=matching_messages[:3],  # Limit messages per chat
                        relevance_score=len(matching_messages),
                    ))
                    
            except (json.JSONDecodeError, IOError):
                continue
        
        # Sort by relevance
        results.sort(key=lambda r: r.relevance_score, reverse=True)
        return results[:limit]
    
    def get_by_date_range(self, start: datetime, end: datetime) -> List[ChatMetadata]:
        """
        Get chats within a date range.
        
        Parameters
        ----------
        start : datetime
            Start of date range (inclusive).
        end : datetime
            End of date range (inclusive).
            
        Returns
        -------
        List[ChatMetadata]
            List of chats within the date range.
        """
        all_chats = self.list_all()
        return [
            chat for chat in all_chats
            if start <= chat.timestamp <= end
        ]
