"""Discovery must preserve specialized routing and account model listings."""

import base64
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_providers import ClaudeProvider, GeminiProvider, OpenAIProvider
from model_cards import (
    get_card,
    list_cards,
    loader,
    overrides,
    register_discovered_models,
)
from services.audio_service import AudioService
from services.streaming_service import can_stream
from tools import ToolManager


@pytest.fixture(autouse=True)
def isolate_cards(monkeypatch):
    monkeypatch.setattr(loader, "_discovered_cards", {})
    monkeypatch.setattr(loader, "_custom_cards", {})
    monkeypatch.setattr(overrides, "load_overrides", dict)


@pytest.mark.parametrize(
    "model, provider, family, quirk",
    [
        ("gpt-realtime-2.1-mini", "openai", "realtime", "realtime_websocket"),
        ("gpt-realtime-mini-2026-11-01", "openai", "realtime", "realtime_websocket"),
        ("gpt-4o-mini-tts-2026-11-01", "openai", "tts", None),
        ("tts-1-hd-2026-11-01", "openai", "tts", None),
        ("gpt-audio-1.5", "openai", "chat.completions", "requires_audio_modality"),
        ("gpt-image-2", "openai", "images", None),
        ("chatgpt-image-latest", "openai", "images", None),
        ("gemini-3.5-flash-preview-tts", "gemini", "tts", None),
        (
            "gemini-3.5-pro-image-preview",
            "gemini",
            "generateContent",
            "multimodal_image_gen",
        ),
    ],
)
def test_new_special_models_keep_routing(model, provider, family, quirk):
    register_discovered_models(provider, [model])
    card = get_card(model)
    assert card.provider == provider
    assert card.api_family == family
    assert model in list_cards()
    if quirk:
        assert card.quirks[quirk]
    assert not card.supports_tools()
    if family == "realtime":
        assert card.is_realtime_model()
    if family != "generateContent":
        instance = OpenAIProvider() if provider == "openai" else GeminiProvider()
        assert not can_stream(instance, provider, model)
    if family == "images" or quirk == "multimodal_image_gen":
        assert ToolManager().is_image_model_for_provider(model, provider)


@pytest.mark.parametrize(
    "model",
    [
        "my-image-model",
        "my-tts-model",
        "gpt-realtime-translate",
        "gpt-realtime-whisper",
        "openai/gpt-image-2",
        "gpt-99-tts",
    ],
)
def test_unrelated_names_do_not_acquire_special_routes(model):
    register_discovered_models("openai", [model])
    assert get_card(model) is None


def test_discovery_does_not_override_custom_configuration_or_user_overrides(
    monkeypatch,
):
    model = "gpt-4o-mini-tts-2026-11-01"
    register_discovered_models("gemini", [model])
    assert model not in list_cards()
    register_discovered_models("openai", [model])
    custom = {model: {"api_type": "images", "endpoint": "http://localhost/images"}}
    assert get_card(model, custom).provider == "custom"
    assert get_card(model, custom).api_family == "images"
    monkeypatch.setattr(
        overrides,
        "load_overrides",
        lambda: {
            model: {"capabilities": {"audio_out": False}, "display_name": "My voice"},
        },
    )
    assert not get_card(model).capabilities.audio_out
    assert get_card(model).display_name == "My voice"


def test_openai_discovery_registers_special_models_without_losing_generator_entries():
    models = ["gpt-image-2", "gpt-4o-mini-tts-2026-11-01", "gpt-realtime-2.1-mini"]
    provider = OpenAIProvider()
    provider.client = Mock()
    provider.client.models.list.return_value = (SimpleNamespace(id=m) for m in models)
    assert provider.get_available_models(disable_filter=True) == sorted(models)
    assert set(models) <= list_cards().keys()


def json_response(data):
    response = Mock()
    response.json.return_value = data
    return response


@pytest.mark.parametrize("disable_filter", [False, True])
def test_claude_refresh_uses_native_auth_and_all_pages(monkeypatch, disable_filter):
    provider = ClaudeProvider()
    provider.client = SimpleNamespace(api_key="test-key")
    get = Mock(
        side_effect=[
            json_response(
                {
                    "data": [{"id": "claude-future-sonnet"}],
                    "has_more": True,
                    "last_id": "first",
                }
            ),
            json_response({"data": [{"id": "claude-future-opus"}], "has_more": False}),
        ]
    )
    monkeypatch.setattr("ai_providers.requests.get", get)
    assert provider.get_available_models(disable_filter) == [
        "claude-future-opus",
        "claude-future-sonnet",
    ]
    first, second = get.call_args_list
    assert first.args == ("https://api.anthropic.com/v1/models",)
    assert first.kwargs["headers"] == {
        "x-api-key": "test-key",
        "anthropic-version": "2023-06-01",
    }
    assert first.kwargs["params"] == {"limit": 100}
    assert second.kwargs["params"] == {"limit": 100, "after_id": "first"}
    assert first.kwargs["timeout"] == 30


def test_claude_failed_discovery_retains_partial_results_and_does_not_loop(monkeypatch):
    provider = ClaudeProvider()
    provider.client = SimpleNamespace(api_key="test-key")
    get = Mock(
        return_value=json_response(
            {
                "data": [{"id": "claude-future-sonnet"}],
                "has_more": True,
                "last_id": "same",
            }
        )
    )
    monkeypatch.setattr("ai_providers.requests.get", get)
    assert provider.get_available_models() == ["claude-future-sonnet"]
    assert get.call_count == 2


def test_claude_discovery_fallback_remains_available(monkeypatch):
    provider = ClaudeProvider()
    provider.client = SimpleNamespace(api_key="test-key")
    monkeypatch.setattr(
        "ai_providers.requests.get", Mock(side_effect=RuntimeError("Offline"))
    )
    assert "claude-sonnet-4-5" in provider.get_available_models()


def test_gemini_discovery_registers_special_models_on_later_pages(monkeypatch):
    provider = GeminiProvider()
    provider.initialize("test-key")
    models = ["gemini-3.5-flash-preview-tts", "gemini-3.5-pro-image-preview"]
    get = Mock(
        side_effect=[
            json_response(
                {
                    "models": [
                        {
                            "name": "models/gemini-chat",
                            "supportedGenerationMethods": ["generateContent"],
                        }
                    ],
                    "nextPageToken": "next",
                }
            ),
            json_response(
                {
                    "models": [
                        {
                            "name": f"models/{m}",
                            "supportedGenerationMethods": ["generateContent"],
                        }
                        for m in models
                    ]
                }
            ),
        ]
    )
    monkeypatch.setattr("ai_providers.requests.get", get)
    assert provider.get_available_models(True) == sorted(["gemini-chat", *models])
    assert get.call_args_list[1].kwargs["params"]["pageToken"] == "next"
    assert set(models) <= list_cards().keys()


def test_gemini_speech_passes_selected_model_to_native_endpoint(monkeypatch):
    provider = GeminiProvider()
    provider.initialize("test-key")
    response = json_response(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "inlineData": {
                                    "mimeType": "audio/L16;rate=24000",
                                    "data": base64.b64encode(b"\0\0").decode(),
                                }
                            }
                        ]
                    }
                }
            ]
        }
    )
    post = Mock(return_value=response)
    monkeypatch.setattr("ai_providers.requests.post", post)
    model = "gemini-3.5-flash-preview-tts"
    assert provider.generate_speech("Hello", "Kore", model=model).startswith(b"RIFF")
    assert post.call_args.args[0].endswith(f"/{model}:generateContent")


def test_speech_cache_is_separate_for_each_selected_gemini_model(tmp_path, monkeypatch):
    monkeypatch.setattr("services.audio_service.HISTORY_DIR", tmp_path)
    service = AudioService()
    provider = Mock()
    provider.generate_speech.side_effect = [b"first audio", b"second audio"]
    first = service.synthesize_gemini_tts(
        "Hello", provider, chat_id="chat", model="gemini-3-flash-tts"
    )
    second = service.synthesize_gemini_tts(
        "Hello", provider, chat_id="chat", model="gemini-3-pro-tts"
    )
    assert first != second
    assert first.read_bytes() == b"first audio"
    assert second.read_bytes() == b"second audio"
    assert (
        service.synthesize_gemini_tts(
            "Hello", provider, chat_id="chat", model="gemini-3-flash-tts"
        )
        == first
    )
    assert provider.generate_speech.call_count == 2


def test_selected_speech_model_reaches_openai_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr("services.audio_service.HISTORY_DIR", tmp_path)
    service = AudioService()
    provider = Mock()
    provider.audio.speech.with_streaming_response.create.return_value.__enter__ = Mock(
        return_value=SimpleNamespace(iter_bytes=lambda: iter([b"audio"]))
    )
    provider.audio.speech.with_streaming_response.create.return_value.__exit__ = Mock(
        return_value=False
    )
    model = "gpt-4o-mini-tts-2026-11-01"
    path = service.synthesize_openai_tts("Hello", provider, model=model, chat_id="chat")
    assert path.read_bytes() == b"audio"
    assert (
        provider.audio.speech.with_streaming_response.create.call_args.kwargs["model"]
        == model
    )
