"""Interrupted writes must not damage the previous saved conversation."""

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from repositories import ChatHistoryRepository, DocumentRepository
from repositories import file_utils


@pytest.mark.parametrize("kind", ["chat", "document"])
@pytest.mark.parametrize("failure", ["serialize", "write", "fsync", "replace"])
def test_failed_save_preserves_previous_json(tmp_path, monkeypatch, kind, failure):
    if kind == "chat":
        repo = ChatHistoryRepository(str(tmp_path))
        repo.save("chat", [{"role": "user", "content": "Original text"}])
        target = tmp_path / "chat.json"
        save = lambda: repo.save("chat", [{"role": "user", "content": "New text"}])
    else:
        repo = DocumentRepository(str(tmp_path))
        doc = repo.create("Document", "Original text")
        target = repo._get_path(doc.id)
        doc.content = "New text"
        save = lambda: repo.save(doc)
    original = target.read_bytes()

    def fail(*args, **kwargs):
        if failure in ("serialize", "write"):
            args[1].write('{"partial":')
        if failure == "serialize":
            raise TypeError("Cannot serialize value")
        raise OSError("Simulated disk failure")

    if failure in ("serialize", "write"):
        monkeypatch.setattr(file_utils.json, "dump", fail)
    else:
        monkeypatch.setattr(file_utils.os, failure, fail)

    with pytest.raises((OSError, TypeError)):
        save()
    assert target.read_bytes() == original
    json.loads(target.read_text())
    assert list(tmp_path.glob(".*.tmp")) == []


def test_atomic_save_preserves_permissions_and_unicode(tmp_path):
    path = tmp_path / "history.json"
    path.write_text('{"old": true}')
    path.chmod(0o640)
    file_utils.atomic_write_json(path, {"text": "こんにちは"}, ensure_ascii=False)
    assert json.loads(path.read_text()) == {"text": "こんにちは"}
    assert "こんにちは" in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o640
    assert list(tmp_path.glob(".*.tmp")) == []


def test_failed_first_save_leaves_no_partial_file(tmp_path):
    path = tmp_path / "new.json"
    with pytest.raises(TypeError):
        file_utils.atomic_write_json(path, {"invalid": object()})
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []
