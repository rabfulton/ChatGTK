"""
schema.py – ModelCard and Capabilities dataclasses.

This module defines the core data structures for the model card system:
- Capabilities: Flags indicating what a model can do
- ModelCard: Single source of truth for a model's identity, API, and behavior
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Set


@dataclass
class Capabilities:
    """Model capability flags."""
    text: bool = True
    vision: bool = False
    files: bool = False
    tool_use: bool = False
    web_search: bool = False
    audio_in: bool = False
    audio_out: bool = False
    image_gen: bool = False
    image_edit: bool = False


@dataclass
class ModelCard:
    """
    Single source of truth for a model's identity and behavior.

    This dataclass captures everything needed to route requests to the correct
    API endpoint, determine which tools can be offered, and handle model-specific
    quirks without scattered string matching throughout the codebase.
    """
    # Identity
    id: str                                     # e.g., "gpt-4o-mini"
    provider: str                               # openai|gemini|grok|claude|perplexity|custom
    display_name: Optional[str] = None          # UI name, falls back to id

    # API/transport
    api_family: str = "chat.completions"        # chat.completions|responses|images|tts
    base_url: Optional[str] = None              # Override for custom endpoints

    # Capabilities
    capabilities: Capabilities = field(default_factory=Capabilities)

    # Constraints
    max_tokens: Optional[int] = None
    max_images_per_message: Optional[int] = None
    supported_file_types: Set[str] = field(default_factory=set)
    image_sizes: Set[str] = field(default_factory=set)  # e.g., {"1024x1024", "1792x1024"}

    # Quirks (behavioral flags)
    quirks: Dict[str, Any] = field(default_factory=dict)
    # Examples: {"no_temperature": True, "needs_developer_role": True, "responses_only": True}

    # Credentials
    key_name: Optional[str] = None              # Lookup key in api_keys (e.g., "openai", "custom_xyz")

    def supports_tools(self) -> bool:
        """Return True if this model supports function/tool calling."""
        return self.capabilities.tool_use

    def is_image_model(self) -> bool:
        """Return True if this is a dedicated image generation model (not a chat model)."""
        return self.capabilities.image_gen and not self.capabilities.text

    def is_chat_model(self) -> bool:
        """Return True if this is a text chat model."""
        return self.capabilities.text and not self.is_image_model()

    def get_display_name(self) -> str:
        """Return the display name, falling back to the model ID."""
        return self.display_name or self.id
