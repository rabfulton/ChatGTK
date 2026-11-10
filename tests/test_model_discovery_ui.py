"""Specialized model selectors must use discovered IDs and route selections."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import gi
import pytest

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import dialogs
from ChatGTK import OpenAIGTKClient
from model_cards import loader, overrides, register_discovered_models
from repositories import ModelCacheRepository


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "_discovered_cards", {})
    monkeypatch.setattr(loader, "_custom_cards", {})
    monkeypatch.setattr(overrides, "load_overrides", dict)
    monkeypatch.setattr(
        dialogs,
        "ModelCacheRepository",
        lambda: ModelCacheRepository(str(tmp_path / "cache.json")),
    )


def test_cached_special_models_return_to_feature_selectors_after_restart():
    image = "gpt-image-2"
    speech = "gpt-4o-mini-tts-2026-11-01"
    gemini = "gemini-3.5-flash-preview-tts"
    dialogs.save_model_cache({"openai": [image, speech], "gemini": [gemini]})
    loader._discovered_cards.clear()
    settings = SimpleNamespace(custom_models={})
    assert image in dialogs.SettingsDialog._get_all_image_models(settings)
    options = dialogs.SettingsDialog._get_tts_model_options(settings)
    assert speech in options
    assert gemini in options
    assert "gpt-realtime" not in options
    # Chat models with a native image tool cannot be called via /images.
    assert "gpt-5.2" not in dialogs.SettingsDialog._get_all_image_models(settings)


def test_image_selector_respects_capability_overrides(monkeypatch):
    model = "gpt-image-2"
    dialogs.save_model_cache({"openai": [model]})
    monkeypatch.setattr(
        overrides,
        "load_overrides",
        lambda: {
            model: {"capabilities": {"image_gen": False}},
        },
    )
    assert model not in dialogs.SettingsDialog._get_all_image_models(
        SimpleNamespace(custom_models={})
    )


@pytest.mark.parametrize(
    "selection, method, model",
    [
        ("openai", "_synthesize_and_play_tts", None),
        ("gemini", "_synthesize_and_play_gemini_tts", None),
        (
            "gpt-4o-mini-tts-2026-11-01",
            "_synthesize_and_play_tts",
            "gpt-4o-mini-tts-2026-11-01",
        ),
        (
            "gemini-3.5-flash-preview-tts",
            "_synthesize_and_play_gemini_tts",
            "gemini-3.5-flash-preview-tts",
        ),
        ("gpt-audio-1.5", "_synthesize_and_play_audio_preview", "gpt-audio-1.5"),
        ("local-voice", "_synthesize_and_play_custom_tts", "local-voice"),
        ("gpt-4o-mini-tts", "_synthesize_and_play_custom_tts", "gpt-4o-mini-tts"),
    ],
)
def test_read_aloud_uses_selected_model(selection, method, model):
    instance = SimpleNamespace(
        custom_models={
            "local-voice": {"api_type": "tts"},
            "gpt-4o-mini-tts": {
                "api_type": "tts",
                "endpoint": "http://localhost/audio/speech",
            },
        }
    )
    instance.settings = Mock()
    instance.settings.get.return_value = selection
    for name in (
        "_synthesize_and_play_tts",
        "_synthesize_and_play_gemini_tts",
        "_synthesize_and_play_audio_preview",
        "_synthesize_and_play_custom_tts",
    ):
        setattr(instance, name, Mock(return_value=True))
    assert OpenAIGTKClient._synthesize_and_play_selected_tts(
        instance, "Hello", chat_id="chat"
    )
    expected = {"chat_id": "chat", "stop_event": None}
    if model:
        expected["model_id"] = model
    getattr(instance, method).assert_called_once_with("Hello", **expected)


def test_refresh_adds_speech_models_once_and_keeps_selection():
    if not Gtk.init_check([])[0]:
        pytest.skip("GTK display unavailable")
    combo = Gtk.ComboBoxText()
    combo.append("openai", "OpenAI TTS")
    combo.set_active_id("openai")
    settings = SimpleNamespace(custom_models={}, combo_tts_provider=combo)
    settings._get_tts_model_options = lambda: (
        dialogs.SettingsDialog._get_tts_model_options(settings)
    )
    try:
        speech = "gpt-4o-mini-tts-2026-11-01"
        register_discovered_models("openai", [speech])
        dialogs.SettingsDialog._refresh_tts_model_dropdown(settings)
        dialogs.SettingsDialog._refresh_tts_model_dropdown(settings)
        identifiers = [row[1] for row in combo.get_model()]
        assert identifiers.count(speech) == 1
        assert combo.get_active_id() == "openai"
    finally:
        combo.destroy()


def test_audio_page_opens_without_sounddevice(monkeypatch):
    if not Gtk.init_check([])[0]:
        pytest.skip("GTK display unavailable")
    # Force a fresh package import even when another test has loaded it.
    for name in list(sys.modules):
        if name == "realtime" or name.startswith("realtime."):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, "sounddevice", None)

    class AudioSettingsDialog(dialogs.SettingsDialog):
        def __init__(self):
            Gtk.Dialog.__init__(self)
            self.custom_models = {}
            self.microphone = "default"
            self.tts_hd = False
            self._audio_page_built = False
            self._read_aloud_signals_connected = False
            self.stack = Gtk.Stack()
            self.stack.add_named(Gtk.Label(label="Loading audio settings..."), "Audio")
            self.get_content_area().add(self.stack)

    settings = AudioSettingsDialog()
    try:
        row = SimpleNamespace(category_name="Audio")
        settings._on_sidebar_row_selected(None, row)
        page = settings.stack.get_child_by_name("Audio")
        assert isinstance(page, Gtk.ScrolledWindow)
        assert settings._audio_page_built
        assert settings.combo_mic.get_active_text() == "default"
        assert settings.combo_realtime.get_active_text() == "alloy"
        settings.combo_realtime_provider.set_active_id("grok")
        assert settings.combo_realtime.get_active_text() == "Ara"
        settings._on_sidebar_row_selected(None, row)
        assert settings.stack.get_child_by_name("Audio") is page
        assert "realtime.openai" not in sys.modules
        assert "realtime.xai" not in sys.modules
    finally:
        settings.destroy()
