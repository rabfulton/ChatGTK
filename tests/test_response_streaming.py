"""Provider streams must preserve answers, reasoning and tool protocol state."""

import json
import sys
import threading
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
import requests
from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_providers import CustomProvider, GeminiProvider, GrokProvider, OpenAIProvider
from model_cards import get_card, loader, overrides
from services.response_stream import (
    StreamCancelled,
    ThinkParser,
    iter_sse,
    managed_stream,
    read_chat_chunks,
    read_response_events,
)
from services.streaming_service import can_stream, stream_chat_completion


@pytest.fixture(autouse=True)
def isolate_cards(monkeypatch):
    monkeypatch.setattr(overrides, "load_overrides", dict)
    monkeypatch.setattr(loader, "_custom_cards", {})


def frame(data):
    return "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"


def http_stream(events):
    response = requests.Response()
    response.status_code = 200
    response.headers["Content-Type"] = "text/event-stream"
    response._content = (
        "".join(frame(event) for event in events) + "data: [DONE]\n\n"
    ).encode()
    response._content_consumed = True
    response.close = Mock(wraps=response.close)
    return response


def chat_chunk(content=None, finish=None, **delta):
    if content is not None:
        delta["content"] = content
    return {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


def message_output(text):
    return {
        "type": "message",
        "id": "msg",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def response_events(output, text="Answer", reasoning="Consider the options"):
    events = []
    if reasoning:
        events.append(
            {
                "type": "response.reasoning_summary_text.delta",
                "delta": reasoning,
                "item_id": "rs",
                "output_index": 0,
                "summary_index": 0,
                "sequence_number": 1,
            }
        )
    if text:
        events.append(
            {
                "type": "response.output_text.delta",
                "delta": text,
                "item_id": "msg",
                "output_index": 1,
                "content_index": 0,
                "sequence_number": 2,
            }
        )
    events.append(
        {
            "type": "response.completed",
            "sequence_number": 3,
            "response": {
                "id": "resp",
                "object": "response",
                "created_at": 1,
                "model": "test",
                "status": "completed",
                "output": output,
            },
        }
    )
    return events


@pytest.mark.parametrize("width", range(1, 13))
def test_think_tags_split_at_every_boundary(width):
    values = {"text": "", "reasoning": ""}
    parser = ThinkParser(
        lambda kind, text: values.__setitem__(kind, values[kind] + text)
    )
    source = (
        " \n<think>考える🙂</think>\n<think>Again</think>Answer with `<think>` example"
    )
    for index in range(0, len(source), width):
        parser.feed(source[index : index + width])
    parser.finish()
    assert values == {
        "text": "Answer with `<think>` example",
        "reasoning": "考える🙂Again",
    }


def test_unclosed_thinking_is_kept_out_of_the_answer():
    events = []
    message = read_chat_chunks(
        [
            chat_chunk("<think>Still thinking"),
            chat_chunk(finish="stop"),
        ],
        lambda *args: events.append(args),
        lambda: False,
    )
    assert message["content"] == ""
    assert message["reasoning_content"] == "Still thinking"


def test_sse_comments_multiline_and_unicode():
    response = Mock()
    response.iter_lines.return_value = [
        b": keepalive",
        b"event: chunk",
        b'data: {"text":',
        'data: "🙂"}'.encode(),
        b"",
        b"data: [DONE]",
        b"",
    ]
    assert list(iter_sse(response)) == [{"text": "🙂"}]


def test_explicit_reasoning_wins_over_duplicate_inline_tags():
    message = read_chat_chunks(
        [
            chat_chunk(reasoning_content="Thought"),
            chat_chunk("<think>Thought</think>Answer"),
            chat_chunk(finish="stop"),
        ],
        lambda *args: None,
        lambda: False,
    )
    assert message["content"] == "Answer"
    assert message["reasoning_content"] == "Thought"


@pytest.mark.parametrize("finish", [None, "length", "content_filter"])
def test_incomplete_chat_never_returns_tool_calls(finish):
    with pytest.raises(RuntimeError, match="(before completion|incomplete)"):
        read_chat_chunks(
            [
                chat_chunk(
                    finish=finish,
                    tool_calls=[
                        {
                            "index": 0,
                            "id": "call",
                            "function": {"name": "text_get", "arguments": "{"},
                        }
                    ],
                )
            ],
            lambda *args: None,
            lambda: False,
        )


def test_broken_responses_stream_preserves_deltas_and_reports_failure():
    delivered = []
    with pytest.raises(RuntimeError, match="before completion"):
        read_response_events(
            [{"type": "response.output_text.delta", "delta": "Partial"}],
            lambda *args: delivered.append(args),
            lambda: False,
        )
    assert delivered == [("text", "Partial")]


def test_cancellation_closes_a_stream_while_waiting_for_tokens():
    cancel = threading.Event()
    closed = threading.Event()
    resource = Mock()
    resource.close.side_effect = closed.set
    with pytest.raises(StreamCancelled), managed_stream(resource, cancel.is_set):
        cancel.set()
        assert closed.wait(2)


def run(provider, provider_name, model, messages=None, **kwargs):
    delivered, meta = [], {}
    answer = stream_chat_completion(
        provider,
        provider_name,
        {
            "model": model,
            "messages": messages or [{"role": "user", "content": "Hello"}],
            **kwargs,
        },
        lambda *args: delivered.append(args),
        lambda: False,
        meta,
    )
    return answer, delivered, meta


@pytest.mark.parametrize(
    "provider_name, model",
    [
        ("openai", "gpt-5"),
        ("openai", "gpt-5.1"),
        ("openai", "gpt-5.2"),
        ("openai", "o3"),
        ("openai", "o4-mini"),
        ("grok", "grok-4.7"),
        ("grok", "grok-latest"),
    ],
)
def test_real_sdk_streams_summaries_and_replays_complete_tool_output(
    provider_name, model
):
    requests_seen = []
    reasoning = {
        "type": "reasoning",
        "id": "rs",
        "summary": [],
        "encrypted_content": "opaque",
    }
    call = {
        "type": "function_call",
        "id": "fc",
        "call_id": "call",
        "name": "text_get",
        "arguments": '{"target":"document"}',
    }

    def handle(request):
        params = json.loads(request.content)
        requests_seen.append(params)
        if len(requests_seen) == 1:
            output = [reasoning, call]
            events = response_events(output, text="")
        else:
            output = [message_output("Answer")]
            events = response_events(output, reasoning="")
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            text="".join(frame(event) for event in events),
        )

    provider = OpenAIProvider() if provider_name == "openai" else GrokProvider()
    with OpenAI(
        api_key="test",
        base_url="https://test.invalid/v1",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    ) as client:
        provider.client = client
        tool = Mock(return_value="document text")
        answer, delivered, meta = run(
            provider,
            provider_name,
            model,
            text_get_handler=tool,
            web_search_enabled=True,
        )
        assert answer == "Answer"
        assert ("reasoning", "Consider the options") in delivered
        assert ("text", "Answer") in delivered
        assert requests_seen[0]["stream"] is True
        if provider_name == "openai":
            assert requests_seen[0]["reasoning"]["summary"] == "auto"
        tool.assert_called_once_with("document")
        assert [item["type"] for item in requests_seen[1]["input"]] == [
            "message",
            "reasoning",
            "function_call",
            "function_call_output",
        ]
        assert requests_seen[1]["input"][1]["encrypted_content"] == "opaque"
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": answer, "provider_meta": meta},
            {"role": "user", "content": "Continue"},
        ]
        run(provider, provider_name, model, messages, web_search_enabled=True)
        assert any(
            item.get("encrypted_content") == "opaque"
            for item in requests_seen[2]["input"]
        )
        if not get_card(model).capabilities.web_search:
            messages[1]["content"] = "Edited answer"
        run(provider, provider_name, model, messages, web_search_enabled=False)
        assert not any(
            item.get("encrypted_content") == "opaque"
            for item in requests_seen[3]["input"]
        )


def test_local_custom_model_streams_inline_thinking_without_extra_parameters(
    monkeypatch,
):
    provider = CustomProvider()
    provider.initialize("", "http://localhost:8080/v1/chat/completions", "local-qwen")
    response = http_stream(
        [
            chat_chunk("<thi"),
            chat_chunk("nk>Thought</thi"),
            chat_chunk("nk>Hello 🙂"),
            chat_chunk(finish="stop"),
        ]
    )
    post = Mock(return_value=response)
    monkeypatch.setattr(provider.session, "post", post)
    answer, delivered, _meta = run(provider, "custom", "local-alias")
    assert answer == "Hello 🙂"
    assert (
        "".join(value for kind, value in delivered if kind == "reasoning") == "Thought"
    )
    payload = post.call_args.kwargs["json"]
    assert payload["model"] == "local-qwen"
    assert payload["stream"] is True
    assert "reasoning" not in payload
    response.close.assert_called()


def test_openrouter_assembles_tool_arguments_and_retains_opaque_details(monkeypatch):
    provider = CustomProvider()
    provider.initialize("test", "https://openrouter.ai/api/v1", "anthropic/test")
    detail = {"type": "reasoning.encrypted", "data": "opaque", "index": 0, "id": "rs"}
    first = http_stream(
        [
            chat_chunk(reasoning="Summary", reasoning_details=[detail]),
            chat_chunk(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call",
                        "function": {"name": "text_get", "arguments": '{"tar'},
                    }
                ]
            ),
            chat_chunk(
                tool_calls=[{"index": 0, "function": {"arguments": 'get":"document"}'}}]
            ),
            chat_chunk(finish="tool_calls"),
        ]
    )
    second = http_stream([chat_chunk("Done"), chat_chunk(finish="stop")])
    payloads = []

    def post(url, **kwargs):
        payloads.append(json.loads(json.dumps(kwargs["json"])))
        return first if len(payloads) == 1 else second

    monkeypatch.setattr(provider.session, "post", post)
    tool = Mock(return_value="document")
    answer, delivered, meta = run(
        provider, "custom", "router-model", text_get_handler=tool
    )
    assert answer == "Done"
    tool.assert_called_once_with("document")
    assert payloads[0]["reasoning"] == {"enabled": True, "exclude": False}
    assistant = payloads[1]["messages"][1]
    assert (
        assistant["tool_calls"][0]["function"]["arguments"] == '{"target":"document"}'
    )
    assert assistant["reasoning_details"] == [detail]
    assert "opaque" not in str(delivered)
    assert len(meta["custom"]["turn_messages"]) == 3


def test_custom_endpoint_returning_plain_json_still_shows_reasoning(monkeypatch):
    provider = CustomProvider()
    provider.initialize("", "http://localhost:8080/v1", "local")
    response = requests.Response()
    response.status_code = 200
    response.headers["Content-Type"] = "application/json"
    response._content = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "content": "Answer",
                        "reasoning_content": "Thought",
                    }
                }
            ]
        }
    ).encode()
    response._content_consumed = True
    monkeypatch.setattr(provider.session, "post", Mock(return_value=response))
    answer, delivered, _ = run(provider, "custom", "local")
    assert answer == "Answer"
    assert ("reasoning", "Thought") in delivered


def test_gemini_streams_native_thoughts_and_keeps_signed_tool_parts(monkeypatch):
    provider = GeminiProvider()
    provider.initialize("test")
    payloads = []
    thought = {"text": "Thought", "thought": True, "thoughtSignature": "opaque-thought"}
    tool_part = {
        "functionCall": {"name": "text_get", "args": {"target": "document"}},
        "thoughtSignature": "signed-call",
    }

    def post(url, **kwargs):
        assert url.endswith(":streamGenerateContent?alt=sse")
        payloads.append(json.loads(json.dumps(kwargs["json"])))
        parts = [thought, tool_part] if len(payloads) == 1 else [{"text": "Answer"}]
        return http_stream(
            [
                {
                    "candidates": [
                        {
                            "content": {"role": "model", "parts": parts},
                            "finishReason": "STOP",
                        }
                    ]
                }
            ]
        )

    monkeypatch.setattr("services.streaming_service.requests.post", post)
    tool = Mock(return_value="document")
    answer, delivered, meta = run(
        provider, "gemini", "gemini-2.5-pro", text_get_handler=tool
    )
    assert answer == "Answer"
    assert ("reasoning", "Thought") in delivered
    assert "opaque-thought" not in str(delivered)
    assert payloads[0]["generationConfig"]["thinkingConfig"]["includeThoughts"] is True
    assert payloads[1]["contents"][1]["parts"] == [thought, tool_part]
    assert (
        payloads[1]["contents"][2]["parts"][0]["functionResponse"]["name"] == "text_get"
    )
    tool.assert_called_once_with("document")
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": answer, "provider_meta": meta},
        {"role": "user", "content": "Continue"},
    ]
    run(provider, "gemini", "gemini-2.5-pro", messages)
    assert payloads[2]["contents"][1]["parts"] == [thought, tool_part]
    assert payloads[2]["contents"][-1]["parts"] == [{"text": "Continue"}]


def test_audio_and_image_requests_keep_the_existing_provider_path():
    assert not can_stream(OpenAIProvider(), "openai", "gpt-4o-audio-preview")
    assert not can_stream(OpenAIProvider(), "openai", "gpt-image-1")
    provider = CustomProvider()
    provider.api_type = "tts"
    assert not can_stream(provider, "custom", "custom-tts")


def test_custom_responses_endpoint_collects_summaries_from_completed_json(monkeypatch):
    provider = CustomProvider()
    provider.initialize(
        "", "http://localhost:8080/v1/responses", "local", api_type="responses"
    )
    events = response_events(
        [
            {
                "type": "reasoning",
                "id": "rs",
                "summary": [{"type": "summary_text", "text": "Thought"}],
            },
            message_output("Answer"),
        ]
    )
    response = http_stream(events[-1:])
    monkeypatch.setattr(provider.session, "post", Mock(return_value=response))
    answer, delivered, meta = run(provider, "custom", "local")
    assert answer == "Answer"
    assert ("reasoning", "Thought") in delivered
    assert meta["custom"]["response_output"][0]["type"] == "reasoning"
    response.close.assert_called()


@pytest.mark.parametrize(
    "done_type",
    [
        "response.reasoning_summary_text.done",
        "response.reasoning_summary_part.done",
        "response.output_item.done",
    ],
)
def test_completed_summary_events_are_captured_once_without_deltas(done_type):
    summary = {"type": "summary_text", "text": "Compare the options"}
    item = {"type": "reasoning", "id": "rs", "summary": [summary]}
    event = {
        "type": done_type,
        "item_id": "rs",
        "output_index": 0,
        "summary_index": 0,
        "text": summary["text"],
        "part": summary,
        "item": item,
    }
    events = [event, *response_events([item, message_output("Answer")], reasoning="")]
    delivered = []
    read_response_events(events, lambda *args: delivered.append(args), lambda: False)
    assert (
        "".join(value for kind, value in delivered if kind == "reasoning")
        == summary["text"]
    )
    assert "".join(value for kind, value in delivered if kind == "text") == "Answer"


def test_summary_completion_fills_missing_suffix_and_keeps_other_parts():
    events = [
        {
            "type": "response.reasoning_summary_text.delta",
            "item_id": "rs",
            "summary_index": 0,
            "delta": "Compare",
        },
        {
            "type": "response.reasoning_summary_text.done",
            "item_id": "rs",
            "summary_index": 0,
            "text": "Compare the options",
        },
        *response_events(
            [
                {
                    "type": "reasoning",
                    "id": "rs",
                    "summary": [
                        {"type": "summary_text", "text": "Compare the options"},
                        {"type": "summary_text", "text": "Choose the best fit"},
                    ],
                },
                message_output("Answer"),
            ],
            reasoning="",
        ),
    ]
    delivered = []
    read_response_events(events, lambda *args: delivered.append(args), lambda: False)
    assert "".join(value for kind, value in delivered if kind == "reasoning") == (
        "Compare the options\n\nChoose the best fit"
    )


def test_gemini_text_and_signature_chunks_are_reassembled_for_replay(monkeypatch):
    provider = GeminiProvider()
    provider.initialize("test")
    events = [
        {"candidates": [{"content": {"parts": [{"text": "Think", "thought": True}]}}]},
        {"candidates": [{"content": {"parts": [{"text": "ing", "thought": True}]}}]},
        {
            "candidates": [
                {"content": {"parts": [{"thoughtSignature": "signed-thought"}]}}
            ]
        },
        {"candidates": [{"content": {"parts": [{"text": "Answer"}]}}]},
        {
            "candidates": [
                {
                    "content": {"parts": [{"thoughtSignature": "signed-answer"}]},
                    "finishReason": "STOP",
                }
            ]
        },
    ]
    monkeypatch.setattr(
        "services.streaming_service.requests.post",
        Mock(return_value=http_stream(events)),
    )
    answer, delivered, meta = run(provider, "gemini", "gemini-pro-latest")
    assert answer == "Answer"
    assert meta["gemini"]["turn_content"][0]["parts"] == [
        {"text": "Thinking", "thought": True, "thoughtSignature": "signed-thought"},
        {"text": "Answer", "thoughtSignature": "signed-answer"},
    ]
    assert "signed" not in str(delivered)


@pytest.mark.parametrize("change", ["model", "endpoint", "answer"])
def test_custom_protocol_state_is_not_replayed_after_configuration_or_content_changes(
    monkeypatch, change
):
    provider = CustomProvider()
    provider.initialize("test", "https://openrouter.ai/api/v1", "model-a")
    post = Mock(
        side_effect=lambda *args, **kwargs: http_stream(
            [
                chat_chunk(
                    "Answer",
                    reasoning_details=[
                        {"type": "reasoning.encrypted", "data": "opaque", "index": 0}
                    ],
                ),
                chat_chunk(finish="stop"),
            ]
        )
    )
    monkeypatch.setattr(provider.session, "post", post)
    answer, _, meta = run(provider, "custom", "alias")
    messages = [
        {"role": "assistant", "content": answer, "provider_meta": meta},
        {"role": "user", "content": "Continue"},
    ]
    if change == "model":
        provider.model_id = "model-b"
    elif change == "endpoint":
        provider.endpoint = "http://localhost:8080/v1"
    else:
        messages[0]["content"] = "Edited answer"
    run(provider, "custom", "alias", messages)
    assert "reasoning_details" not in post.call_args.kwargs["json"]["messages"][0]
    assert "provider_meta" not in post.call_args.kwargs["json"]["messages"][0]
