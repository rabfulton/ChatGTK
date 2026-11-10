"""Feature choices require discovery, capability support and correct transport."""

import io
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_providers import OpenAIProvider
from model_cards import loader, overrides, register_discovered_models
from model_cards.selection import get_feature_models
from repositories import SettingsRepository


@pytest.fixture(autouse=True)
def isolate_cards(monkeypatch):
    monkeypatch.setattr(loader, "_custom_cards", {})
    monkeypatch.setattr(loader, "_discovered_cards", {})
    monkeypatch.setattr(overrides, "load_overrides", dict)


def test_available_features_exclude_old_cards_and_unsupported_workflows():
    discovered = {
        "openai": [
            "gpt-image-2",
            "gpt-audio-1.5",
            "gpt-4o-mini-tts",
            "gpt-transcribe",
            "gpt-4o-mini-transcribe-2025-12-15",
            "gpt-live-transcribe",
            "gpt-realtime-2.1-mini",
            "gpt-5.2",
        ]
    }
    assert set(get_feature_models(discovered, {}, "image")) == {"gpt-image-2"}
    assert set(get_feature_models(discovered, {}, "tts")) == {
        "gpt-audio-1.5",
        "gpt-4o-mini-tts",
    }
    assert set(get_feature_models(discovered, {}, "stt")) == {
        "gpt-transcribe",
        "gpt-4o-mini-transcribe-2025-12-15",
    }
    # Registered cards from a previous discovery cannot bypass availability.
    register_discovered_models("openai", ["gpt-image-1.5", "gpt-audio-1.0"])
    assert set(get_feature_models(discovered, {}, "image")) == {"gpt-image-2"}
    assert not get_feature_models({"gemini": ["gpt-image-2"]}, {}, "image")


@pytest.mark.parametrize(
    "feature, api_type",
    [
        ("image", "images"),
        ("tts", "tts"),
        ("stt", "stt"),
        ("stt", "audio.transcriptions"),
    ],
)
def test_custom_endpoints_remain_available_without_remote_discovery(feature, api_type):
    models = {"local": {"api_type": api_type, "display_name": "My local model"}}
    assert get_feature_models({}, models, feature) == {"local": "My local model"}
    assert not get_feature_models({}, {}, feature)
    assert not get_feature_models({"openai": []}, {}, feature)


@pytest.mark.parametrize(
    "old_settings, expected",
    [
        ("TTS_VOICE_PROVIDER=openai\nTTS_HD=true\n", "tts-1-hd"),
        ("TTS_VOICE_PROVIDER=openai\nTTS_HD=false\n", "tts-1"),
        ("TTS_HD=true\n", "tts-1-hd"),
        ("READ_ALOUD_PROVIDER=tts\nTTS_HD=true\n", "tts-1-hd"),
        ("TTS_VOICE_PROVIDER=gemini\nTTS_HD=true\n", "gemini-2.5-flash-preview-tts"),
        ("TTS_VOICE_PROVIDER=gpt-4o-mini-tts\nTTS_HD=true\n", "gpt-4o-mini-tts"),
        ("TTS_VOICE_PROVIDER=private-voice\nTTS_HD=true\n", "private-voice"),
    ],
)
def test_legacy_hd_migrates_to_explicit_model_and_is_removed_on_save(
    tmp_path, old_settings, expected
):
    path = tmp_path / "settings.cfg"
    path.write_text(old_settings)
    repo = SettingsRepository(str(path))
    assert repo.get("TTS_VOICE_PROVIDER") == expected
    assert "TTS_HD" not in repo.get_all()
    repo.save()
    assert "TTS_HD=" not in path.read_text()
    assert SettingsRepository(str(path)).get("TTS_VOICE_PROVIDER") == expected


@pytest.mark.parametrize(
    "model",
    [
        "gpt-transcribe",
        "gpt-4o-mini-transcribe-2025-12-15",
        "gpt-4o-transcribe-diarize",
    ],
)
def test_file_transcription_models_use_transcription_endpoint(model):
    provider = OpenAIProvider()
    provider.client = Mock()
    provider.client.audio.transcriptions.create.return_value.text = "Hello"
    assert provider.transcribe_audio(io.BytesIO(b"wav data"), model=model) == "Hello"
    params = provider.client.audio.transcriptions.create.call_args.kwargs
    assert params["model"] == model
    assert ("chunking_strategy" in params) == ("diarize" in model)
    provider.client.chat.completions.create.assert_not_called()
