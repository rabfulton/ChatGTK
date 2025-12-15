"""
loader.py – Model card loading and lookup.

This module provides functions to look up ModelCard instances by model ID,
with support for built-in cards, user-defined custom cards, user overrides,
and automatic synthesis from legacy custom_models.json entries.
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
    1. User card overrides (from model_card_overrides.json) applied to base card
    2. Registered custom cards (runtime via register_card())
    3. Built-in catalog (from catalog.py)
    4. Synthesized card from custom_models dict (legacy format)
    5. None (caller should use heuristics fallback)

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
    # Import here to avoid circular imports
    from .overrides import load_overrides, apply_override_to_card
    
    # Get base card from various sources
    base_card = None
    
    # Check registered custom cards first
    if model_id in _custom_cards:
        base_card = _custom_cards[model_id]
    # Then check builtin catalog
    elif model_id in BUILTIN_CARDS:
        base_card = BUILTIN_CARDS[model_id]
    # Finally try to synthesize from custom_models.json
    elif custom_models and model_id in custom_models:
        cfg = custom_models[model_id]
        base_card = _synthesize_card_from_custom(model_id, cfg)
    
    # Check for user overrides and apply them
    overrides = load_overrides()
    if model_id in overrides:
        override_data = overrides[model_id]
        if base_card:
            # Apply override to existing card
            return apply_override_to_card(base_card, override_data)
        else:
            # Create new card from override (for completely custom models)
            return _create_card_from_override(model_id, override_data)
    
    return base_card


def _create_card_from_override(model_id: str, override: dict) -> ModelCard:
    """
    Create a new ModelCard entirely from override data.
    
    Used when a user creates a card for a model that doesn't exist in
    the builtin catalog or custom_models.json.
    """
    caps_data = override.get("capabilities", {})
    caps = Capabilities(
        text=caps_data.get("text", True),
        vision=caps_data.get("vision", False),
        files=caps_data.get("files", False),
        tool_use=caps_data.get("tool_use", False),
        web_search=caps_data.get("web_search", False),
        audio_in=caps_data.get("audio_in", False),
        audio_out=caps_data.get("audio_out", False),
        image_gen=caps_data.get("image_gen", False),
        image_edit=caps_data.get("image_edit", False),
    )
    
    return ModelCard(
        id=model_id,
        provider=override.get("provider", "custom"),
        display_name=override.get("display_name"),
        api_family=override.get("api_family", "chat.completions"),
        base_url=override.get("base_url"),
        temperature=override.get("temperature"),
        capabilities=caps,
        max_tokens=override.get("max_tokens"),
        quirks=override.get("quirks", {}),
        key_name=override.get("key_name"),
    )


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

    voice = cfg.get("voice")
    if not voice:
        cfg_voices = cfg.get("voices")
        if isinstance(cfg_voices, list) and cfg_voices:
            # Use the first listed voice as the default for synthesized cards
            voice = cfg_voices[0]

    return ModelCard(
        id=model_id,
        provider="custom",
        display_name=cfg.get("display_name") or model_id,
        api_family=api_type,
        base_url=cfg.get("endpoint"),
        voice=voice,  # Voice for TTS models
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
