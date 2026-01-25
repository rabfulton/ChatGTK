import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_search_tool_scans_chat_imports_dir(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "HISTORY_DIR", str(tmp_path))

    from controller import ChatController
    from repositories import SettingsRepository

    settings_repo = SettingsRepository(settings_file=str(tmp_path / "settings.cfg"))
    controller = ChatController(settings_repo=settings_repo)
    controller.current_chat_id = "chat_123"

    imports_dir = tmp_path / "chat_123" / "imports"
    imports_dir.mkdir(parents=True)
    (imports_dir / "doc.txt").write_text("hello keyword world", encoding="utf-8")

    result = controller.handle_search_tool("keyword", source="documents")
    assert "Found" in result
    assert "doc.txt" in result or "Source:" in result
