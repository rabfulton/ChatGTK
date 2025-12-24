"""
Shared history index helpers for fast sidebar listings.
"""

import json
from pathlib import Path
from typing import Dict, Any


HISTORY_INDEX_FILENAME = ".history_index.json"


def _default_index() -> Dict[str, Any]:
    return {"version": 1, "entries": {}}


def load_history_index(history_dir: Path) -> Dict[str, Any]:
    """Load the history index file or return an empty index."""
    path = history_dir / HISTORY_INDEX_FILENAME
    if not path.exists():
        return _default_index()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "entries" not in data:
            return _default_index()
        if not isinstance(data.get("entries"), dict):
            data["entries"] = {}
        return data
    except Exception:
        return _default_index()


def save_history_index(history_dir: Path, data: Dict[str, Any]) -> None:
    """Persist the history index file."""
    path = history_dir / HISTORY_INDEX_FILENAME
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass
