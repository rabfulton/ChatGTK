"""Memory settings load once, including without optional dependencies."""

from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import dialogs


@pytest.mark.parametrize("memory_available", [False, True])
def test_select_memory_replaces_placeholder_once(monkeypatch, memory_available):
    memory = SimpleNamespace(
        MEMORY_AVAILABLE=memory_available,
        LOCAL_EMBEDDINGS_AVAILABLE=False,
        get_missing_dependencies=lambda: ["qdrant-client"],
    )
    monkeypatch.setitem(sys.modules, "memory", memory)

    # Exercise the real builders without creating a window or requiring a display.
    gtk = Mock()
    gtk.ComboBoxText.side_effect = lambda: Mock(
        get_active_text=Mock(return_value="openai"),
    )
    monkeypatch.setattr(dialogs, "Gtk", gtk)
    idle_add = Mock()
    monkeypatch.setattr(dialogs.GLib, "idle_add", idle_add)

    class SettingsHarness:
        _on_sidebar_row_selected = dialogs.SettingsDialog._on_sidebar_row_selected
        _build_memory_page = dialogs.SettingsDialog._build_memory_page
        _ensure_memory_page = dialogs.SettingsDialog._ensure_memory_page
        _replace_stack_page = dialogs.SettingsDialog._replace_stack_page
        _populate_embedding_models = dialogs.SettingsDialog._populate_embedding_models
        _memory_page_built = False
        custom_models = {}

    settings = SettingsHarness()
    settings._on_memory_embedding_mode_changed = Mock()
    settings._on_memory_import_clicked = Mock()
    settings._on_memory_refresh_stats = Mock()
    settings._on_memory_clear_clicked = Mock()
    placeholder = object()
    pages = {"Memory": placeholder}

    def add_page(widget, name):
        assert widget is not None, "The page builder must return a widget"
        assert name not in pages, "The placeholder must be removed first"
        pages[name] = widget

    settings.stack = Mock()
    settings.stack.get_child_by_name.side_effect = pages.get
    settings.stack.remove.side_effect = lambda widget: pages.pop("Memory")
    settings.stack.add_named.side_effect = add_page
    row = SimpleNamespace(category_name="Memory")

    settings._on_sidebar_row_selected(None, row)
    settings._on_sidebar_row_selected(None, row)

    assert settings._memory_page_built
    assert list(pages) == ["Memory"]
    assert pages["Memory"] is gtk.ScrolledWindow.return_value
    settings.stack.remove.assert_called_once_with(placeholder)
    settings.stack.add_named.assert_called_once_with(pages["Memory"], "Memory")
    assert settings.stack.set_visible_child_name.call_count == 2
    if not memory_available:
        markup = gtk.Label.return_value.set_markup.call_args.args[0]
        assert "qdrant-client" in markup
        assert "additional dependencies" in markup
