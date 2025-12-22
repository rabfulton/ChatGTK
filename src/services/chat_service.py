"""
Chat service for managing conversation lifecycle and message handling.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime

from repositories import (
    ChatHistoryRepository,
    SettingsRepository,
    APIKeysRepository,
)
from conversation import ConversationHistory, Message, create_system_message
from utils import generate_chat_name
from events import EventBus, EventType, Event


class ChatService:
    """
    Service for managing chat conversations.
    
    This service coordinates between repositories and AI providers to handle
    the full conversation lifecycle including creation, loading, saving,
    message preparation, and provider interaction.
    """
    
    def __init__(
        self,
        history_repo: ChatHistoryRepository,
        settings_repo: SettingsRepository,
        api_keys_repo: APIKeysRepository,
        event_bus: Optional[EventBus] = None,
        settings_manager=None,
    ):
        """
        Initialize the chat service.
        
        Parameters
        ----------
        history_repo : ChatHistoryRepository
            Repository for chat history persistence.
        settings_repo : SettingsRepository
            Repository for application settings.
        api_keys_repo : APIKeysRepository
            Repository for API keys.
        event_bus : Optional[EventBus]
            Event bus for publishing events.
        settings_manager : Optional[SettingsManager]
            Optional settings manager for centralized reads.
        """
        self._history_repo = history_repo
        self._settings_repo = settings_repo
        self._api_keys_repo = api_keys_repo
        self._event_bus = event_bus
        self._settings_manager = settings_manager
    
    def _emit(self, event_type: EventType, **data) -> None:
        """Emit an event if event bus is configured."""
        if self._event_bus:
            self._event_bus.publish(Event(type=event_type, data=data, source='chat_service'))
    
    def create_chat(self, system_message: Optional[str] = None) -> str:
        """
        Create a new chat conversation.
        
        Parameters
        ----------
        system_message : Optional[str]
            System message to initialize the conversation.
            If None, uses default from settings.
            
        Returns
        -------
        str
            The new chat ID.
        """
        if system_message is None:
            if self._settings_manager is not None:
                system_message = self._settings_manager.get(
                    'SYSTEM_MESSAGE',
                    'You are a helpful assistant.'
                )
            else:
                system_message = self._settings_repo.get(
                    'SYSTEM_MESSAGE',
                    'You are a helpful assistant.'
                )
        
        # Create conversation history with system message
        history = ConversationHistory(system_message=system_message)
        
        # Generate a temporary chat ID (will be replaced on first save)
        chat_id = f"new_chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        self._emit(EventType.CHAT_CREATED, chat_id=chat_id, system_message=system_message)
        
        return chat_id
    
    def load_chat(self, chat_id: str) -> Optional[ConversationHistory]:
        """
        Load a chat conversation by ID.
        
        Parameters
        ----------
        chat_id : str
            The chat identifier.
            
        Returns
        -------
        Optional[ConversationHistory]
            The conversation history if found, None otherwise.
        """
        history = self._history_repo.get(chat_id)
        if history:
            self._emit(EventType.CHAT_LOADED, chat_id=chat_id, message_count=len(history))
        return history
    
    def save_chat(self, chat_id: str, history: ConversationHistory) -> str:
        """
        Save a chat conversation.
        
        Parameters
        ----------
        chat_id : str
            The chat identifier. If it starts with "new_chat_", a proper
            ID will be generated based on the first user message.
        history : ConversationHistory
            The conversation history to save.
            
        Returns
        -------
        str
            The actual chat ID used for saving.
        """
        # Generate proper chat ID if this is a new chat
        if chat_id.startswith('new_chat_'):
            # Get first user message for naming
            first_user_msg = history.get_first_user_message()
            if first_user_msg:
                # Use the content of the first user message
                chat_id = generate_chat_name(first_user_msg.content)
            else:
                # Fallback to timestamp-based name
                from datetime import datetime
                chat_id = f"chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            if chat_id.endswith('.json'):
                chat_id = chat_id[:-5]
        
        self._history_repo.save(chat_id, history)
        self._emit(EventType.CHAT_SAVED, chat_id=chat_id, message_count=len(history))
        return chat_id
    
    def delete_chat(self, chat_id: str) -> bool:
        """
        Delete a chat conversation.
        
        Parameters
        ----------
        chat_id : str
            The chat identifier.
            
        Returns
        -------
        bool
            True if deleted successfully, False otherwise.
        """
        result = self._history_repo.delete(chat_id)
        if result:
            self._emit(EventType.CHAT_DELETED, chat_id=chat_id)
        return result
    
    def list_chats(self) -> List[Dict[str, Any]]:
        """
        List all available chats.
        
        Returns
        -------
        List[Dict[str, Any]]
            List of chat metadata dictionaries.
        """
        metadata_list = self._history_repo.list_all()
        return [meta.to_dict() for meta in metadata_list]
    
    def search_history(self, query: str, limit: int = 10, exclude_chat_id: Optional[str] = None, context_window: int = 200) -> List[Dict[str, Any]]:
        """
        Search chat histories for a keyword.
        
        Parameters
        ----------
        query : str
            The search query.
        limit : int
            Maximum number of results.
        exclude_chat_id : Optional[str]
            Chat ID to exclude from results (e.g., current chat).
        context_window : int
            Characters to show before/after match.
            
        Returns
        -------
        List[Dict[str, Any]]
            List of search result dictionaries.
        """
        results = self._history_repo.search(query, limit, exclude_chat_id, context_window)
        return [result.to_dict() for result in results]
    
    def prepare_messages_for_model(
        self,
        history: ConversationHistory,
        model: str,
        tool_guidance: Optional[str] = None,
        buffer_limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Prepare messages for sending to a model.
        
        This applies conversation buffer limits and adds tool guidance.
        
        Parameters
        ----------
        history : ConversationHistory
            The conversation history.
        model : str
            The model identifier.
        tool_guidance : Optional[str]
            Tool guidance to append to system message.
        buffer_limit : Optional[int]
            Maximum number of messages to include (None for no limit).
            
        Returns
        -------
        List[Dict[str, Any]]
            Prepared message list.
        """
        messages = history.to_list()
        
        # Apply conversation buffer limit
        if buffer_limit is not None and buffer_limit > 0:
            # Always keep system message (first message)
            system_msg = messages[0] if messages and messages[0].get('role') == 'system' else None
            other_messages = messages[1:] if system_msg else messages
            
            # Keep only the last N messages
            if len(other_messages) > buffer_limit:
                other_messages = other_messages[-buffer_limit:]
            
            messages = [system_msg] + other_messages if system_msg else other_messages
        
        # Add tool guidance to system message if provided
        if tool_guidance and messages and messages[0].get('role') == 'system':
            messages[0] = messages[0].copy()
            messages[0]['content'] = messages[0]['content'] + '\n\n' + tool_guidance
        
        return messages
    
