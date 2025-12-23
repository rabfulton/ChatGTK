"""
conversation.py – Domain layer for message structures and history operations.

This module provides:
- Message and ProviderMeta dataclasses for representing conversation messages.
- Helper functions for creating, manipulating, and converting conversation history.
- Integration with the tools module for prompt shaping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from tools import append_tool_guidance, is_chat_completion_model


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ProviderMeta:
    """
    Provider-specific metadata attached to a message.
    
    This can hold arbitrary data that specific providers need to track
    (e.g., Gemini thought signatures).
    """
    data: Dict[str, Any] = field(default_factory=dict)
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from the metadata."""
        return self.data.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        """Set a value in the metadata."""
        self.data[key] = value
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return self.data.copy()
    
    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ProviderMeta":
        """Create from dictionary."""
        return cls(data=data.copy() if data else {})


@dataclass
class Message:
    """
    Represents a single message in a conversation.
    
    Attributes
    ----------
    role : str
        The role of the message sender ('system', 'user', 'assistant').
    content : str
        The text content of the message.
    images : Optional[List[Dict[str, Any]]]
        Optional list of attached images (each with 'data' and 'mime_type').
    files : Optional[List[Dict[str, Any]]]
        Optional list of attached document files. Each dict may contain:
        - 'path': Local file path (used before upload).
        - 'mime_type': MIME type of the file.
        - 'display_name': Human-readable filename for display.
        - 'file_id': Provider-assigned ID after upload (e.g., OpenAI file ID).
    provider_meta : ProviderMeta
        Provider-specific metadata.
    model : Optional[str]
        Model ID (stored in system message for chat restoration).
    text_edit_events : Optional[List[Dict[str, Any]]]
        Optional list of text edit events for undo support.
    """
    role: str
    content: str
    images: Optional[List[Dict[str, Any]]] = None
    files: Optional[List[Dict[str, Any]]] = None
    provider_meta: ProviderMeta = field(default_factory=ProviderMeta)
    model: Optional[str] = None
    text_edit_events: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization or API calls."""
        result: Dict[str, Any] = {
            "role": self.role,
            "content": self.content,
            "provider_meta": self.provider_meta.to_dict(),
        }
        if self.images:
            result["images"] = self.images
        if self.files:
            result["files"] = self.files
        if self.model:
            result["model"] = self.model
        if self.text_edit_events:
            result["text_edit_events"] = self.text_edit_events
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        """Create from dictionary."""
        return cls(
            role=data.get("role", "user"),
            content=data.get("content", ""),
            images=data.get("images"),
            files=data.get("files"),
            provider_meta=ProviderMeta.from_dict(data.get("provider_meta")),
            model=data.get("model"),
            text_edit_events=data.get("text_edit_events"),
        )


# ---------------------------------------------------------------------------
# Conversation history helpers
# ---------------------------------------------------------------------------

class ConversationHistory:
    """
    Manages a conversation history as a list of messages.
    
    This class provides a clean interface for manipulating conversation history
    and converting it for different purposes (API calls, serialization, etc.).
    """
    
    def __init__(self, system_message: str = "You are a helpful assistant.", metadata: Optional[Dict[str, Any]] = None):
        """
        Initialize a new conversation history.
        
        Parameters
        ----------
        system_message : str
            The initial system message for the conversation.
        metadata : Optional[Dict[str, Any]]
            Optional chat-level metadata (e.g., title, tags).
        """
        self._messages: List[Message] = [
            Message(role="system", content=system_message)
        ]
        self.metadata: Dict[str, Any] = metadata or {}
    
    @property
    def messages(self) -> List[Message]:
        """Return the list of messages."""
        return self._messages
    
    def __len__(self) -> int:
        return len(self._messages)
    
    def __getitem__(self, index: int) -> Message:
        return self._messages[index]
    
    def add_user_message(
        self,
        content: str,
        images: Optional[List[Dict[str, Any]]] = None,
        files: Optional[List[Dict[str, Any]]] = None,
    ) -> Message:
        """
        Add a user message to the history.
        
        Parameters
        ----------
        content : str
            The message content.
        images : Optional[List[Dict[str, Any]]]
            Optional list of attached images.
        files : Optional[List[Dict[str, Any]]]
            Optional list of attached document files.
        
        Returns
        -------
        Message
            The created message.
        """
        msg = Message(role="user", content=content, images=images, files=files)
        self._messages.append(msg)
        return msg
    
    def add_assistant_message(
        self,
        content: str,
        provider_meta: Optional[Dict[str, Any]] = None,
    ) -> Message:
        """
        Add an assistant message to the history.
        
        Parameters
        ----------
        content : str
            The message content.
        provider_meta : Optional[Dict[str, Any]]
            Optional provider-specific metadata.
        
        Returns
        -------
        Message
            The created message.
        """
        msg = Message(
            role="assistant",
            content=content,
            provider_meta=ProviderMeta.from_dict(provider_meta),
        )
        self._messages.append(msg)
        return msg
    
    def get_last_message(self) -> Optional[Message]:
        """Return the last message, or None if empty."""
        return self._messages[-1] if self._messages else None
    
    def get_first_user_message(self) -> Optional[Message]:
        """Return the first user message, or None if none exists."""
        for msg in self._messages:
            if msg.role == "user":
                return msg
        return None
    
    def clear(self, system_message: str = "You are a helpful assistant.") -> None:
        """
        Clear the history and reset with a new system message.
        
        Parameters
        ----------
        system_message : str
            The new system message.
        """
        self._messages = [Message(role="system", content=system_message)]
    
    def to_list(self) -> List[Dict[str, Any]]:
        """
        Convert to a list of dictionaries for serialization.
        
        Returns
        -------
        List[Dict[str, Any]]
            The conversation history as a list of dicts.
        """
        return [msg.to_dict() for msg in self._messages]
    
    @classmethod
    def from_list(cls, data: List[Dict[str, Any]], default_system: str = "You are a helpful assistant.", metadata: Optional[Dict[str, Any]] = None) -> "ConversationHistory":
        """
        Create from a list of dictionaries.
        
        Parameters
        ----------
        data : List[Dict[str, Any]]
            The conversation history as a list of dicts.
        default_system : str
            Default system message if none is present.
        metadata : Optional[Dict[str, Any]]
            Optional chat-level metadata.
        
        Returns
        -------
        ConversationHistory
            The created conversation history.
        """
        history = cls.__new__(cls)
        history._messages = [Message.from_dict(d) for d in data] if data else []
        history.metadata = metadata or {}
        
        # Ensure there's a system message at the start
        if not history._messages or history._messages[0].role != "system":
            history._messages.insert(0, Message(role="system", content=default_system))
        
        return history
    
    def to_provider_messages(
        self,
        model_name: str,
        enabled_tools: Optional[Set[str]] = None,
        model_provider_map: Optional[Dict[str, str]] = None,
        custom_models: Optional[Dict[str, Any]] = None,
        settings_manager=None,
    ) -> List[Dict[str, Any]]:
        """
        Convert to a list of message dicts suitable for sending to a provider.
        
        This method applies tool guidance to the system prompt when appropriate.
        
        Parameters
        ----------
        model_name : str
            The model name to use for determining capabilities.
        enabled_tools : Optional[Set[str]]
            Set of enabled tool names.
        model_provider_map : Optional[Dict[str, str]]
            Optional mapping of model names to provider names.
        custom_models : Optional[Dict[str, Any]]
            Optional dict of custom model configurations.
        settings_manager : Optional[SettingsManager]
            Optional settings manager for tool prompt appendices.
        
        Returns
        -------
        List[Dict[str, Any]]
            The messages formatted for the provider.
        """
        if not self._messages:
            return []
        
        # For non-chat-completion models, return as-is
        if not is_chat_completion_model(model_name, custom_models):
            return self.to_list()
        
        # Get the base messages
        messages = self.to_list()
        
        # If there's no system message or no tools, return as-is
        if not messages or messages[0].get("role") != "system":
            return messages
        
        if enabled_tools is None:
            enabled_tools = set()
        
        # Apply tool guidance to the system prompt
        current_prompt = messages[0].get("content", "") or ""
        try:
            new_prompt = append_tool_guidance(
                current_prompt,
                enabled_tools,
                include_math=True,
                settings_manager=settings_manager
            )
        except Exception as e:
            print(f"Error while appending tool guidance: {e}")
            new_prompt = current_prompt
        
        # If nothing changed, return the original
        if new_prompt == current_prompt:
            return messages
        
        # Create a copy with the modified system prompt
        result = [msg.copy() for msg in messages]
        result[0]["content"] = new_prompt
        return result


# ---------------------------------------------------------------------------
# Standalone helper functions (deprecated - use ConversationHistory methods)
# ---------------------------------------------------------------------------
# These functions are maintained for backward compatibility but are deprecated.
# New code should use ConversationHistory class methods instead:
#   - ConversationHistory.add_user_message()
#   - ConversationHistory.add_assistant_message()
#   - ConversationHistory(system_message=...) for system messages
# ---------------------------------------------------------------------------

import warnings

_DEPRECATION_WARNED = set()  # Track which warnings have been shown


def _warn_once(func_name: str, alternative: str) -> None:
    """Show deprecation warning once per function."""
    if func_name not in _DEPRECATION_WARNED:
        _DEPRECATION_WARNED.add(func_name)
        warnings.warn(
            f"{func_name}() is deprecated. Use {alternative} instead. "
            "This function will be removed in a future version.",
            DeprecationWarning,
            stacklevel=3
        )


def create_system_message(content: str) -> Dict[str, Any]:
    """Create a system message dict.
    
    .. deprecated::
        Use ``ConversationHistory(system_message=content)`` instead.
    """
    # Note: Not warning for system messages as they're commonly used at init
    return {"role": "system", "content": content, "provider_meta": {}}


def create_user_message(
    content: str,
    images: Optional[List[Dict[str, Any]]] = None,
    files: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Create a user message dict.
    
    .. deprecated::
        Use ``ConversationHistory.add_user_message()`` instead.
    
    Parameters
    ----------
    content : str
        The message content.
    images : Optional[List[Dict[str, Any]]]
        Optional list of attached images (each with 'data' and 'mime_type').
    files : Optional[List[Dict[str, Any]]]
        Optional list of attached document files. Each dict may contain:
        - 'path': Local file path (used before upload).
        - 'mime_type': MIME type of the file.
        - 'display_name': Human-readable filename for display.
        - 'file_id': Provider-assigned ID after upload.
    
    Returns
    -------
    Dict[str, Any]
        The user message dictionary.
    """
    msg: Dict[str, Any] = {"role": "user", "content": content, "provider_meta": {}}
    if images:
        msg["images"] = images
    if files:
        msg["files"] = files
    return msg


def create_assistant_message(
    content: str,
    provider_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create an assistant message dict.
    
    .. deprecated::
        Use ``ConversationHistory.add_assistant_message()`` instead.
    """
    return {
        "role": "assistant",
        "content": content,
        "provider_meta": provider_meta or {},
    }


def get_first_user_content(history: List[Dict[str, Any]]) -> str:
    """Get the content of the first user message in a history.
    
    .. deprecated::
        Use ``ConversationHistory.get_first_user_message()`` instead.
    """
    for msg in history:
        if msg.get("role") == "user":
            return msg.get("content", "")
    return ""


def prepare_messages_for_model(
    history: List[Dict[str, Any]],
    model_name: str,
    enabled_tools: Optional[Set[str]] = None,
    custom_models: Optional[Dict[str, Any]] = None,
    settings_manager=None,
) -> List[Dict[str, Any]]:
    """
    Prepare a conversation history for sending to a model.
    
    This is a convenience function that applies tool guidance to the system prompt.
    
    Parameters
    ----------
    history : List[Dict[str, Any]]
        The conversation history as a list of dicts.
    model_name : str
        The model name.
    enabled_tools : Optional[Set[str]]
        Set of enabled tool names.
    custom_models : Optional[Dict[str, Any]]
        Optional dict of custom model configurations.
    settings_manager : Optional[SettingsManager]
        Optional settings manager for tool prompt appendices.
    
    Returns
    -------
    List[Dict[str, Any]]
        The prepared messages.
    """
    if not history:
        return []
    
    if not is_chat_completion_model(model_name, custom_models):
        return history
    
    first_message = history[0]
    if first_message.get("role") != "system":
        return history
    
    current_prompt = first_message.get("content", "") or ""
    
    if enabled_tools is None:
        enabled_tools = set()
    
    try:
        new_prompt = append_tool_guidance(
            current_prompt,
            enabled_tools,
            include_math=True,
            settings_manager=settings_manager
        )
    except Exception as e:
        print(f"Error while appending tool guidance: {e}")
        new_prompt = current_prompt
    
    if new_prompt == current_prompt:
        return history
    
    messages = [msg.copy() for msg in history]
    messages[0]["content"] = new_prompt
    return messages
