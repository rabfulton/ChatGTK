"""
model_cards – Unified model capability and routing system.

This package provides a single source of truth for model identity, capabilities,
and behavioral quirks, replacing scattered string heuristics throughout the codebase.

Usage:
    from model_cards import get_card, ModelCard, Capabilities

    card = get_card("gpt-4o-mini")
    if card and card.supports_tools():
        # Enable tool calling for this model
        ...
"""

from .schema import ModelCard, Capabilities
from .loader import (
    get_card,
    list_cards,
    register_card,
    unregister_card,
    clear_custom_cards,
)

__all__ = [
    "ModelCard",
    "Capabilities",
    "get_card",
    "list_cards",
    "register_card",
    "unregister_card",
    "clear_custom_cards",
]
