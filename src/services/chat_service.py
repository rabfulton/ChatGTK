"""
Chat service for managing conversation lifecycle and message handling.
"""

import os
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime

from repositories import (
    ChatHistoryRepository,
    SettingsRepository,
    APIKeysRepository,
)
from conversation import ConversationHistory, Message, create_system_message
from ai_providers import get_ai_provider
from utils import generate_chat_name


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
        """
        self._history_repo = history_repo
        self._settings_repo = settings_repo
        self._api_keys_repo = api_keys_repo
        
        # Cache providers to avoid re-initialization
        self._providers: Dict[str, Any] = {}
        self._model_provider_map: Dict[str, str] = {}
    
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
            system_message = self._settings_repo.get('SYSTEM_MESSAGE', 'You are a helpful assistant.')
        
        # Create conversation history with system message
        history = ConversationHistory(system_message=system_message)
        
        # Generate a temporary chat ID (will be replaced on first save)
        chat_id = f"new_chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
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
        return self._history_repo.get(chat_id)
    
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
        return self._history_repo.delete(chat_id)
    
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
    
    def search_history(self, query: str, limit: int = 10, exclude_chat_id: Optional[str] = None) -> List[Dict[str, Any]]:
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
            
        Returns
        -------
        List[Dict[str, Any]]
            List of search result dictionaries.
        """
        results = self._history_repo.search(query, limit, exclude_chat_id)
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
    
    def get_provider(self, provider_name: str) -> Optional[Any]:
        """
        Get or initialize an AI provider.
        
        Parameters
        ----------
        provider_name : str
            The provider name (e.g., 'openai', 'gemini').
            
        Returns
        -------
        Optional[Any]
            The provider instance if available, None otherwise.
        """
        # Check if provider is already initialized
        if provider_name in self._providers:
            return self._providers[provider_name]
        
        # Get API key for provider
        api_key = self._api_keys_repo.get_key(provider_name)
        if not api_key:
            # Check environment variables
            env_key = os.environ.get(f'{provider_name.upper()}_API_KEY', '').strip()
            if not env_key:
                return None
            api_key = env_key
        
        # Initialize provider
        try:
            provider = get_ai_provider(provider_name)
            provider.initialize(api_key)
            self._providers[provider_name] = provider
            return provider
        except Exception as e:
            print(f"Error initializing provider {provider_name}: {e}")
            return None
    
    def send_message(
        self,
        chat_id: str,
        content: str,
        model: str,
        provider_name: str,
        images: Optional[List[Dict]] = None,
        files: Optional[List[Dict]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        web_search_enabled: bool = False,
        tool_handlers: Optional[Dict[str, Callable]] = None,
        stream_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """
        Send a message and get a response.
        
        Parameters
        ----------
        chat_id : str
            The chat identifier.
        content : str
            The message content.
        model : str
            The model to use.
        provider_name : str
            The provider name.
        images : Optional[List[Dict]]
            List of image attachments.
        files : Optional[List[Dict]]
            List of file attachments.
        temperature : Optional[float]
            Temperature parameter for generation.
        max_tokens : Optional[int]
            Maximum tokens for generation.
        web_search_enabled : bool
            Whether web search is enabled.
        tool_handlers : Optional[Dict[str, Callable]]
            Dictionary of tool handler functions.
        stream_callback : Optional[Callable[[str], None]]
            Callback for streaming responses.
            
        Returns
        -------
        Dict[str, Any]
            Dictionary containing:
            - 'response': The AI response text
            - 'chat_id': The actual chat ID used
            - 'success': Whether the operation succeeded
            - 'error': Error message if failed
        """
        try:
            # Load or create conversation history
            history = self.load_chat(chat_id)
            if history is None:
                system_message = self._settings_repo.get('SYSTEM_MESSAGE', 'You are a helpful assistant.')
                history = ConversationHistory(default_system=system_message)
            
            # Add user message
            history.add_user_message(content, images=images, files=files)
            
            # Get provider
            provider = self.get_provider(provider_name)
            if provider is None:
                return {
                    'success': False,
                    'error': f'Provider {provider_name} not available',
                    'chat_id': chat_id,
                }
            
            # Prepare messages
            buffer_limit = self._settings_repo.get('CONVERSATION_BUFFER_LIMIT')
            messages = self.prepare_messages_for_model(history, model, buffer_limit=buffer_limit)
            
            # Generate response
            response = provider.generate_chat_completion(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                chat_id=chat_id,
                web_search_enabled=web_search_enabled,
                **(tool_handlers or {}),
            )
            
            # Add assistant response to history
            history.add_assistant_message(response)
            
            # Save chat
            actual_chat_id = self.save_chat(chat_id, history)
            
            return {
                'success': True,
                'response': response,
                'chat_id': actual_chat_id,
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'chat_id': chat_id,
            }
    
    def get_conversation_buffer_limit(self) -> Optional[int]:
        """
        Get the conversation buffer limit from settings.
        
        Returns
        -------
        Optional[int]
            The buffer limit, or None if not set.
        """
        limit = self._settings_repo.get('CONVERSATION_BUFFER_LIMIT')
        if limit is None or limit == 0:
            return None
        return int(limit)
