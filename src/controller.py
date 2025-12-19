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
from settings import SettingsManager
from events import EventBus, EventType, Event, get_event_bus
from utils import (
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
                 event_bus: Optional[EventBus] = None,
                 settings_manager: Optional[SettingsManager] = None):
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
        settings_manager : Optional[SettingsManager]
            Settings manager instance. If None, creates a new one.
        """
        # Initialize repositories
        self._settings_repo = settings_repo or SettingsRepository()
        self._api_keys_repo = api_keys_repo or APIKeysRepository()
        self._chat_history_repo = chat_history_repo or ChatHistoryRepository()
        self._model_cache_repo = model_cache_repo or ModelCacheRepository()
        
        # Initialize event bus
        self._event_bus = event_bus or get_event_bus()
        
        # Initialize settings manager
        self._settings_manager = settings_manager or SettingsManager(
            repository=self._settings_repo,
            event_bus=self._event_bus,
        )
        
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
        self._audio_service = AudioService(event_bus=self._event_bus)
        
        # Load settings and apply as attributes for backward compatibility
        self._settings: Dict[str, Any] = self._settings_manager.get_all()
        self._settings_manager.apply_to_object(self)
        
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
            image_tool_enabled=self._settings_manager.get('IMAGE_TOOL_ENABLED', True),
            music_tool_enabled=self._settings_manager.get('MUSIC_TOOL_ENABLED', False),
            read_aloud_tool_enabled=self._settings_manager.get('READ_ALOUD_TOOL_ENABLED', False),
            search_tool_enabled=self._settings_manager.get('SEARCH_TOOL_ENABLED', False),
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

    def init_system_prompts(self) -> None:
        """Public method to initialize system prompts from settings."""
        self._init_system_prompts_from_settings()

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
            conv_history = ConversationHistory.from_list(self.conversation_history, metadata=metadata)
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

    # -----------------------------------------------------------------------
    # High-level orchestration methods
    # -----------------------------------------------------------------------

    def get_provider_for_model(self, model: str) -> Optional[Any]:
        """
        Get or initialize the appropriate provider for a model.
        
        Parameters
        ----------
        model : str
            The model identifier.
            
        Returns
        -------
        Optional[Any]
            The provider instance, or None if unavailable.
        """
        provider_name = self.get_provider_name_for_model(model)
        
        # Check for custom provider
        if provider_name == "custom":
            provider = self.custom_providers.get(model)
            if provider:
                return provider
            # Initialize custom provider
            config = (self.custom_models or {}).get(model, {})
            if not config:
                return None
            from utils import resolve_api_key
            provider = get_ai_provider("custom")
            provider.initialize(
                api_key=resolve_api_key(config.get("api_key", "")).strip(),
                endpoint=config.get("endpoint"),
                model_id=model,
                api_type=config.get("api_type", "chat.completions"),
            )
            self.custom_providers[model] = provider
            return provider
        
        # Check cached provider
        if provider_name in self.providers:
            return self.providers[provider_name]
        
        # Get API key and initialize
        api_key = self._get_api_key_for_provider(provider_name)
        if not api_key:
            return None
        
        return self.initialize_provider(provider_name, api_key)

    def get_provider(self, provider_name: str) -> Optional[Any]:
        """
        Get or initialize a provider by name.
        
        Parameters
        ----------
        provider_name : str
            The provider name ('openai', 'gemini', 'grok', 'claude', 'perplexity').
            
        Returns
        -------
        Optional[Any]
            The provider instance, or None if unavailable.
        """
        if provider_name in self.providers:
            return self.providers[provider_name]
        
        api_key = self._get_api_key_for_provider(provider_name)
        if not api_key:
            return None
        
        return self.initialize_provider(provider_name, api_key)

    def _get_api_key_for_provider(self, provider_name: str) -> Optional[str]:
        """Get API key for a provider from env or saved keys."""
        env_map = {
            'openai': 'OPENAI_API_KEY',
            'gemini': 'GEMINI_API_KEY',
            'grok': 'GROK_API_KEY',
            'claude': 'CLAUDE_API_KEY',
            'perplexity': 'PERPLEXITY_API_KEY',
        }
        env_var = env_map.get(provider_name, f'{provider_name.upper()}_API_KEY')
        return os.environ.get(env_var, '').strip() or self.api_keys.get(provider_name, '').strip()

    def get_provider_name_for_model(self, model: str) -> str:
        """
        Determine which provider handles a given model.
        
        Uses model cards as the single source of truth, with fallback heuristics.
        
        Parameters
        ----------
        model : str
            The model identifier.
            
        Returns
        -------
        str
            The provider name ('openai', 'gemini', 'grok', 'claude', 'perplexity', 'custom').
        """
        from model_cards import get_card
        
        if not model:
            return 'openai'
        
        # Model card is the single source of truth
        card = get_card(model, self.custom_models)
        if card:
            return card.provider
        
        # Fallback: check model_provider_map (from API fetch)
        if model in self.model_provider_map:
            return self.model_provider_map[model]
        
        # Check custom models
        if model in (self.custom_models or {}):
            return "custom"
        
        # Fallback heuristics for unknown models
        model_lower = model.lower()
        if 'claude' in model_lower:
            return 'claude'
        if 'gemini' in model_lower:
            return 'gemini'
        if 'grok' in model_lower:
            return 'grok'
        if 'sonar' in model_lower:
            return 'perplexity'
        
        return 'openai'

    def prepare_message(
        self,
        content: str,
        images: Optional[List[Dict[str, Any]]] = None,
        files: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Prepare a user message for the conversation.
        
        Parameters
        ----------
        content : str
            The message content.
        images : Optional[List[Dict]]
            List of image attachments.
        files : Optional[List[Dict]]
            List of file attachments.
            
        Returns
        -------
        Dict[str, Any]
            The prepared message dictionary.
        """
        return create_user_message(content, images=images, files=files)

    def add_user_message(
        self,
        content: str,
        images: Optional[List[Dict[str, Any]]] = None,
        files: Optional[List[Dict[str, Any]]] = None,
    ) -> int:
        """
        Add a user message to the conversation history.
        
        Parameters
        ----------
        content : str
            The message content.
        images : Optional[List[Dict]]
            List of image attachments.
        files : Optional[List[Dict]]
            List of file attachments.
            
        Returns
        -------
        int
            The index of the added message.
        """
        msg = self.prepare_message(content, images, files)
        msg_index = len(self.conversation_history)
        self.conversation_history.append(msg)
        
        self._event_bus.publish(Event(
            type=EventType.MESSAGE_SENT,
            data={'content': content, 'index': msg_index, 'role': 'user'},
            source='controller'
        ))
        
        return msg_index

    def add_assistant_message(self, content: str) -> int:
        """
        Add an assistant message to the conversation history.
        
        Parameters
        ----------
        content : str
            The message content.
            
        Returns
        -------
        int
            The index of the added message.
        """
        msg = create_assistant_message(content)
        msg_index = len(self.conversation_history)
        self.conversation_history.append(msg)
        
        self._event_bus.publish(Event(
            type=EventType.MESSAGE_RECEIVED,
            data={'content': content, 'index': msg_index, 'role': 'assistant'},
            source='controller'
        ))
        
        return msg_index

    def is_quick_image_request(self, content: str) -> bool:
        """Check if content is a quick image generation request (img: prefix)."""
        return content.lower().startswith("img:")

    def get_image_prompt(self, content: str) -> str:
        """Extract image prompt from img: prefixed content."""
        return content[4:].strip()

    def get_preferred_image_model(self) -> str:
        """Get the user's preferred image generation model."""
        return self._settings_manager.get('IMAGE_MODEL', 'dall-e-3') or 'dall-e-3'

    def get_temperature_for_model(self, model: str) -> Optional[float]:
        """
        Get the appropriate temperature setting for a model.
        
        Some models (like o1, o3) don't support temperature.
        """
        from model_cards import get_card
        
        card = get_card(model, self.custom_models)
        if card and card.quirks.get('no_temperature'):
            return None
        
        return self._settings_manager.get('TEMPERATURE', 0.7)

    def ensure_chat_id(self) -> str:
        """
        Ensure a chat ID exists, creating one if necessary.
        
        Returns
        -------
        str
            The current or newly created chat ID.
        """
        if self.current_chat_id is None and len(self.conversation_history) > 1:
            # Generate from first user message
            from utils import generate_chat_name
            first_user = next(
                (m for m in self.conversation_history if m.get('role') == 'user'),
                None
            )
            if first_user:
                self.current_chat_id = generate_chat_name(first_user.get('content', ''))
            else:
                from datetime import datetime
                self.current_chat_id = f"chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        return self.current_chat_id

    # -----------------------------------------------------------------------
    # Message sending (main API call flow)
    # -----------------------------------------------------------------------

    def send_message(
        self,
        model: str,
        tool_handlers: Optional[Dict[str, Callable]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        """
        Send the last user message to the AI and emit response via events.
        
        This is the main entry point for AI requests. It handles:
        - Provider selection and initialization
        - Image model routing
        - Message preparation
        - Tool handler wiring
        - Response processing
        
        Results are emitted via MESSAGE_RECEIVED or ERROR_OCCURRED events.
        
        Parameters
        ----------
        model : str
            The model to use for generation.
        tool_handlers : Optional[Dict[str, Callable]]
            Tool handler functions (image_tool_handler, music_tool_handler, etc.)
        cancel_check : Optional[Callable[[], bool]]
            Function that returns True if request should be cancelled.
        """
        from model_cards import get_card
        from markup_utils import format_response
        
        def is_cancelled():
            return cancel_check() if cancel_check else False
        
        try:
            # Emit thinking started
            self._event_bus.publish(Event(
                type=EventType.THINKING_STARTED,
                data={'model': model},
                source='controller'
            ))
            
            if is_cancelled():
                return
            
            # Ensure valid model
            if not model:
                model = "gpt-3.5-turbo"
            
            provider_name = self.get_provider_name_for_model(model)
            
            if is_cancelled():
                return
            
            # Get or initialize provider
            provider = self._get_or_init_provider(model, provider_name)
            
            last_msg = self.conversation_history[-1]
            prompt = last_msg.get("content", "")
            has_attached_images = bool(last_msg.get("images"))
            
            # Check for image model
            card = get_card(model, self.custom_models)
            is_image_model = card and card.capabilities.image_gen and not card.capabilities.text
            
            if is_image_model:
                # Route to image generation
                answer = self._image_service.generate_image(
                    prompt=prompt,
                    model=model,
                    provider=provider,
                    provider_name=provider_name,
                    chat_id=self.current_chat_id or "temp",
                    edit_image=last_msg.get("images", [None])[0] if has_attached_images else None,
                )
                assistant_provider_meta = None
            else:
                # Check for realtime models
                if card and card.api_family == "realtime":
                    return
                
                # Prepare messages
                messages_to_send = self.messages_for_model(model)
                if provider_name == 'perplexity':
                    messages_to_send = self._clean_messages_for_perplexity(messages_to_send)
                
                # Build kwargs
                response_meta = {}
                kwargs = {
                    "messages": messages_to_send,
                    "model": model,
                    "temperature": self.get_temperature_for_model(model),
                    "max_tokens": self._settings_manager.get('MAX_TOKENS', 0) or None,
                    "chat_id": self.current_chat_id,
                }
                
                # Add tool handlers and web search for non-perplexity
                if provider_name != 'perplexity':
                    kwargs["web_search_enabled"] = self._settings_manager.get('WEB_SEARCH_ENABLED', False)
                    if tool_handlers:
                        kwargs.update(tool_handlers)
                
                # Add response_meta for providers that use it
                if provider_name in ('gemini', 'perplexity', 'claude'):
                    kwargs["response_meta"] = response_meta
                
                if is_cancelled():
                    return
                
                # Call provider
                answer = provider.generate_chat_completion(**kwargs)
                assistant_provider_meta = response_meta if response_meta else None
                
                # Append Perplexity sources
                if provider_name == 'perplexity':
                    answer = self._append_perplexity_sources(answer, response_meta)
            
            if is_cancelled():
                return
            
            # Normalize image tags
            answer = self._normalize_image_tags(answer)
            
            # Add to conversation history
            assistant_message = create_assistant_message(answer, provider_meta=assistant_provider_meta)
            message_index = len(self.conversation_history)
            self.conversation_history.append(assistant_message)
            
            # Store model in system message (first message)
            if self.conversation_history:
                self.conversation_history[0]['model'] = model
            
            # Save chat
            self.save_current_chat()
            
            # Emit response
            self._event_bus.publish(Event(
                type=EventType.MESSAGE_RECEIVED,
                data={
                    'content': answer,
                    'formatted_content': format_response(answer),
                    'index': message_index,
                    'model': model,
                    'provider_meta': assistant_provider_meta,
                },
                source='controller'
            ))
            
        except Exception as error:
            if not is_cancelled():
                error_message = f"** Error: {str(error)} **"
                message_index = len(self.conversation_history)
                self.conversation_history.append(create_assistant_message(error_message))
                
                self._event_bus.publish(Event(
                    type=EventType.ERROR_OCCURRED,
                    data={'error': str(error), 'context': 'send_message', 'index': message_index},
                    source='controller'
                ))
        finally:
            self._event_bus.publish(Event(
                type=EventType.THINKING_STOPPED,
                data={},
                source='controller'
            ))

    def _get_or_init_provider(self, model: str, provider_name: str) -> Any:
        """Get or initialize a provider for the given model."""
        if provider_name == "custom":
            provider = self.custom_providers.get(model)
            if not provider:
                config = (self.custom_models or {}).get(model, {})
                if not config:
                    raise ValueError(f"Custom model '{model}' is not configured")
                provider = get_ai_provider("custom")
                from utils import resolve_api_key
                provider.initialize(
                    api_key=resolve_api_key(config.get("api_key", "")).strip(),
                    endpoint=config.get("endpoint"),
                    model_id=config.get("model_name") or model,
                    api_type=config.get("api_type") or "chat.completions",
                    voice=config.get("voice"),
                )
                self.custom_providers[model] = provider
            return provider
        else:
            provider = self.get_provider(provider_name)
            if not provider:
                raise ValueError(f"{provider_name.title()} provider is not initialized")
            return provider

    def _clean_messages_for_perplexity(self, messages: List[Dict]) -> List[Dict]:
        """Clean messages for Perplexity API (strict alternation required)."""
        if not messages:
            return messages
        
        cleaned = []
        system_messages = []
        other_messages = []
        
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_messages.append({"role": "system", "content": content})
            elif content:
                other_messages.append({"role": role, "content": content})
        
        cleaned.extend(system_messages)
        
        # Ensure strict alternation
        alternating = []
        expected_role = "user"
        
        for msg in other_messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == expected_role:
                alternating.append({"role": role, "content": content})
                expected_role = "assistant" if role == "user" else "user"
            elif role == "user" and expected_role == "user":
                if alternating and alternating[-1]["role"] == "user":
                    alternating[-1]["content"] += "\n\n" + content
                else:
                    alternating.append({"role": role, "content": content})
                    expected_role = "assistant"
            elif role == "assistant" and expected_role == "assistant":
                if alternating and alternating[-1]["role"] == "assistant":
                    alternating[-1]["content"] += "\n\n" + content
                else:
                    alternating.append({"role": role, "content": content})
                    expected_role = "user"
        
        cleaned.extend(alternating)
        return cleaned

    def _append_perplexity_sources(self, answer: str, response_meta: dict) -> str:
        """Append Perplexity search results as sources section."""
        perplexity_meta = (response_meta or {}).get("perplexity", {})
        search_results = perplexity_meta.get("search_results") if isinstance(perplexity_meta, dict) else None
        if not search_results:
            return answer
        
        lines = []
        for idx, res in enumerate(search_results, start=1):
            title = res.get("title") or "Source"
            url = res.get("url") or ""
            date = res.get("date") or ""
            line = f"{idx}. {title}"
            if date:
                line += f" ({date})"
            if url:
                line += f" — {url}"
            lines.append(line)
        
        if lines:
            return (answer.rstrip() + "\n\nSources:\n" + "\n".join(lines)).rstrip()
        return answer

    def _normalize_image_tags(self, text: str) -> str:
        """Normalize image references to consistent format."""
        if not text:
            return text
        import re
        
        seen_src = set()
        
        def md_to_html(match):
            path = match.group(2)
            if path.startswith('sandbox:'):
                path = path[8:]
            if path in seen_src:
                return ""
            seen_src.add(path)
            return f'<img src="{path}"/>'
        
        text = re.sub(r'!\[([^\]]*)\]\((?:sandbox:)?([^)]+)\)', md_to_html, text)
        
        pattern = re.compile(r'<img\s+src="([^"]+)"[^>]*>', re.IGNORECASE)
        result_parts = []
        last_end = 0
        
        for match in pattern.finditer(text):
            result_parts.append(text[last_end:match.start()])
            src = match.group(1)
            if src in seen_src:
                replacement = ""
            else:
                seen_src.add(src)
                replacement = f'<img src="{src}"/>'
            result_parts.append(replacement)
            last_end = match.end()
        
        result_parts.append(text[last_end:])
        return "".join(result_parts)

    @property
    def event_bus(self) -> EventBus:
        """Get the event bus instance."""
        return self._event_bus

    @property
    def settings_manager(self) -> SettingsManager:
        """Get the settings manager instance."""
        return self._settings_manager

    # -----------------------------------------------------------------------
    # Settings management
    # -----------------------------------------------------------------------

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a setting value via settings manager."""
        return self._settings_manager.get(key, default)
    
    def set_setting(self, key: str, value: Any) -> None:
        """Set a setting value via settings manager."""
        self._settings_manager.set(key, value)
        # Also update local attribute for backward compatibility
        setattr(self, key.lower(), value)

    def _save_settings(self) -> None:
        """Persist current settings to disk."""
        # Update settings manager from object attributes
        self._settings_manager.update_from_object(self, save=True)

    def update_tool_manager(self) -> None:
        """Update the ToolManager with current settings."""
        self.tool_manager = ToolManager(
            image_tool_enabled=self._settings_manager.get('IMAGE_TOOL_ENABLED', True),
            music_tool_enabled=self._settings_manager.get('MUSIC_TOOL_ENABLED', False),
            read_aloud_tool_enabled=self._settings_manager.get('READ_ALOUD_TOOL_ENABLED', False),
            search_tool_enabled=self._settings_manager.get('SEARCH_TOOL_ENABLED', False),
        )
        # Update tool service with new tool manager and event bus
        self._tool_service = ToolService(
            tool_manager=self.tool_manager,
            event_bus=self._event_bus,
        )
