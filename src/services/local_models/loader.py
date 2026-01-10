"""
Load and save local model configurations.
"""

import json
import os
from pathlib import Path
from typing import List, Dict

from config import LOCAL_MODELS_FILE
from .types import LocalModelEntry


def load_local_models() -> List[LocalModelEntry]:
    """
    Load local model entries from local_models.json.
    
    Returns
    -------
    List[LocalModelEntry]
        List of configured local models, or empty list if file doesn't exist.
    """
    if not os.path.exists(LOCAL_MODELS_FILE):
        return []
    
    try:
        with open(LOCAL_MODELS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        entries = []
        for item in data.get("models", []):
            try:
                entry = LocalModelEntry.from_dict(item)
                entries.append(entry)
            except (KeyError, TypeError) as e:
                print(f"[LocalModels] Skipping invalid entry: {e}")
                continue
        
        return entries
        
    except (json.JSONDecodeError, IOError) as e:
        print(f"[LocalModels] Failed to load {LOCAL_MODELS_FILE}: {e}")
        return []


def save_local_models(entries: List[LocalModelEntry]) -> bool:
    """
    Save local model entries to local_models.json.
    
    Parameters
    ----------
    entries : List[LocalModelEntry]
        The model entries to save.
        
    Returns
    -------
    bool
        True if saved successfully.
    """
    # Ensure parent directory exists
    Path(LOCAL_MODELS_FILE).parent.mkdir(parents=True, exist_ok=True)
    
    data = {
        "models": [entry.to_dict() for entry in entries],
    }
    
    try:
        with open(LOCAL_MODELS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except IOError as e:
        print(f"[LocalModels] Failed to save {LOCAL_MODELS_FILE}: {e}")
        return False


def merge_discovered_models(
    saved: List[LocalModelEntry],
    discovered: List[LocalModelEntry],
) -> List[LocalModelEntry]:
    """
    Merge saved configurations with newly discovered models.
    
    Preserves user settings (enabled, display_name overrides) for existing
    models while adding newly discovered ones.
    
    Parameters
    ----------
    saved : List[LocalModelEntry]
        Previously saved model entries.
    discovered : List[LocalModelEntry]
        Newly discovered models from backends.
        
    Returns
    -------
    List[LocalModelEntry]
        Merged list of models.
    """
    saved_by_id: Dict[str, LocalModelEntry] = {e.id: e for e in saved}
    result = []
    seen_ids = set()
    
    # Process discovered models, preserving saved settings
    for model in discovered:
        if model.id in saved_by_id:
            # Preserve user settings from saved entry
            saved_entry = saved_by_id[model.id]
            model.enabled = saved_entry.enabled
            if saved_entry.display_name != saved_entry.id:
                # User customized the display name
                model.display_name = saved_entry.display_name
        
        result.append(model)
        seen_ids.add(model.id)
    
    # Add saved models that weren't discovered (may be offline)
    for saved_entry in saved:
        if saved_entry.id not in seen_ids:
            # Mark as unavailable but keep in list
            result.append(saved_entry)
    
    return result
