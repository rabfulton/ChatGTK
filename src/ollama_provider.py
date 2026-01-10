"""
Ollama Provider for ChatGTK.

This provider wraps the OllamaBackend to integrate with the existing
AIProvider pattern used throughout the application.
"""

import os
from typing import Optional, List, Callable, Any

from services.local_models import OllamaBackend, LocalModelEntry


class OllamaProvider:
    """
    Provider for Ollama local LLM models.
    
    Unlike cloud providers, this doesn't require an API key.
    Instead, it connects to a local Ollama server.
    """
    
    def __init__(self):
        self.backend: Optional[OllamaBackend] = None
        self.base_url: str = "http://localhost:11434"
        self._models_cache: List[LocalModelEntry] = []
        self._debug = os.environ.get("DEBUG_CHATGTK", "").lower() in ("1", "true", "yes")
    
    def _log(self, msg: str) -> None:
        """Log debug message if debugging is enabled."""
        if self._debug:
            print(f"[OllamaProvider] {msg}")
    
    def initialize(self, base_url: str = "http://localhost:11434"):
        """
        Initialize the Ollama provider.
        
        Parameters
        ----------
        base_url : str
            The base URL of the Ollama server.
        """
        self.base_url = base_url
        self.backend = OllamaBackend(base_url)
        self._log(f"Initialized with base_url={base_url}")
    
    def get_available_models(self, refresh: bool = False) -> List[str]:
        """
        Get list of available Ollama models.
        
        Returns model IDs in the format "ollama:<model_name>".
        
        Parameters
        ----------
        refresh : bool
            If True, refresh the cache by querying the server.
            
        Returns
        -------
        List[str]
            List of model IDs.
        """
        if not self.backend:
            self.initialize()
        
        if refresh or not self._models_cache:
            self._models_cache = self.backend.list_models()
        
        return [entry.id for entry in self._models_cache]
    
    def get_model_entries(self, refresh: bool = False) -> List[LocalModelEntry]:
        """
        Get full model entries with metadata.
        
        Parameters
        ----------
        refresh : bool
            If True, refresh the cache.
            
        Returns
        -------
        List[LocalModelEntry]
            List of model entries.
        """
        if not self.backend:
            self.initialize()
        
        if refresh or not self._models_cache:
            self._models_cache = self.backend.list_models()
        
        return self._models_cache
    
    def get_entry_by_id(self, model_id: str) -> Optional[LocalModelEntry]:
        """
        Get a model entry by its ID.
        
        Parameters
        ----------
        model_id : str
            The model ID (e.g., "ollama:llama3.2:3b").
            
        Returns
        -------
        Optional[LocalModelEntry]
            The model entry, or None if not found.
        """
        # Ensure models are loaded
        self.get_available_models()
        
        for entry in self._models_cache:
            if entry.id == model_id:
                return entry
        
        # If not in cache, try to create an entry from the ID
        if model_id.startswith("ollama:"):
            model_name = model_id[7:]  # Remove "ollama:" prefix
            return LocalModelEntry(
                id=model_id,
                type="chat",
                backend="ollama",
                display_name=model_name,
                config={
                    "base_url": self.base_url,
                    "model": model_name,
                },
            )
        
        return None
    
    def test_connection(self) -> tuple[bool, str]:
        """
        Test connection to the Ollama server.
        
        Returns
        -------
        tuple[bool, str]
            (success, message)
        """
        if not self.backend:
            self.initialize()
        
        health = self.backend.health_check()
        return (health.ok, health.detail)
    
    def generate_chat_completion(
        self,
        messages: List[dict],
        model: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        chat_id: Optional[str] = None,
        stream_callback: Optional[Callable[[str], None]] = None,
        **kwargs: Any,
    ) -> str:
        """
        Generate a chat completion using Ollama.
        
        Parameters
        ----------
        messages : List[dict]
            Conversation messages.
        model : str
            Model ID (e.g., "ollama:llama3.2:3b").
        temperature : Optional[float]
            Sampling temperature.
        max_tokens : Optional[int]
            Maximum tokens to generate.
        chat_id : Optional[str]
            Chat ID for context (not used by Ollama).
        stream_callback : Optional[Callable[[str], None]]
            Callback for streaming chunks.
        **kwargs : Any
            Additional options.
            
        Returns
        -------
        str
            The generated response.
        """
        if not self.backend:
            self.initialize()
        
        entry = self.get_entry_by_id(model)
        if not entry:
            raise ValueError(f"Unknown model: {model}")
        
        self._log(f"Generating completion: model={model}, messages={len(messages)}")
        
        # Build tools if enabled
        from tools import build_tools_for_provider, build_enabled_tools_from_handlers
        
        # Get individual handlers for the tool check
        image_handler = kwargs.get("image_tool_handler")
        music_handler = kwargs.get("music_tool_handler")
        read_aloud_handler = kwargs.get("read_aloud_tool_handler")
        search_handler = kwargs.get("search_tool_handler")
        text_get_handler = kwargs.get("text_get_handler")
        text_edit_handler = kwargs.get("text_edit_handler")
        wolfram_handler = kwargs.get("wolfram_handler")
        
        enabled_tools = build_enabled_tools_from_handlers(
            image_handler,
            music_handler,
            read_aloud_handler,
            search_handler,
            text_get_handler,
            text_edit_handler,
            wolfram_handler,
        )
        tools = build_tools_for_provider(enabled_tools, "ollama") if enabled_tools else None
        
        # Pick the first available handler as the general tool call handler for Ollama
        tool_call_handler = wolfram_handler or search_handler or image_handler or \
                           music_handler or read_aloud_handler or text_edit_handler

        return self.backend.chat(
            entry=entry,
            messages=messages,
            stream_cb=stream_callback,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_call_handler=tool_call_handler,
        )
    
    # Methods required by AIProvider interface but not applicable to Ollama
    
    def generate_image(self, prompt: str, chat_id: str, model: str = None) -> str:
        """Not supported by Ollama."""
        raise NotImplementedError("Ollama does not support image generation")
    
    def transcribe_audio(self, audio_file: str) -> str:
        """Not supported by Ollama."""
        raise NotImplementedError("Ollama does not support audio transcription")
    
    def generate_speech(self, text: str, voice: str) -> bytes:
        """Not supported by Ollama."""
        raise NotImplementedError("Ollama does not support text-to-speech")
