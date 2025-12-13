"""
loader.py – Model card loading and lookup.

This module provides functions to look up ModelCard instances by model ID,
with support for built-in cards, user-defined custom cards, and automatic
synthesis from legacy custom_models.json entries.
"""

from typing import Optional, Dict

from .schema import ModelCard, Capabilities
from .catalog import BUILTIN_CARDS


# Cache for dynamically registered custom cards
_custom_cards: Dict[str, ModelCard] = {}


def get_card(model_id: str, custom_models: Optional[dict] = None) -> Optional[ModelCard]:
    """
    Look up a ModelCard by ID.

    Priority order:
    1. User-defined custom cards (registered via register_card())
    2. Built-in catalog (from catalog.py)
    3. Synthesized card from custom_models dict (legacy format)
    4. None (caller should use heuristics fallback)

    Parameters
    ----------
    model_id : str
        The model identifier to look up.
    custom_models : dict, optional
        Dict of custom model configurations (from custom_models.json).
        Each entry maps model_id -> {"endpoint": ..., "api_type": ..., ...}

    Returns
    -------
    ModelCard or None
        The model card if found, or None if the model is unknown.
    """
    # 1. Check custom cards cache (user-registered)
    if model_id in _custom_cards:
        return _custom_cards[model_id]

    # 2. Check builtin catalog
    if model_id in BUILTIN_CARDS:
        return BUILTIN_CARDS[model_id]

    # 3. Synthesize from custom_models.json
    if custom_models and model_id in custom_models:
        cfg = custom_models[model_id]
        return _synthesize_card_from_custom(model_id, cfg)

    return None


def _synthesize_card_from_custom(model_id: str, cfg: dict) -> ModelCard:
    """
    Create a ModelCard from a legacy custom_models.json entry.

    This allows existing custom model definitions to work with the new
    card-based system without requiring users to migrate their configs.

    Parameters
    ----------
    model_id : str
        The model identifier.
    cfg : dict
        Configuration dict with keys like "endpoint", "api_type", "display_name", etc.

    Returns
    -------
    ModelCard
        A synthesized model card based on the configuration.
    """
    api_type = (cfg.get("api_type") or "chat.completions").lower()

    # Infer capabilities from api_type
    if api_type == "images":
        caps = Capabilities(text=False, image_gen=True)
    elif api_type == "tts":
        caps = Capabilities(text=False, audio_out=True)
    elif api_type == "responses":
        # Responses API typically indicates a modern model with tool support
        caps = Capabilities(text=True, tool_use=True, vision=True)
    else:
        # Default chat.completions: assume text + tools
        caps = Capabilities(text=True, tool_use=True)

    return ModelCard(
        id=model_id,
        provider="custom",
        display_name=cfg.get("display_name") or model_id,
        api_family=api_type,
        base_url=cfg.get("endpoint"),
        capabilities=caps,
        key_name=model_id,  # Custom models use their own key
    )


def register_card(card: ModelCard) -> None:
    """
    Register a custom model card.

    This allows runtime registration of model cards, which takes precedence
    over built-in cards for the same model ID.

    Parameters
    ----------
    card : ModelCard
        The model card to register.
    """
    _custom_cards[card.id] = card


def unregister_card(model_id: str) -> bool:
    """
    Unregister a custom model card.

    Parameters
    ----------
    model_id : str
        The model ID to unregister.

    Returns
    -------
    bool
        True if a card was removed, False if no custom card existed.
    """
    if model_id in _custom_cards:
        del _custom_cards[model_id]
        return True
    return False


def list_cards() -> Dict[str, ModelCard]:
    """
    Return all known cards (builtin + custom).

    Custom cards override builtin cards with the same ID.

    Returns
    -------
    Dict[str, ModelCard]
        Mapping of model ID to ModelCard.
    """
    return {**BUILTIN_CARDS, **_custom_cards}


def clear_custom_cards() -> None:
    """Clear all registered custom cards. Useful for testing."""
    _custom_cards.clear()
