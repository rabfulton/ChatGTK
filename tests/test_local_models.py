"""Local servers use saved custom models and the OpenAI-compatible provider."""

import os
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import utils
from ai_providers import CustomProvider
from config import LOCAL_SERVER_PRESETS
from model_cards import get_card
from model_cards import loader, overrides
from tools import ToolManager


@pytest.fixture(autouse=True)
def isolate_model_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(utils, "CUSTOM_MODELS_FILE", str(tmp_path / "models.json"))
    monkeypatch.setattr(overrides, "load_overrides", lambda: {})
    monkeypatch.setattr(loader, "_custom_cards", {})


@pytest.mark.parametrize("preset_id", ["ollama", "lmstudio", "text-gen-webui"])
def test_saved_local_model_sends_openai_compatible_chat(preset_id, monkeypatch):
    preset = LOCAL_SERVER_PRESETS[preset_id]
    model_id = "local-test-model"
    server_model = "llama3.2:3b"
    endpoint = preset["base_url"] + preset["chat_endpoint"]
    models = {
        model_id: {
            "model_id": server_model,
            "endpoint": endpoint,
            "api_key": "",
            "api_type": "chat.completions",
            "display_name": f"{preset['display_name']}: Llama 3.2 3B",
        },
    }
    utils.save_custom_models(models)
    saved = utils.load_custom_models()
    assert saved == models

    card = get_card(model_id, saved)
    assert card.provider == "custom"
    assert card.api_family == "chat.completions"
    assert card.base_url == endpoint
    assert card.display_name == models[model_id]["display_name"]
    assert ToolManager().get_provider_name_for_model(
        model_id, custom_models=saved
    ) == "custom"

    provider = CustomProvider()
    config = saved[model_id]
    provider.initialize(
        api_key=config["api_key"],
        endpoint=config["endpoint"],
        model_id=config["model_id"],
        api_type=config["api_type"],
    )
    response = Mock()
    response.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "Hello!"}}],
    }
    post = Mock(return_value=response)
    monkeypatch.setattr(provider.session, "post", post)

    messages = [
        {"role": "system", "content": "Be helpful."},
        {
            "role": "user",
            "content": "Hello",
            "provider_meta": {"internal": True},
            "model": model_id,
        },
    ]
    result = provider.generate_chat_completion(messages, model=None)

    assert result == "Hello!"
    post.assert_called_once_with(
        endpoint,
        headers={"Content-Type": "application/json"},
        json={
            "model": server_model,
            "messages": [
                {"role": "system", "content": "Be helpful."},
                {"role": "user", "content": "Hello"},
            ],
        },
        timeout=60,
    )
    response.raise_for_status.assert_called_once()
    assert messages[1]["provider_meta"] == {"internal": True}


@pytest.mark.parametrize("api_type, capability", [
    ("chat.completions", "text"),
    ("audio.transcriptions", "audio_in"),
    ("tts", "audio_out"),
])
def test_local_model_cards_keep_cloud_features_disabled(api_type, capability):
    model_id = "local-test-model"
    card = get_card(model_id, {
        model_id: {
            "api_type": api_type,
            "endpoint": "http://localhost:8080/v1",
        },
    })

    assert card.provider == "custom"
    assert getattr(card.capabilities, capability) is True
    assert card.capabilities.web_search is False
    assert card.capabilities.files is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
