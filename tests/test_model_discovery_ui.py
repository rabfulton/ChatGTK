"""Specialized model selectors must use discovered IDs and route selections."""

import sys
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import gi
import pytest

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
from requests import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import ChatGTK
import dialogs
import repositories
from ai_providers import ClaudeProvider
from ChatGTK import OpenAIGTKClient
from model_cards import loader, overrides
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


def feature_settings(**kwargs):
    settings = SimpleNamespace(custom_models={}, **kwargs)
    settings._get_feature_model_options = MethodType(
        dialogs.SettingsDialog._get_feature_model_options,
        settings,
    )
    return settings


def test_cached_special_models_return_to_feature_selectors_after_restart():
    image = "gpt-image-2"
    speech = "gpt-4o-mini-tts-2026-11-01"
    gemini = "gemini-3.5-flash-preview-tts"
    dialogs.save_model_cache({"openai": [image, speech], "gemini": [gemini]})
    loader._discovered_cards.clear()
    settings = feature_settings()
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
    assert model not in dialogs.SettingsDialog._get_all_image_models(feature_settings())


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
    settings = feature_settings(combo_tts_provider=combo)
    settings._get_tts_model_options = lambda: (
        dialogs.SettingsDialog._get_tts_model_options(settings)
    )
    try:
        speech = "gpt-4o-mini-tts-2026-11-01"
        dialogs.save_model_cache({"openai": [speech]})
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
        assert not hasattr(settings, "switch_hd")
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


def test_whitelist_groups_deprecated_models_and_preserves_selection_and_filter():
    if not Gtk.init_check([])[0]:
        pytest.skip("GTK display unavailable")

    class WhitelistSettingsDialog(dialogs.SettingsDialog):
        _PROVIDER_INFO = (
            ("OpenAI", "openai", "openai_model_whitelist", "OPENAI_API_KEY"),
            ("Grok", "grok", "grok_model_whitelist", "GROK_API_KEY"),
        )

        def __init__(self):
            Gtk.Dialog.__init__(self)
            self.custom_models = {}
            self.model_checkboxes = {}
            self.openai_model_whitelist = "gpt-5.2,tts-1"
            self.grok_model_whitelist = "grok-latest"
            self._whitelist_outer_box = Gtk.ListBox()
            self.get_content_area().add(self._whitelist_outer_box)
            self._provider_filter_combo = Gtk.ComboBoxText()
            self._provider_filter_combo.append("all", "All")
            self._provider_filter_combo.append("grok", "Grok")
            self._provider_filter_combo.set_active_id("all")
            self.get_content_area().add(self._provider_filter_combo)
            self._get_available_models_for_provider = lambda provider: {
                "openai": ["tts-1", "gpt-5.2", "gpt-realtime-mini", "gpt-5.4-nano"],
                "grok": ["grok-latest", "grok-3"],
            }[provider]
            self._get_display_name_for_model = lambda model: ""

    settings = WhitelistSettingsDialog()
    try:
        settings._populate_model_whitelist_sections()
        openai_group = settings._deprecated_expanders["openai"]
        assert openai_group.get_label() == "Deprecated (3)"
        assert not openai_group.get_expanded()
        legacy_list = openai_group.get_child()
        old_checkbox = settings.model_checkboxes["openai"]["tts-1"]
        assert old_checkbox.get_active()
        assert old_checkbox.get_sensitive()
        assert old_checkbox.get_parent().get_parent().get_parent() is legacy_list
        current_checkbox = settings.model_checkboxes["openai"]["gpt-5.2"]
        assert (
            current_checkbox.get_parent().get_parent().get_parent()
            is settings._whitelist_outer_box
        )
        assert "Shutdown: 2027-01-06" in old_checkbox.get_tooltip_text()
        assert "gpt-realtime-2.1-mini" in old_checkbox.get_tooltip_text()
        # Display-name entries must remain available for every provider.
        assert set(settings.model_display_entries) == {"openai", "grok"}

        old_checkbox.set_active(False)
        openai_group.set_expanded(True)
        settings.model_checkboxes["grok"]["grok-3"].set_active(True)
        settings._provider_filter_combo.set_active_id("grok")
        settings._populate_model_whitelist_sections(preserve_selections=True)
        assert settings._deprecated_expanders["openai"].get_expanded()
        assert not settings._deprecated_expanders["openai"].get_parent().get_visible()
        assert settings._deprecated_expanders["grok"].get_parent().get_visible()
        assert not settings.model_checkboxes["openai"]["tts-1"].get_active()
        assert settings.model_checkboxes["grok"]["grok-3"].get_active()
        assert settings.model_checkboxes["openai"]["gpt-5.2"].get_active()
    finally:
        settings.destroy()


@pytest.mark.parametrize(
    "selection, visible",
    [
        ("openai", False),
        ("tts-1", False),
        ("tts-1-hd", False),
        ("gemini", True),
        ("gemini-2.5-flash-preview-tts", True),
        ("gpt-audio-1.5", True),
        ("local-voice", False),
    ],
)
def test_speech_template_visibility_depends_on_the_adapter(selection, visible):
    settings = SimpleNamespace(
        custom_models={"local-voice": {"api_type": "tts"}},
        combo_tts_provider=Mock(get_active_id=Mock(return_value=selection)),
        row_prompt_template=Mock(),
    )
    dialogs.SettingsDialog._update_tts_option_visibility(settings)
    if visible:
        settings.row_prompt_template.show.assert_called_once()
        settings.row_prompt_template.hide.assert_not_called()
    else:
        settings.row_prompt_template.hide.assert_called_once()
        settings.row_prompt_template.show.assert_not_called()


@pytest.mark.parametrize("fail_mode", ["error", "fallback"])
def test_failed_refresh_keeps_last_known_availability(fail_mode):
    dialogs.save_model_cache({"openai": ["gpt-audio-1.5"]})
    provider = Mock()
    provider.model_listing_succeeded = fail_mode != "fallback"
    if fail_mode == "error":
        provider.get_available_models.side_effect = RuntimeError("offline")
    else:
        provider.get_available_models.return_value = ["dall-e-3"]
    settings = feature_settings(providers={"openai": provider})
    result = dialogs.SettingsDialog._get_available_models_for_provider(
        settings,
        "openai",
        force_refresh=True,
    )
    assert result == ["gpt-audio-1.5"]
    assert dialogs.load_model_cache()["openai"] == ["gpt-audio-1.5"]


def test_empty_discovery_removes_suggestions_without_restoring_catalog_defaults():
    provider = Mock(model_listing_succeeded=True)
    provider.get_available_models.return_value = []
    settings = feature_settings(providers={"openai": provider})
    assert (
        dialogs.SettingsDialog._get_available_models_for_provider(
            settings, "openai", True
        )
        == []
    )
    assert dialogs.load_model_cache()["openai"] == []
    assert settings._get_feature_model_options("tts") == {}


def test_missing_discovery_does_not_persist_fallback_as_availability():
    settings = feature_settings(providers={})
    assert dialogs.SettingsDialog._get_available_models_for_provider(
        settings, "openai", True
    )
    assert "openai" not in dialogs.load_model_cache()
    assert settings._get_feature_model_options("image") == {}


def test_refresh_removes_old_tts_choices_and_preserves_voice_and_current_model():
    if not Gtk.init_check([])[0]:
        pytest.skip("GTK display unavailable")
    combo = Gtk.ComboBoxText()
    combo.append("gemini-2.5-flash-preview-tts", "Gemini")
    combo.append("tts-1-hd", "Old unused model")
    combo.set_active_id("gemini-2.5-flash-preview-tts")
    settings = feature_settings(combo_tts_provider=combo)
    settings._get_tts_model_options = lambda: (
        dialogs.SettingsDialog._get_tts_model_options(settings)
    )
    changed = Mock()
    settings._tts_provider_changed_id = combo.connect("changed", changed)
    try:
        dialogs.save_model_cache({"openai": ["gpt-4o-mini-tts"]})
        dialogs.SettingsDialog._refresh_tts_model_dropdown(settings)
        choices = {row[1]: row[0] for row in combo.get_model()}
        assert "tts-1-hd" not in choices
        assert "gpt-4o-mini-tts" in choices
        assert "not in latest listing" in choices["gemini-2.5-flash-preview-tts"]
        assert combo.get_active_id() == "gemini-2.5-flash-preview-tts"
        changed.assert_not_called()
    finally:
        combo.destroy()


def test_startup_discovery_caches_inventory_before_conversation_whitelist(monkeypatch):
    monkeypatch.setattr(
        repositories, "ModelCacheRepository", dialogs.ModelCacheRepository
    )
    monkeypatch.setattr(
        ChatGTK,
        "threading",
        SimpleNamespace(
            Thread=lambda target, daemon: SimpleNamespace(start=target),
        ),
    )
    apply_results = Mock()
    monkeypatch.setattr(
        ChatGTK.GLib, "idle_add", lambda callback, *args: callback(*args)
    )
    provider = Mock(model_listing_succeeded=True)
    provider.get_available_models.return_value = [
        "gpt-5.2",
        "gpt-image-2",
        "gpt-transcribe",
    ]
    settings = Mock()
    settings.get.side_effect = lambda key, default=None: (
        "gpt-5.2" if key == "OPENAI_MODEL_WHITELIST" else default
    )
    client = SimpleNamespace(
        settings=settings,
        providers={"openai": provider},
        custom_models={},
        apply_model_fetch_results=apply_results,
    )
    monkeypatch.delenv("DISABLE_MODEL_FILTER", raising=False)
    OpenAIGTKClient.fetch_models_async(client)
    apply_results.assert_called_once_with(["gpt-5.2"], {"gpt-5.2": "openai"})
    assert set(dialogs.load_model_cache()["openai"]) == {
        "gpt-5.2",
        "gpt-image-2",
        "gpt-transcribe",
    }


def test_legacy_claude_cache_refreshes_all_pages_including_uncarded_models(monkeypatch):
    presets = dialogs.SETTINGS_CONFIG["CLAUDE_MODEL_WHITELIST"]["default"].split(",")
    dialogs.save_model_cache({"claude": presets})
    provider = ClaudeProvider()
    provider.client = SimpleNamespace(api_key="test-key")
    pages = []
    for body in (
        {"data": [{"id": "claude-future-opus"}], "has_more": True, "last_id": "first"},
        {"data": [{"id": "claude-future-sonnet"}], "has_more": False},
    ):
        page = Mock()
        page.json.return_value = body
        pages.append(page)
    get = Mock(side_effect=pages)
    monkeypatch.setattr("ai_providers.requests.get", get)
    settings = feature_settings(providers={"claude": provider})
    models = dialogs.SettingsDialog._get_available_models_for_provider(
        settings, "claude"
    )
    assert models == ["claude-future-opus", "claude-future-sonnet"]
    assert dialogs.get_card(models[0]) is None
    assert get.call_count == 2
    assert dialogs.load_model_cache()["claude"] == models
    assert "claude" not in settings._model_fetch_status


def test_failed_legacy_claude_refresh_reports_error_and_only_retries_when_requested(
    monkeypatch,
):
    presets = dialogs.SETTINGS_CONFIG["CLAUDE_MODEL_WHITELIST"]["default"].split(",")
    dialogs.save_model_cache({"claude": presets})
    provider = ClaudeProvider()
    provider.client = SimpleNamespace(api_key="test-key")
    response = Mock()
    response.raise_for_status.side_effect = HTTPError(
        response=SimpleNamespace(status_code=401)
    )
    get = Mock(return_value=response)
    monkeypatch.setattr("ai_providers.requests.get", get)
    settings = feature_settings(providers={"claude": provider})
    for _ in range(2):
        assert (
            dialogs.SettingsDialog._get_available_models_for_provider(
                settings, "claude"
            )
            == presets
        )
    assert get.call_count == 1
    assert "HTTP 401" in settings._model_fetch_status["claude"]
    assert "cached models" in settings._model_fetch_status["claude"]
    assert dialogs.load_model_cache()["claude"] == presets
    dialogs.SettingsDialog._get_available_models_for_provider(settings, "claude", True)
    assert get.call_count == 2


def test_uncarded_claude_models_are_selectable_and_status_is_visible():
    if not Gtk.init_check([])[0]:
        pytest.skip("GTK display unavailable")

    class ClaudeSettingsDialog(dialogs.SettingsDialog):
        _PROVIDER_INFO = (
            ("Claude", "claude", "claude_model_whitelist", "CLAUDE_API_KEY"),
        )

        def __init__(self):
            Gtk.Dialog.__init__(self)
            self.custom_models = {}
            self.model_checkboxes = {}
            self.claude_model_whitelist = "claude-future-opus"
            self._whitelist_outer_box = Gtk.ListBox()
            self.get_content_area().add(self._whitelist_outer_box)
            self._provider_filter_combo = Gtk.ComboBoxText()
            self._provider_filter_combo.append("all", "All")
            self._provider_filter_combo.set_active_id("all")
            self.get_content_area().add(self._provider_filter_combo)
            self._model_fetch_status = {
                "claude": "Discovery failed. Showing cached models."
            }
            self._get_available_models_for_provider = lambda provider: [
                "claude-future-opus",
                "claude-future-sonnet",
            ]
            self._get_display_name_for_model = lambda model: ""

    settings = ClaudeSettingsDialog()
    try:
        settings._populate_model_whitelist_sections()
        assert set(settings.model_checkboxes["claude"]) == {
            "claude-future-opus",
            "claude-future-sonnet",
        }
        assert settings.model_checkboxes["claude"]["claude-future-opus"].get_active()
        checkbox = settings.model_checkboxes["claude"]["claude-future-sonnet"]
        assert checkbox.get_sensitive()
        checkbox.set_active(True)
        status_labels = [
            row.get_child()
            for row in settings._model_widgets_by_provider["claude"]
            if isinstance(row.get_child(), Gtk.Label)
        ]
        assert any("Discovery failed" in label.get_text() for label in status_labels)
        settings._populate_model_whitelist_sections(preserve_selections=True)
        assert settings.model_checkboxes["claude"]["claude-future-sonnet"].get_active()
    finally:
        settings.destroy()
