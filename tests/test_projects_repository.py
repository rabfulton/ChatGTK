"""Project names and IDs must never escape the project storage root."""

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from repositories import projects_repository as projects


@pytest.fixture
def repository(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setattr(projects, "PROJECTS_FILE", str(tmp_path / "projects.json"))
    return projects.ProjectsRepository()


@pytest.mark.parametrize("name", ["..", "../outside", "/tmp/absolute", r"..\outside", "C/C++", "📚"])
def test_project_names_generate_safe_unique_ids(repository, tmp_path, name):
    sentinel = tmp_path / "history" / "important.json"
    sentinel.parent.mkdir()
    sentinel.write_text("original")
    project = repository.create(name)
    directory = Path(repository.get_history_dir(project.id))
    assert directory.parent.parent == (tmp_path / "projects").resolve()
    assert project.id not in (".", "..")
    assert "/" not in project.id and "\\" not in project.id
    assert repository.create(name).id != project.id
    assert repository.delete(project.id)
    assert sentinel.read_text() == "original"


@pytest.mark.parametrize("project_id", ["", ".", "..", "../outside", "/tmp/outside", r"..\outside", "bad\x00id"])
def test_unsafe_project_ids_are_rejected(repository, project_id):
    with pytest.raises(ValueError):
        repository.get_history_dir(project_id)


def test_unsafe_persisted_ids_are_ignored_without_touching_history(repository, tmp_path):
    Path(projects.PROJECTS_FILE).write_text(json.dumps({"projects": [
        {"id": "..", "name": "Unsafe"}, {"id": "safe.legacy", "name": "Safe"},
    ]}))
    loaded = projects.ProjectsRepository()
    assert loaded.get("..") is None
    assert loaded.get("safe.legacy").name == "Safe"
    assert loaded.delete("..") is False
    loaded.create("New safe project")
    saved = json.loads(Path(projects.PROJECTS_FILE).read_text())
    assert {"id": "..", "name": "Unsafe"} in saved["projects"]


@pytest.mark.parametrize("symlink_part", ["project", "history"])
def test_symlinks_cannot_redirect_project_deletion(repository, tmp_path, symlink_part):
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "important.json"
    sentinel.write_text("original")
    root = Path(projects.PROJECTS_DIR)
    root.mkdir()
    directory = root / "linked"
    if symlink_part == "project":
        directory.symlink_to(outside, target_is_directory=True)
    else:
        directory.mkdir()
        (directory / "history").symlink_to(outside, target_is_directory=True)
    repository._projects["linked"] = projects.Project("linked", "Linked")
    with pytest.raises(ValueError):
        repository.delete("linked")
    assert sentinel.read_text() == "original"


@pytest.mark.parametrize("operation", ["copy_chat_to_project", "move_chat_to_project"])
def test_transfer_to_same_project_preserves_assets(repository, operation):
    project = repository.create("Current")
    directory = Path(repository.get_history_dir(project.id))
    (directory / "chat.json").write_text('{"messages": []}')
    assets = directory / "chat"
    assets.mkdir()
    (assets / "image.png").write_bytes(b"original image")

    assert getattr(repository, operation)("chat", str(directory), project.id)
    assert (assets / "image.png").read_bytes() == b"original image"
    assert json.loads((directory / "chat.json").read_text()) == {"messages": []}
