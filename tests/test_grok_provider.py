"""Exercise xAI discovery and Responses using the real SDK with mocked HTTP."""

import json
import importlib.util
from pathlib import Path
import sys
from unittest.mock import Mock

import httpx
from openai import OpenAI
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_providers import GrokProvider
from config import SETTINGS_CONFIG
from model_cards import get_card, loader, overrides
from model_cards.grok import (
    GROK_DEFAULT_MODELS,
    GROK_RETIRED_MODELS,
    LEGACY_GROK_MODEL_WHITELIST,
)
from repositories import SettingsRepository


@pytest.fixture
def make_provider(monkeypatch):
    monkeypatch.setattr(overrides, "load_overrides", lambda: {})
    monkeypatch.setattr(loader, "_custom_cards", {})
    clients = []

    def make(handler):
        provider = GrokProvider()
        provider.client = OpenAI(
            api_key="test-key",
            base_url=provider.BASE_URL,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
            max_retries=0,
        )
        clients.append(provider.client)
        return provider

    yield make
    for client in clients:
        client.close()


def response_body(output, model="grok-latest"):
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "model": model,
        "status": "completed",
        "output": output,
    }


def message_output(text):
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


@pytest.mark.parametrize("disable_filter", [False, True])
def test_discovery_keeps_new_models_and_language_aliases(make_provider, disable_filter):
    def handle(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"object": "list", "data": [
                {"id": "grok-4.7", "object": "model", "created": 1},
                {"id": "grok-4.8", "object": "model", "created": 1},
                {"id": "grok-imagine-image-2.0", "object": "model", "created": 1},
                {"id": "grok-imagine-video-1.5", "object": "model", "created": 1},
            ]})
        assert request.url.path == "/v1/language-models"
        return httpx.Response(200, json={"models": [
            {"id": "grok-4.7", "aliases": ["grok-latest", "grok-4.7-latest"]},
        ]})

    provider = make_provider(handle)
    assert provider.get_available_models(disable_filter=disable_filter) == [
        "grok-4.7", "grok-4.7-latest", "grok-4.8",
        "grok-imagine-image-2.0", "grok-latest", "grok-realtime",
    ]
    alias_card = get_card("grok-4.7-latest")
    assert alias_card.capabilities.web_search is True
    assert alias_card.quirks["alias_of"] == "grok-4.7"


@pytest.mark.parametrize("model_payload", [
    {"object": "list", "data": []},
    {"models": []},
    None,
])
def test_language_metadata_recovers_empty_or_failed_listing(make_provider, model_payload):
    def handle(request):
        if request.url.path == "/v1/models":
            if model_payload is None:
                return httpx.Response(503, json={"error": {"message": "Unavailable"}})
            return httpx.Response(200, json=model_payload)
        return httpx.Response(200, json={"models": [
            {"id": "grok-4.7", "aliases": ["grok-latest"]},
        ]})

    assert make_provider(handle).get_available_models() == [
        "grok-4.7", "grok-latest", "grok-realtime",
    ]


@pytest.mark.parametrize("status", [200, 503])
def test_discovery_fallback_uses_current_defaults(make_provider, status):
    def handle(request):
        return httpx.Response(status, json={"object": "list", "data": [], "models": []})

    models = make_provider(handle).get_available_models()
    assert models == sorted(GROK_DEFAULT_MODELS)
    assert "grok-latest" in models
    assert not set(models) & set(GROK_RETIRED_MODELS)
    assert not any(model.startswith("grok-2") for model in models)


def test_listing_survives_unavailable_alias_endpoint(make_provider):
    def handle(request):
        if request.url.path == "/v1/language-models":
            return httpx.Response(404, json={"error": {"message": "Not available"}})
        return httpx.Response(200, json={"object": "list", "data": [
            {"id": "grok-4.7", "aliases": ["grok-latest"], "created": 1},
            {"id": "grok-4.7", "created": 1},
        ]})

    assert make_provider(handle).get_available_models() == [
        "grok-4.7", "grok-latest", "grok-realtime",
    ]


@pytest.mark.parametrize("search_enabled", [False, True])
def test_modern_chat_uses_responses_and_optional_search(make_provider, search_enabled):
    requests = []

    def handle(request):
        assert request.url.path == "/v1/responses"
        payload = json.loads(request.content)
        requests.append(payload)
        # xAI rejects a tool_choice even when it is "none" if no tools exist.
        if "tool_choice" in payload and not payload.get("tools"):
            return httpx.Response(400, json={"error": {
                "message": "A tool_choice was set on the request but no tools were specified.",
            }})
        return httpx.Response(200, json=response_body([message_output("Hello!")]))

    provider = make_provider(handle)
    answer = provider.generate_chat_completion(
        [{"role": "system", "content": "Be helpful."},
         {"role": "user", "content": "Hello"}],
        "grok-latest", web_search_enabled=search_enabled, max_tokens=128,
    )

    assert answer == "Hello!"
    assert len(requests) == 1
    payload = requests[0]
    assert payload["model"] == "grok-latest"
    assert payload["instructions"] == "Be helpful."
    assert payload["max_output_tokens"] == 128
    assert payload["input"][0]["content"] == [{"type": "input_text", "text": "Hello"}]
    assert payload.get("tools", []) == (
        [{"type": "web_search"}, {"type": "x_search"}] if search_enabled else []
    )
    if search_enabled:
        assert payload["tool_choice"] == "auto"
    else:
        assert "tools" not in payload
        assert "tool_choice" not in payload


def test_turning_search_off_clears_opaque_state_and_reports_only_new_searches(make_provider):
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        output = [message_output("Answer using the earlier results.")]
        if len(requests) == 1:
            output = [
                {"id": "rs_search", "type": "reasoning", "summary": [],
                 "encrypted_content": "old-search-state"},
                {"id": "ws_search", "type": "web_search_call", "status": "completed",
                 "action": {"type": "search", "query": "Project documentation"}},
                message_output("Earlier search results."),
            ]
        return httpx.Response(200, json=response_body(output))

    provider = make_provider(handle)
    first_meta = {}
    first_answer = provider.generate_chat_completion(
        [{"role": "user", "content": "Search for project documentation."}],
        "grok-latest", web_search_enabled=True, response_meta=first_meta,
    )
    assert first_meta["grok"]["search_calls"] == {"web": 1, "x": 0}
    assert first_meta["grok"]["web_search_enabled"] is True

    second_meta = {}
    provider.generate_chat_completion(
        [{"role": "user", "content": "Search for project documentation."},
         {"role": "assistant", "content": first_answer, "provider_meta": first_meta},
         {"role": "user", "content": "Now answer without searching."}],
        "grok-latest", web_search_enabled=False, response_meta=second_meta,
    )

    assert "tools" not in requests[1]
    assert "tool_choice" not in requests[1]
    assert all(item["type"] == "message" for item in requests[1]["input"])
    assert requests[1]["input"][1]["content"] == "Earlier search results."
    assert second_meta["grok"]["search_calls"] == {"web": 0, "x": 0}
    assert second_meta["grok"]["web_search_enabled"] is False


def test_tool_rounds_and_next_turn_keep_encrypted_reasoning(make_provider):
    requests = []
    reasoning = {"id": "rs_test", "type": "reasoning", "summary": [],
                 "encrypted_content": "opaque-reasoning"}
    function_call = {
        "id": "fc_test", "type": "function_call", "call_id": "call_test",
        "name": "text_get", "arguments": '{"target":"file"}',
    }

    def handle(request):
        payload = json.loads(request.content)
        assert request.url.path == "/v1/responses"
        requests.append(payload)
        output = ([reasoning, function_call] if len(requests) == 1
                  else [message_output("Done.")])
        return httpx.Response(200, json=response_body(output))

    provider = make_provider(handle)
    handler = Mock(return_value="File contents")
    meta = {}
    answer = provider.generate_chat_completion(
        [{"role": "user", "content": "Read the file."}],
        "grok-latest", text_get_handler=handler, response_meta=meta,
    )

    handler.assert_called_once_with("file")
    assert answer.startswith("Done.")
    second_input = requests[1]["input"]
    assert [item["type"] for item in second_input] == [
        "message", "reasoning", "function_call", "function_call_output",
    ]
    assert second_input[1]["encrypted_content"] == "opaque-reasoning"
    assert second_input[-1]["call_id"] == "call_test"
    assert second_input[-1]["output"] == "File contents"
    # Metadata must be JSON-serializable for saving conversations.
    json.dumps(meta)

    provider.generate_chat_completion(
        [{"role": "user", "content": "Read the file."},
         {"role": "assistant", "content": answer, "provider_meta": meta},
         {"role": "user", "content": "What next?"}],
        "grok-latest",
    )
    assert requests[2]["input"][1]["encrypted_content"] == "opaque-reasoning"
    assert [item["type"] for item in requests[2]["input"]].count("function_call") == 1


def test_reasoning_is_not_reused_after_switching_models(make_provider):
    provider = make_provider(lambda request: httpx.Response(500))
    messages = [{"role": "assistant", "content": "Earlier answer", "provider_meta": {
        "grok": {"model": "grok-4.3", "response_output": [
            {"type": "reasoning", "encrypted_content": "old-reasoning"},
        ]},
    }}]
    items, _ = provider._build_responses_input(messages, "grok-4.7")
    assert items == [{"type": "message", "role": "assistant", "content": "Earlier answer"}]


def test_legacy_mini_uses_chat_without_search(make_provider):
    def handle(request):
        assert request.url.path == "/v1/chat/completions"
        assert "tools" not in json.loads(request.content)
        return httpx.Response(200, json={
            "id": "chat_test", "object": "chat.completion", "created": 1,
            "model": "grok-3-mini", "choices": [{"index": 0,
                "message": {"role": "assistant", "content": "Hello!"},
                "finish_reason": "stop"}],
        })

    provider = make_provider(handle)
    assert provider.generate_chat_completion(
        [{"role": "user", "content": "Hello"}],
        "grok-3-mini", web_search_enabled=True,
    ) == "Hello!"


def test_multi_agent_omits_unsupported_function_tools_and_token_limit(make_provider):
    def handle(request):
        payload = json.loads(request.content)
        assert request.url.path == "/v1/responses"
        assert payload["tools"] == [{"type": "web_search"}, {"type": "x_search"}]
        assert "max_output_tokens" not in payload
        return httpx.Response(200, json=response_body([message_output("Research done.")]))

    handler = Mock()
    answer = make_provider(handle).generate_chat_completion(
        [{"role": "user", "content": "Research this."}],
        "grok-4.20-multi-agent-0309", max_tokens=128,
        web_search_enabled=True, text_get_handler=handler,
    )
    assert answer == "Research done."
    handler.assert_not_called()


def test_current_defaults_have_cards_and_retired_cards_are_labelled():
    for model in GROK_DEFAULT_MODELS:
        card = get_card(model)
        assert card is not None
        assert card.provider == "grok"
        assert not card.quirks.get("deprecated")
    for model, replacement in GROK_RETIRED_MODELS.items():
        card = get_card(model)
        assert card.quirks["deprecated"] is True
        assert card.quirks["replacement_model"] == replacement
        assert "retired" in card.display_name


def test_new_grok_cards_use_conservative_capabilities():
    card = get_card("grok-4.8")
    assert card.provider == "grok"
    assert card.api_family == "responses"
    assert card.capabilities.text is True
    assert card.capabilities.web_search is False
    assert card.capabilities.tool_use is False
    assert card.capabilities.vision is False


@pytest.mark.parametrize("check_toggle, fail_off", [
    (False, False), (True, False), (True, True),
])
def test_live_check_reports_alias_and_search_toggle_results(
    make_provider, monkeypatch, capsys, check_toggle, fail_off,
):
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "check_grok.py"
    spec = importlib.util.spec_from_file_location("check_grok", script_path)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)

    def handle(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"object": "list", "data": [
                {"id": "grok-4.7", "created": 1},
                {"id": "grok-imagine-video-1.5", "created": 1},
            ]})
        if request.url.path == "/v1/language-models":
            return httpx.Response(200, json={"models": [
                {"id": "grok-4.7", "aliases": ["grok-latest"]},
            ]})
        if request.url.path == "/v1/models/grok-latest":
            return httpx.Response(404, json={"error": {"message": "Not found"}})
        assert request.url.path == "/v1/responses"
        payload = json.loads(request.content)
        assert payload["model"] == "grok-latest"
        if not payload.get("tools"):
            assert "tools" not in payload
            assert "tool_choice" not in payload
            if fail_off:
                return httpx.Response(400, json={"error": {"message": (
                    "Invalid input message; key=test-secret-must-not-be-printed"
                )}})
            return httpx.Response(200, json=response_body([
                message_output("Search is off on this turn."),
            ]))
        return httpx.Response(200, json=response_body([
            {"id": "ws_test", "type": "web_search_call", "status": "completed",
             "action": {"type": "search", "query": "xAI documentation"}},
            message_output("https://docs.x.ai/developers/models"),
        ]))

    provider = make_provider(handle)
    monkeypatch.setattr(script, "GrokProvider", lambda: provider)
    monkeypatch.setattr(provider, "initialize", lambda key: None)
    monkeypatch.setenv("XAI_API_KEY", " test-secret-must-not-be-printed ")
    flag = "--check-search-toggle" if check_toggle else "--search"
    monkeypatch.setattr(sys, "argv", [str(script_path), flag])

    assert script.main() == (1 if fail_off else 0)
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    if fail_off:
        assert len(report["errors"]) == 1
        error = report["errors"][0]
        assert "Search-disabled request failed" in error
        assert "HTTP 400" in error
        assert "Invalid input message" in error
        assert "[REDACTED]" in error
    else:
        assert report["errors"] == []
    assert len(report["warnings"]) == 1
    assert "aliases may still work" in report["warnings"][0]
    assert "web_search_call" in report["search_output_types"]
    assert report["api_language_aliases"] == ["grok-latest"]
    assert report["unsupported_api_models"] == ["grok-imagine-video-1.5"]
    assert report["advertised_without_card"] == []
    assert "test-secret-must-not-be-printed" not in captured.out + captured.err
    if check_toggle and not fail_off:
        assert report["search_disabled_calls"] == {"web": 0, "x": 0}


@pytest.mark.parametrize("configured, migrated", [
    (LEGACY_GROK_MODEL_WHITELIST, True),
    (", ".join(reversed(LEGACY_GROK_MODEL_WHITELIST.split(","))), True),
    ("grok-3", False),
    ("grok-latest,grok-4.7", False),
    ("", False),
])
def test_old_default_whitelist_migrates_without_replacing_custom_choices(
    tmp_path, configured, migrated,
):
    path = tmp_path / "settings.cfg"
    path.write_text(f"GROK_MODEL_WHITELIST={configured}\n")
    repo = SettingsRepository(settings_file=str(path))
    expected = (SETTINGS_CONFIG["GROK_MODEL_WHITELIST"]["default"]
                if migrated else configured)
    assert repo.get("GROK_MODEL_WHITELIST") == expected
    # Loading/migrating settings must not overwrite the file by itself.
    assert path.read_text() == f"GROK_MODEL_WHITELIST={configured}\n"
