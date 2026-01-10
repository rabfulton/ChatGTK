"""
Abstract base class for local model backends.
"""

from abc import ABC, abstractmethod
from typing import List, Callable, Optional, Any

from .types import LocalModelEntry, LocalModelHealth


class LocalModelBackend(ABC):
    """
    Protocol for local model backends.
    
    Each backend (Ollama, sherpa-onnx, etc.) implements this interface
    to provide model discovery, health checks, and inference.
    """
    
    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Return the unique name for this backend (e.g., 'ollama')."""
        pass
    
    @abstractmethod
    def list_models(self) -> List[LocalModelEntry]:
        """
        Discover available models from this backend.
        
        Returns a list of LocalModelEntry objects for each model found.
        For backends like Ollama, this queries the server for installed models.
        For in-process backends, this scans local directories.
        """
        pass
    
    @abstractmethod
    def health_check(self, entry: Optional[LocalModelEntry] = None) -> LocalModelHealth:
        """
        Check if the backend (and optionally a specific model) is available.
        
        Parameters
        ----------
        entry : Optional[LocalModelEntry]
            If provided, check this specific model. Otherwise, check
            backend connectivity.
            
        Returns
        -------
        LocalModelHealth
            Health status with ok flag, detail message, and latency.
        """
        pass
    
    @abstractmethod
    def chat(
        self,
        entry: LocalModelEntry,
        messages: List[dict],
        stream_cb: Optional[Callable[[str], None]] = None,
        **opts: Any,
    ) -> str:
        """
        Generate a chat completion.
        
        Parameters
        ----------
        entry : LocalModelEntry
            The model configuration to use.
        messages : List[dict]
            Conversation messages in ChatGTK format:
            [{"role": "user"|"assistant"|"system", "content": "..."}]
        stream_cb : Optional[Callable[[str], None]]
            If provided, called with each text chunk as it arrives.
        **opts : Any
            Additional options (temperature, max_tokens, etc.)
            
        Returns
        -------
        str
            The complete response text.
        """
        pass
