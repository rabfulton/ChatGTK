"""
controller.py – Application state and business logic, decoupled from GTK UI.

This module provides the ChatController class that manages:
- Conversation history and chat lifecycle
- AI provider initialization and model management
- Settings and API key management
- Tool manager configuration

The controller is designed to be toolkit-agnostic to facilitate future porting.
"""

from __future__ import annotations

import os
import json
from typing import Any, Dict, List, Optional, Set, Callable

from repositories import (
    SettingsRepository,
    APIKeysRepository,
    ChatHistoryRepository,
    ModelCacheRepository,
)
from services import (
    ChatService,
    ImageGenerationService,
    AudioService,
    ToolService,
)
from events import EventBus, EventType, Event, get_event_bus
from utils import (
    load_settings,
    save_settings,
    apply_settings,
    get_object_settings,
    convert_settings_for_save,
    load_api_keys,
    load_custom_models,
    save_custom_models,
)
from ai_providers import get_ai_provider
from conversation import (
    create_system_message,
    create_user_message,
    create_assistant_message,
    ConversationHistory,
)
from tools import (
    ToolManager,
    is_chat_completion_model,
    append_tool_guidance,
)


class ChatController:
    """
    Manages application state and business logic for the chat client.
    
    This class is designed to be independent of any specific GUI toolkit,
    making it suitable for use with GTK, Qt, or other frameworks.
    """

    def __init__(self, 
                 settings_repo: Optional[SettingsRepository] = None,
                 api_keys_repo: Optional[APIKeysRepository] = None,
                 chat_history_repo: Optional[ChatHistoryRepository] = None,
                 model_cache_repo: Optional[ModelCacheRepository] = None,
                 event_bus: Optional[EventBus] = None):
        """Initialize the controller with settings and state.
        
        Parameters
        ----------
        settings_repo : Optional[SettingsRepository]
            Settings repository instance. If None, creates a new one.
        api_keys_repo : Optional[APIKeysRepository]
            API keys repository instance. If None, creates a new one.
        chat_history_repo : Optional[ChatHistoryRepository]
            Chat history repository instance. If None, creates a new one.
        model_cache_repo : Optional[ModelCacheRepository]
            Model cache repository instance. If None, creates a new one.
        event_bus : Optional[EventBus]
            Event bus for publishing/subscribing to events. If None, uses global.
        """
        # Initialize repositories
        self._settings_repo = settings_repo or SettingsRepository()
        self._api_keys_repo = api_keys_repo or APIKeysRepository()
        self._chat_history_repo = chat_history_repo or ChatHistoryRepository()
        self._model_cache_repo = model_cache_repo or ModelCacheRepository()
        
        # Initialize event bus
        self._event_bus = event_bus or get_event_bus()
        
        # Initialize services with event bus
        self._chat_service = ChatService(
            history_repo=self._chat_history_repo,
            settings_repo=self._settings_repo,
            api_keys_repo=self._api_keys_repo,
            event_bus=self._event_bus,
        )
        self._image_service = ImageGenerationService(
            chat_history_repo=self._chat_history_repo,
            event_bus=self._event_bus,
        )
        self._audio_service = AudioService(
            chat_history_repo=self._chat_history_repo,
            settings_repo=self._settings_repo,
            event_bus=self._event_bus,
        )
        
        # Load settings from repository
        self._settings: Dict[str, Any] = self._settings_repo.get_all()
        
        # Apply settings as attributes for convenience
        for key, value in self._settings.items():
            setattr(self, key.lower(), value)
        
        # Initialize system prompts from settings
        self._init_system_prompts_from_settings()
        
        # Chat state
        self.current_chat_id: Optional[str] = None
        self.conversation_history: List[Dict[str, Any]] = [
            create_system_message(self.system_message)
        ]
        
        # Provider management
        self.providers: Dict[str, Any] = {}
        self.model_provider_map: Dict[str, str] = {}
        self.api_keys: Dict[str, str] = self._api_keys_repo.get_all_raw()
        self.custom_models: Dict[str, Dict[str, Any]] = load_custom_models()
        self.custom_providers: Dict[str, Any] = {}
        
        # Tool manager
        self.tool_manager = ToolManager(
            image_tool_enabled=bool(getattr(self, "image_tool_enabled", True)),
            music_tool_enabled=bool(getattr(self, "music_tool_enabled", False)),
            read_aloud_tool_enabled=bool(getattr(self, "read_aloud_tool_enabled", False)),
            search_tool_enabled=bool(getattr(self, "search_tool_enabled", False)),
        )
        
        # Initialize tool service with event bus
        self._tool_service = ToolService(
            tool_manager=self.tool_manager,
            event_bus=self._event_bus,
        )

    # -----------------------------------------------------------------------
    # System prompts management
    # -----------------------------------------------------------------------

    def _init_system_prompts_from_settings(self) -> None:
        """
        Initialize system prompts from settings.
        
        Parses SYSTEM_PROMPTS_JSON and sets up self.system_prompts (list of dicts)
        and self.active_system_prompt_id. Also updates self.system_message to
        the active prompt's content for backward compatibility.
        """
        prompts = []
        raw = getattr(self, "system_prompts_json", "") or ""
        if raw.strip():
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    for p in parsed:
                        if isinstance(p, dict) and "id" in p and "name" in p and "content" in p:
                            prompts.append(p)
            except json.JSONDecodeError:
                pass
        
        # Fallback: synthesize a single prompt from system_message
        if not prompts:
            prompts = [{
                "id": "default",
                "name": "Default",
                "content": getattr(self, "system_message", "You are a helpful assistant.")
            }]
        
        self.system_prompts: List[Dict[str, Any]] = prompts
        
        # Determine active prompt ID
        active_id = getattr(self, "active_system_prompt_id", "") or ""
        valid_ids = {p["id"] for p in self.system_prompts}
        if active_id not in valid_ids:
            active_id = self.system_prompts[0]["id"] if self.system_prompts else ""
        self.active_system_prompt_id = active_id
        
        # Update system_message to the active prompt's content
        active_prompt = self.get_system_prompt_by_id(active_id)
        if active_prompt:
            self.system_message = active_prompt["content"]

    def get_system_prompt_by_id(self, prompt_id: str) -> Optional[Dict[str, Any]]:
        """Return the system prompt dict with the given ID, or None."""
        for p in getattr(self, "system_prompts", []):
            if p["id"] == prompt_id:
                return p
        return None

    def set_active_system_prompt(self, prompt_id: str) -> bool:
        """
        Set the active system prompt by ID.
        
        Returns True if the prompt was found and set, False otherwise.
        """
        prompt = self.get_system_prompt_by_id(prompt_id)
        if not prompt:
            return False
        
        self.active_system_prompt_id = prompt_id
        self.system_message = prompt["content"]
        
        # Update the system message in the current conversation history
        if self.conversation_history and self.conversation_history[0].get("role") == "system":
            self.conversation_history[0]["content"] = prompt["content"]
        
        self._save_settings()
        return True

    # -----------------------------------------------------------------------
    # Provider management
    # -----------------------------------------------------------------------

    def initialize_provider(self, provider_name: str, api_key: str) -> Any:
        """
        Initialize and cache a provider when the key changes.
        
        Returns the provider instance, or None if the key was cleared.
        """
        api_key = (api_key or "").strip()
        self.api_keys[provider_name] = api_key

        # If the key was cleared, drop the provider.
        if not api_key:
            self.providers.pop(provider_name, None)
            return None

        # Reuse an existing provider instance when available so caches survive.
        provider = self.providers.get(provider_name)
        if provider is None:
            provider = get_ai_provider(provider_name)

        # Let the provider decide how to handle key changes (e.g., clear caches).
        provider.initialize(api_key)
        self.providers[provider_name] = provider
        return provider

    def initialize_providers_from_env(self) -> None:
        """
        Initialize providers from environment variables and saved keys.
        
        Environment variables take precedence over saved keys.
        """
        env_openai_key = os.environ.get('OPENAI_API_KEY', '').strip()
        env_gemini_key = os.environ.get('GEMINI_API_KEY', '').strip()
        env_grok_key = os.environ.get('GROK_API_KEY', '').strip()
        env_claude_key = (
            os.environ.get('CLAUDE_API_KEY', '').strip()
            or os.environ.get('ANTHROPIC_API_KEY', '').strip()
        )
        env_perplexity_key = os.environ.get('PERPLEXITY_API_KEY', '').strip()

        # Choose the effective key for each provider
        openai_key = env_openai_key or self.api_keys.get('openai', '').strip()
        gemini_key = env_gemini_key or self.api_keys.get('gemini', '').strip()
        grok_key = env_grok_key or self.api_keys.get('grok', '').strip()
        claude_key = env_claude_key or self.api_keys.get('claude', '').strip()
        perplexity_key = env_perplexity_key or self.api_keys.get('perplexity', '').strip()

        if openai_key:
            self.api_keys['openai'] = openai_key
            self.initialize_provider('openai', openai_key)
        if gemini_key:
            self.api_keys['gemini'] = gemini_key
            self.initialize_provider('gemini', gemini_key)
        if grok_key:
            self.api_keys['grok'] = grok_key
            self.initialize_provider('grok', grok_key)
        if claude_key:
            self.api_keys['claude'] = claude_key
            os.environ['CLAUDE_API_KEY'] = claude_key
            os.environ['ANTHROPIC_API_KEY'] = claude_key
            self.initialize_provider('claude', claude_key)
        if perplexity_key:
            self.api_keys['perplexity'] = perplexity_key
            self.initialize_provider('perplexity', perplexity_key)

    def get_default_models_for_provider(self, provider_name: str) -> List[str]:
        """Return default models for a provider when the API is unavailable."""
        if provider_name == 'gemini':
            return ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-3-pro-preview"]
        if provider_name == 'grok':
            return ["grok-2", "grok-2-mini", "grok-2-image-1212"]
        if provider_name == 'claude':
            return ["claude-sonnet-4-5", "claude-3-5-sonnet-latest"]
        if provider_name == 'perplexity':
            return ["sonar", "sonar-pro", "sonar-reasoning"]
        return ["gpt-3.5-turbo", "gpt-4", "gpt-4o-mini"]

    # -----------------------------------------------------------------------
    # Chat lifecycle
    # -----------------------------------------------------------------------

    def new_chat(self) -> None:
        """Reset the conversation for a new chat."""
        self.current_chat_id = None
        self.conversation_history = [create_system_message(self.system_message)]

    def load_chat(self, chat_id: str) -> bool:
        """
        Load a chat from disk by its ID (filename without .json).
        
        Returns True if successful, False otherwise.
        """
        try:
            # Use chat service to load chat
            conv_history = self._chat_service.load_chat(chat_id)
            if conv_history:
                self.conversation_history = conv_history.to_list()
                self.current_chat_id = chat_id
                return True
        except Exception as e:
            print(f"Error loading chat {chat_id}: {e}")
        return False

    def save_current_chat(self, metadata: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """
        Save the current conversation history.
        
        If this is a new chat, generates a name based on the first user message.
        Returns the chat_id (filename) or None on error.
        """
        if not self.conversation_history:
            return None
        
        try:
            # Use existing ID or generate new one
            chat_id = self.current_chat_id
            if not chat_id:
                # Generate a temporary ID that will be replaced by service
                from datetime import datetime
                chat_id = f"new_chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Convert to ConversationHistory and save via service
            conv_history = ConversationHistory.from_list(self.conversation_history)
            actual_chat_id = self._chat_service.save_chat(chat_id, conv_history)
            self.current_chat_id = actual_chat_id
            return actual_chat_id
        except Exception as e:
            print(f"Error saving chat: {e}")
            import traceback
            traceback.print_exc()
            return None

    def list_chats(self) -> List[Dict[str, Any]]:
        """List all available chats via service."""
        return self._chat_service.list_chats()

    def delete_chat(self, chat_id: str) -> bool:
        """Delete a chat via service."""
        return self._chat_service.delete_chat(chat_id)

    def search_history(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search chat histories via service."""
        return self._chat_service.search_history(query, limit, exclude_chat_id=self.current_chat_id)

    # -----------------------------------------------------------------------
    # Message preparation
    # -----------------------------------------------------------------------

    def get_conversation_buffer_limit(self) -> Optional[int]:
        """
        Return the configured conversation buffer length as an integer.
        
        Returns:
            None: send the full conversation history (ALL).
            0: send only the latest non-system message.
            N>0: send the last N non-system messages.
        """
        raw = getattr(self, "conversation_buffer_length", None)
        if raw is None:
            return None

        if isinstance(raw, (int, float)):
            value = int(raw)
            return max(value, 0)

        text = str(raw).strip()
        if not text or text.upper() == "ALL":
            return None

        try:
            value = int(text)
            return max(value, 0)
        except ValueError:
            return None

    def apply_conversation_buffer_limit(self, history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Apply the configured conversation buffer length to the given history.
        
        The system message (first entry) is always preserved when present.
        """
        if not history:
            return history

        limit = self.get_conversation_buffer_limit()
        if limit is None or len(history) <= 1:
            return history

        first = history[0]
        non_system = history[1:]
        if not non_system:
            return history

        if limit == 0:
            trimmed = [non_system[-1]]
        else:
            trimmed = non_system[-limit:]

        return [first] + trimmed

    def messages_for_model(self, model_name: str) -> List[Dict[str, Any]]:
        """
        Return the conversation history with tool guidance appended for chat models.
        """
        if not self.conversation_history:
            return []

        # For non-chat-completion models, skip extra system guidance
        if not is_chat_completion_model(model_name, self.custom_models):
            return self.apply_conversation_buffer_limit(self.conversation_history)

        first_message = self.conversation_history[0]
        if first_message.get("role") != "system":
            return self.apply_conversation_buffer_limit(self.conversation_history)

        current_prompt = first_message.get("content", "") or ""

        # Get enabled tools for this model and append guidance
        try:
            enabled_tools = self.tool_manager.get_enabled_tools_for_model(
                model_name, self.model_provider_map, self.custom_models
            )
            new_prompt = append_tool_guidance(current_prompt, enabled_tools, include_math=True)
        except Exception as e:
            print(f"Error while appending tool guidance: {e}")
            new_prompt = current_prompt

        limited_history = self.apply_conversation_buffer_limit(self.conversation_history)

        if new_prompt == current_prompt:
            return limited_history

        messages = [msg.copy() for msg in limited_history]
        messages[0]["content"] = new_prompt
        return messages

    # -----------------------------------------------------------------------
    # Service accessors
    # -----------------------------------------------------------------------

    @property
    def chat_service(self) -> ChatService:
        """Get the chat service instance."""
        return self._chat_service
    
    @property
    def image_service(self) -> ImageGenerationService:
        """Get the image generation service instance."""
        return self._image_service
    
    @property
    def audio_service(self) -> AudioService:
        """Get the audio service instance."""
        return self._audio_service
    
    @property
    def tool_service(self) -> ToolService:
        """Get the tool service instance."""
        return self._tool_service

    @property
    def event_bus(self) -> EventBus:
        """Get the event bus instance."""
        return self._event_bus

    # -----------------------------------------------------------------------
    # Settings management
    # -----------------------------------------------------------------------

    def _save_settings(self) -> None:
        """Persist current settings to disk."""
        # Load existing to preserve dialog-managed settings
        existing = load_settings()
        for key in self._settings.keys():
            attr = key.lower()
            if hasattr(self, attr):
                existing[key] = getattr(self, attr)
        save_settings(convert_settings_for_save(existing))

    def update_tool_manager(self) -> None:
        """Update the ToolManager with current settings."""
        self.tool_manager = ToolManager(
            image_tool_enabled=bool(getattr(self, "image_tool_enabled", True)),
            music_tool_enabled=bool(getattr(self, "music_tool_enabled", False)),
            read_aloud_tool_enabled=bool(getattr(self, "read_aloud_tool_enabled", False)),
            search_tool_enabled=bool(getattr(self, "search_tool_enabled", False)),
        )
        # Update tool service with new tool manager and event bus
        self._tool_service = ToolService(
            tool_manager=self.tool_manager,
            event_bus=self._event_bus,
        )
