"""File helpers shared by repositories."""

import json
import os
from pathlib import Path
import stat
import tempfile


def atomic_write_json(path, data, *, indent=2, ensure_ascii=True) -> None:
    """Replace a JSON file atomically, preserving its previous contents on failure."""
    path = Path(path)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=indent, ensure_ascii=ensure_ascii)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
