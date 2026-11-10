"""New conversational Realtime models use GA sessions and audio events."""

import asyncio
import base64
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

spec = importlib.util.spec_from_file_location(
    "chatgtk_test_realtime",
    Path(__file__).resolve().parents[1] / "src/realtime/openai.py",
)
realtime = importlib.util.module_from_spec(spec)
# Network protocol tests need neither PortAudio nor an audio device.
with patch.dict(sys.modules, {"sounddevice": Mock()}):
    spec.loader.exec_module(realtime)
OpenAIWebSocketProvider = realtime.OpenAIWebSocketProvider


def websocket(events):
    ws = Mock(closed=False, state=None)
    ws.send = AsyncMock()
    ws.recv = AsyncMock(side_effect=[json.dumps(event) for event in events])
    ws.close = AsyncMock()
    return ws


def provider(model):
    instance = OpenAIWebSocketProvider()
    instance.api_key = "test-key"
    instance.model = model
    instance.voice = "alloy"
    instance.realtime_prompt = "Speak clearly."
    instance.temperature = 0.7
    return instance


@pytest.mark.parametrize(
    "model, beta",
    [
        ("gpt-realtime", False),
        ("gpt-realtime-2.1-mini", False),
        ("gpt-4o-realtime-preview-2025-06-03", True),
    ],
)
def test_realtime_session_uses_the_selected_models_protocol(monkeypatch, model, beta):
    instance = provider(model)
    ws = websocket([{"type": "session.created"}, {"type": "session.updated"}])
    connect = AsyncMock(return_value=ws)
    monkeypatch.setattr(realtime.websockets, "connect", connect)
    asyncio.run(instance.ensure_connection("alloy"))
    assert connect.call_args.args[0].endswith(f"?model={model}")
    headers = connect.call_args.kwargs["additional_headers"]
    assert ("OpenAI-Beta" in headers) == beta
    session = json.loads(ws.send.call_args.args[0])["session"]
    if beta:
        assert session["modalities"] == ["text", "audio"]
        assert session["voice"] == "alloy"
    else:
        assert session["type"] == "realtime"
        assert session["output_modalities"] == ["audio"]
        assert session["audio"]["output"]["voice"] == "alloy"
        assert session["audio"]["input"]["format"] == {
            "type": "audio/pcm",
            "rate": 24000,
        }
        assert session["audio"]["input"]["turn_detection"]["type"] == "server_vad"
        assert "temperature" not in session
    assert session["instructions"] == "Speak clearly."


def test_session_rejection_closes_connection_and_reports_error(monkeypatch):
    instance = provider("gpt-realtime-2.1-mini")
    ws = websocket([{"type": "error", "error": {"message": "Unsupported session"}}])
    monkeypatch.setattr(realtime.websockets, "connect", AsyncMock(return_value=ws))
    with pytest.raises(RuntimeError, match="Unsupported session"):
        asyncio.run(instance.ensure_connection("alloy"))
    ws.close.assert_awaited_once()
    assert instance.ws is None


def test_selecting_another_realtime_model_opens_a_new_connection(monkeypatch):
    instance = provider("gpt-realtime-2.1-mini")
    instance.ws = websocket([])
    instance._connected_model = "gpt-realtime"
    old_ws = instance.ws
    new_ws = websocket([{"type": "session.updated"}])
    monkeypatch.setattr(realtime.websockets, "connect", AsyncMock(return_value=new_ws))
    asyncio.run(instance.ensure_connection("alloy"))
    old_ws.close.assert_awaited_once()
    assert instance.ws is new_ws


@pytest.mark.parametrize(
    "model, audio_event, beta",
    [
        ("gpt-realtime-2.1-mini", "response.output_audio.delta", False),
        ("gpt-4o-realtime-preview", "response.audio.delta", True),
    ],
)
def test_realtime_text_turn_plays_audio_and_returns_transcript(
    monkeypatch, model, audio_event, beta
):
    instance = provider(model)
    pcm = b"\x01\x00\x02\x00"
    ws = websocket(
        [
            {"type": "session.updated"},
            {"type": audio_event, "delta": base64.b64encode(pcm).decode()},
            {
                "type": "response.done",
                "response": {"output": [{"content": [{"transcript": "Hello!"}]}]},
            },
        ]
    )
    monkeypatch.setattr(realtime.websockets, "connect", AsyncMock(return_value=ws))
    output_stream = Mock()
    monkeypatch.setattr(realtime.sd, "OutputStream", Mock(return_value=output_stream))
    instance.on_assistant_transcript = Mock()
    asyncio.run(instance.send_text_message("Hello"))
    sent = [json.loads(call.args[0]) for call in ws.send.call_args_list]
    assert [event["type"] for event in sent] == [
        "session.update",
        "conversation.item.create",
        "response.create",
    ]
    response = sent[-1]["response"]
    if beta:
        assert response["temperature"] == 0.7
    else:
        assert response == {"output_modalities": ["audio"]}
    output_stream.start.assert_called_once()
    assert output_stream.write.call_args.args[0].tobytes() == pcm
    instance.on_assistant_transcript.assert_called_once_with("Hello!")


def test_microphone_session_handles_ga_audio_and_transcripts(monkeypatch):
    instance = provider("gpt-realtime-2.1-mini")
    instance.microphone = "test microphone"
    pcm = b"\x01\x00\x02\x00"
    ws = websocket(
        [
            {"type": "session.updated"},
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "transcript": "Question",
            },
            {"type": "response.created"},
            {
                "type": "response.output_audio.delta",
                "delta": base64.b64encode(pcm).decode(),
            },
            {
                "type": "response.done",
                "response": {
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"transcript": "Answer"}],
                        }
                    ]
                },
            },
        ]
    )
    monkeypatch.setattr(realtime.websockets, "connect", AsyncMock(return_value=ws))
    monkeypatch.setattr(realtime.sd, "query_devices", Mock(return_value=[]))
    output = Mock()
    monkeypatch.setattr(realtime.sd, "OutputStream", Mock(return_value=output))
    monkeypatch.setattr(realtime.sd, "InputStream", Mock())
    instance.on_user_transcript = Mock()
    instance.on_assistant_transcript = Mock(
        side_effect=lambda text: setattr(instance, "is_recording", False)
    )
    asyncio.run(asyncio.wait_for(instance.start_audio_stream(Mock()), timeout=2))
    instance.on_user_transcript.assert_called_once_with("Question")
    instance.on_assistant_transcript.assert_called_once_with("Answer")
    assert output.write.call_args.args[0].tobytes() == pcm
