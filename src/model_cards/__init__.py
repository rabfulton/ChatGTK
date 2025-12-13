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
from .overrides import (
    load_overrides,
    save_overrides,
    get_override,
    set_override,
    delete_override,
    apply_override_to_card,
    card_to_override_dict,
)

__all__ = [
    "ModelCard",
    "Capabilities",
    "get_card",
    "list_cards",
    "register_card",
    "unregister_card",
    "clear_custom_cards",
    "load_overrides",
    "save_overrides",
    "get_override",
    "set_override",
    "delete_override",
    "apply_override_to_card",
    "card_to_override_dict",
]
