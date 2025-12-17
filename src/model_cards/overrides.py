"""
overrides.py – User overrides for model cards.

This module handles loading and saving user customizations to model cards,
allowing users to override capabilities, quirks, and other settings for
both builtin and custom models.
"""

import json
import os
from pathlib import Path
from typing import Optional, Dict, Any

from .schema import ModelCard, Capabilities


def _get_overrides_file_path() -> str:
    """Get the path to the model card overrides file, using the app's data directory."""
    try:
        from config import PARENT_DIR
        return os.path.join(PARENT_DIR, "model_card_overrides.json")
    except ImportError:
        # Fallback if config not available
        return os.path.join(os.path.expanduser("~"), ".local", "share", "chatgtk", "model_card_overrides.json")


def load_overrides() -> Dict[str, Dict[str, Any]]:
    """
    Load user model card overrides from disk.
    
    Returns a dict mapping model_id -> override data.
    Override data can include: display_name, provider, api_family, base_url,
    capabilities (dict), quirks (dict), max_tokens, context_window.
    """
    try:
        overrides_file = _get_overrides_file_path()
        if not Path(overrides_file).exists():
            return {}
        with open(overrides_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception as e:
        print(f"Error loading model card overrides: {e}")
    return {}


def save_overrides(overrides: Dict[str, Dict[str, Any]]) -> None:
    """
    Save user model card overrides to disk.
    
    Parameters
    ----------
    overrides : dict
        Dict mapping model_id -> override data.
    """
    try:
        overrides_file = _get_overrides_file_path()
        Path(overrides_file).parent.mkdir(parents=True, exist_ok=True)
        with open(overrides_file, 'w', encoding='utf-8') as f:
            json.dump(overrides or {}, f, indent=2)
    except Exception as e:
        print(f"Error saving model card overrides: {e}")


def get_override(model_id: str) -> Optional[Dict[str, Any]]:
    """Get the override data for a specific model, or None if not overridden."""
    overrides = load_overrides()
    return overrides.get(model_id)


def set_override(model_id: str, override_data: Dict[str, Any]) -> None:
    """Set or update the override data for a specific model."""
    overrides = load_overrides()
    overrides[model_id] = override_data
    save_overrides(overrides)


def delete_override(model_id: str) -> bool:
    """
    Delete the override for a specific model.
    
    Returns True if an override was deleted, False if none existed.
    """
    overrides = load_overrides()
    if model_id in overrides:
        del overrides[model_id]
        save_overrides(overrides)
        return True
    return False


def apply_override_to_card(card: ModelCard, override: Dict[str, Any]) -> ModelCard:
    """
    Apply override data to a model card, returning a new card with overrides applied.
    
    The original card is not modified.
    
    Parameters
    ----------
    card : ModelCard
        The base model card.
    override : dict
        Override data to apply.
        
    Returns
    -------
    ModelCard
        A new card with overrides applied.
    """
    # Start with a copy of the card's data
    new_display_name = override.get("display_name", card.display_name)
    new_provider = override.get("provider", card.provider)
    new_api_family = override.get("api_family", card.api_family)
    new_base_url = override.get("base_url", card.base_url)
    new_temperature = override.get("temperature") if "temperature" in override else card.temperature
    new_max_tokens = override.get("max_tokens", card.max_tokens)
    new_key_name = override.get("key_name", card.key_name)
    
    # Merge capabilities
    caps_override = override.get("capabilities", {})
    new_caps = Capabilities(
        text=caps_override.get("text", card.capabilities.text),
        vision=caps_override.get("vision", card.capabilities.vision),
        files=caps_override.get("files", card.capabilities.files),
        tool_use=caps_override.get("tool_use", card.capabilities.tool_use),
        web_search=caps_override.get("web_search", card.capabilities.web_search),
        audio_in=caps_override.get("audio_in", card.capabilities.audio_in),
        audio_out=caps_override.get("audio_out", card.capabilities.audio_out),
        image_gen=caps_override.get("image_gen", card.capabilities.image_gen),
        image_edit=caps_override.get("image_edit", card.capabilities.image_edit),
    )
    
    # Merge quirks
    new_quirks = {**card.quirks, **override.get("quirks", {})}
    
    # Merge constraints
    new_image_sizes = set(override.get("image_sizes", list(card.image_sizes)))
    new_supported_file_types = set(override.get("supported_file_types", list(card.supported_file_types)))
    new_max_images = override.get("max_images_per_message", card.max_images_per_message)
    
    return ModelCard(
        id=card.id,
        provider=new_provider,
        display_name=new_display_name,
        api_family=new_api_family,
        base_url=new_base_url,
        capabilities=new_caps,
        temperature=new_temperature,
        max_tokens=new_max_tokens,
        max_images_per_message=new_max_images,
        supported_file_types=new_supported_file_types,
        image_sizes=new_image_sizes,
        quirks=new_quirks,
        key_name=new_key_name,
    )


def card_to_override_dict(card: ModelCard) -> Dict[str, Any]:
    """
    Convert a ModelCard to an override dict suitable for saving.
    
    This extracts all non-default values from the card.
    """
    return {
        "display_name": card.display_name,
        "provider": card.provider,
        "api_family": card.api_family,
        "base_url": card.base_url,
        "temperature": card.temperature,
        "capabilities": {
            "text": card.capabilities.text,
            "vision": card.capabilities.vision,
            "files": card.capabilities.files,
            "tool_use": card.capabilities.tool_use,
            "web_search": card.capabilities.web_search,
            "audio_in": card.capabilities.audio_in,
            "audio_out": card.capabilities.audio_out,
            "image_gen": card.capabilities.image_gen,
            "image_edit": card.capabilities.image_edit,
        },
        "quirks": card.quirks,
        "max_tokens": card.max_tokens,
    }
