"""
xAI (Grok) realtime voice client (scaffold).

Notes from `GROK.md`:
- Endpoint: wss://api.x.ai/v1/realtime
- Auth: Authorization: Bearer $XAI_API_KEY
- Session: session.update with session.voice + session.audio.{input,output}.format.{type,rate}
- Events: response.output_audio.delta, response.output_audio_transcript.delta, response.done, etc.

Implementation intentionally deferred until we finish extracting shared
realtime components from the OpenAI implementation.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import threading
from typing import Optional

import numpy as np
import sounddevice as sd
import websockets


class XAIWebSocketProvider:
    def __init__(self, callback_scheduler=None):
        self._callback_scheduler = callback_scheduler
        self.on_user_transcript = None
        self.on_assistant_transcript = None
        self.last_error = None

        self.ws = None
        self.loop = None
        self.thread = None
        self._lock = threading.Lock()
        self.message_lock = asyncio.Lock()

        self.api_key = None
        self.voice = "Ara"
        self.system_message = "You are a helpful assistant."
        self.temperature = None
        self.realtime_prompt = None
        self.turn_detection = "server_vad"  # or None

        self.is_recording = False
        self.drain_requested = False

        self.input_stream = None
        self.output_stream = None

        # Audio configuration
        self.input_sample_rate = 48000  # mic input
        self.output_sample_rate = 24000  # xAI default
        self.channels = 1
        self.min_audio_ms = 75
        self.audio_buffer = bytearray()

        # Transcript accumulation for assistant output (delta stream)
        self._assistant_transcript = ""
        self._assistant_transcript_in_progress = False

    def connect(
        self,
        model: Optional[str] = None,
        system_message: Optional[str] = None,
        temperature: Optional[float] = None,
        voice: Optional[str] = None,
        api_key: Optional[str] = None,
        realtime_prompt: Optional[str] = None,
        mute_mic_during_playback: Optional[bool] = None,
    ) -> bool:
        del model
        del mute_mic_during_playback

        self.last_error = None
        if api_key:
            self.api_key = api_key
        self.voice = voice or self.voice or "Ara"
        self.system_message = system_message or self.system_message
        self.temperature = temperature
        if realtime_prompt:
            self.realtime_prompt = realtime_prompt

        self.start_loop()
        fut = asyncio.run_coroutine_threadsafe(self.ensure_connection(), self.loop)
        try:
            fut.result(timeout=10.0)
            return True
        except Exception as exc:
            self.last_error = f"Failed to connect to xAI realtime: {exc}"
            return False

    def disconnect(self) -> None:
        if self.output_stream:
            try:
                self.output_stream.stop()
                self.output_stream.close()
            except Exception:
                pass
            self.output_stream = None

        if self.ws and self._ws_is_open():
            try:
                asyncio.run_coroutine_threadsafe(self.ws.close(), self.loop).result(timeout=5.0)
            except Exception:
                pass

        self.stop_loop()
        self.ws = None

    def start_streaming(
        self,
        callback,
        microphone=None,
        system_message=None,
        temperature=None,
        voice=None,
        api_key=None,
        realtime_prompt=None,
        mute_mic_during_playback=None,
        vad_threshold=None,
    ) -> None:
        del mute_mic_during_playback
        del vad_threshold

        self.last_error = None
        if api_key:
            self.api_key = api_key
        if voice:
            self.voice = voice
        if system_message:
            self.system_message = system_message
        if temperature is not None:
            self.temperature = temperature
        if realtime_prompt:
            self.realtime_prompt = realtime_prompt

        # If a microphone name is provided, store it. (We match by substring later.)
        self.microphone = microphone or ""

        self.start_loop()
        asyncio.run_coroutine_threadsafe(self._start_audio_stream(callback), self.loop)
        return None

    def stop_streaming(self) -> None:
        self.is_recording = False

        if self.input_stream:
            try:
                self.input_stream.stop()
                self.input_stream.close()
            except Exception:
                pass
            self.input_stream = None

        # Drain a little to let trailing response events arrive.
        self.drain_requested = True
        if self.loop:
            asyncio.run_coroutine_threadsafe(self._drain_then_stop(), self.loop)

        return None

    def send_text(self, text: str, callback) -> None:
        self.last_error = None
        self.start_loop()
        asyncio.run_coroutine_threadsafe(self._send_text_message(text, callback), self.loop)
        return None

    # ---------------------------------------------------------------------
    # Internals
    # ---------------------------------------------------------------------

    def _schedule_callback(self, callback, *args):
        if self._callback_scheduler:
            self._callback_scheduler(callback, *args)
        else:
            callback(*args)

    def start_loop(self):
        with self._lock:
            if self.thread is None or not self.thread.is_alive():
                self.loop = asyncio.new_event_loop()
                self.thread = threading.Thread(target=self._run_loop, daemon=True)
                self.thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def stop_loop(self):
        if self.loop and self.loop.is_running():
            try:
                async def _cancel_tasks():
                    current = asyncio.current_task(self.loop)
                    tasks = [t for t in asyncio.all_tasks(self.loop) if not t.done() and t is not current]
                    for t in tasks:
                        t.cancel()
                    if tasks:
                        await asyncio.gather(*tasks, return_exceptions=True)

                asyncio.run_coroutine_threadsafe(_cancel_tasks(), self.loop).result(timeout=2.0)
                asyncio.run_coroutine_threadsafe(asyncio.sleep(0), self.loop).result(timeout=1.0)
            except Exception:
                pass

            self.loop.call_soon_threadsafe(self.loop.stop)
            if self.thread and self.thread.is_alive():
                self.thread.join()
            try:
                self.loop.close()
            except Exception:
                pass

            self.loop = None
            self.thread = None

    def _ws_is_open(self) -> bool:
        if not self.ws:
            return False
        state = getattr(self.ws, "state", None)
        if state is not None:
            try:
                return getattr(state, "name", str(state)) == "OPEN" or state == 1
            except Exception:
                pass
        if hasattr(self.ws, "closed"):
            try:
                return not bool(self.ws.closed)
            except Exception:
                return False
        return bool(getattr(self.ws, "open", False))

    async def ensure_connection(self):
        if self._ws_is_open():
            return

        api_key = self.api_key or os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY")
        if not api_key:
            raise ValueError("Missing xAI API key (set XAI_API_KEY or GROK_API_KEY)")

        headers = {"Authorization": f"Bearer {api_key}"}
        ws_url = "wss://api.x.ai/v1/realtime"
        try:
            self.ws = await websockets.connect(ws_url, ssl=True, additional_headers=headers)
        except TypeError:
            self.ws = await websockets.connect(ws_url, ssl=True, extra_headers=headers)

        await self._send_session_update()

        # Wait for session.updated or conversation.created
        for _ in range(50):
            message = await self.ws.recv()
            if isinstance(message, str):
                data = json.loads(message)
                if data.get("type") in ("session.updated", "conversation.created"):
                    return

    async def _send_session_update(self):
        instructions = (self.realtime_prompt or self.system_message or "You are a helpful assistant.").strip()
        session_config = {
            "type": "session.update",
            "session": {
                "voice": self.voice or "Ara",
                "instructions": instructions,
                "turn_detection": {"type": "server_vad"} if self.turn_detection == "server_vad" else None,
                "audio": {
                    "input": {"format": {"type": "audio/pcm", "rate": int(self.output_sample_rate)}},
                    "output": {"format": {"type": "audio/pcm", "rate": int(self.output_sample_rate)}},
                },
            },
        }
        await self.ws.send(json.dumps(session_config))

    def _initialize_output_stream(self):
        if self.output_stream is None:
            self.output_stream = sd.OutputStream(
                channels=1,
                samplerate=self.output_sample_rate,
                dtype=np.int16,
                blocksize=4800,
                latency="low",
            )
            self.output_stream.start()

    def _select_input_device(self) -> Optional[int]:
        mic = (getattr(self, "microphone", "") or "").strip()
        if not mic or mic == "default":
            return None
        try:
            devices = sd.query_devices()
            for i, device in enumerate(devices):
                name = str(device.get("name", ""))
                if device.get("max_input_channels", 0) > 0 and mic in name:
                    return i
        except Exception:
            return None
        return None

    async def _start_audio_stream(self, callback):
        try:
            await self.ensure_connection()
            self.is_recording = True
            self.drain_requested = False
            self._assistant_transcript = ""
            self._assistant_transcript_in_progress = False

            self._initialize_output_stream()

            device_idx = self._select_input_device()

            def audio_callback(indata, frames, time_info, status):
                del frames, time_info
                if status:
                    # Avoid spamming; keep last error only.
                    self.last_error = str(status)
                if not self.is_recording:
                    return
                try:
                    audio_data = indata.copy().flatten()
                    if self.input_sample_rate != self.output_sample_rate and audio_data.size:
                        resampled_size = int(len(audio_data) * self.output_sample_rate / self.input_sample_rate)
                        audio_data = np.interp(
                            np.linspace(0, len(audio_data), resampled_size, endpoint=False),
                            np.arange(len(audio_data)),
                            audio_data,
                        )
                    audio_int16 = np.clip(audio_data * 32767, -32768, 32767).astype(np.int16)
                    self.audio_buffer.extend(audio_int16.tobytes())

                    buffer_ms = (len(self.audio_buffer) / 2) * 1000 / self.output_sample_rate
                    if buffer_ms >= self.min_audio_ms:
                        chunk = bytes(self.audio_buffer)
                        self.audio_buffer = bytearray()
                        asyncio.run_coroutine_threadsafe(self._send_audio_append(chunk), self.loop)
                except Exception as exc:
                    self.last_error = f"Audio callback error: {exc}"

            self.input_stream = sd.InputStream(
                device=device_idx,
                channels=self.channels,
                samplerate=self.input_sample_rate,
                dtype="float32",
                callback=audio_callback,
                blocksize=0,
                latency="low",
            )
            self.input_stream.start()

            await self._recv_loop(callback)
        except Exception as exc:
            self.last_error = f"Realtime streaming error: {exc}"
            self.is_recording = False

    async def _send_audio_append(self, audio_bytes: bytes):
        if not audio_bytes:
            return
        if not self.ws or not self._ws_is_open():
            return
        event = {
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(audio_bytes).decode("utf-8"),
        }
        await self.ws.send(json.dumps(event))

    async def _recv_loop(self, callback):
        while self.is_recording or self.drain_requested:
            if not self.ws or not self._ws_is_open():
                await asyncio.sleep(0.1)
                continue
            async with self.message_lock:
                try:
                    try:
                        msg = await asyncio.wait_for(self.ws.recv(), timeout=0.5)
                    except asyncio.TimeoutError:
                        if not (self.is_recording or self.drain_requested):
                            break
                        continue
                    if not isinstance(msg, str):
                        continue
                    data = json.loads(msg)
                    await self._handle_server_event(data, callback)
                except Exception as exc:
                    self.last_error = f"Realtime receive error: {exc}"

    async def _handle_server_event(self, data: dict, callback):
        event_type = data.get("type")

        if event_type == "conversation.item.input_audio_transcription.completed":
            transcript = data.get("transcript") or ""
            if transcript and self.on_user_transcript:
                self._schedule_callback(self.on_user_transcript, transcript)
            return

        if event_type == "response.output_audio.delta":
            try:
                audio_bytes = base64.b64decode(data.get("delta") or "")
                if audio_bytes:
                    audio_data = np.frombuffer(audio_bytes, dtype=np.int16)
                    if audio_data.ndim == 1:
                        audio_data = audio_data.reshape(-1, 1)
                    self._initialize_output_stream()
                    self.output_stream.write(audio_data)
            except Exception as exc:
                self.last_error = f"Audio playback error: {exc}"
            return

        if event_type == "response.output_audio_transcript.delta":
            delta = data.get("delta") or ""
            if delta:
                self._assistant_transcript_in_progress = True
                self._assistant_transcript += delta
            return

        if event_type == "response.output_audio_transcript.done":
            transcript = self._assistant_transcript.strip()
            if transcript and self.on_assistant_transcript:
                self._schedule_callback(self.on_assistant_transcript, transcript)
            self._assistant_transcript = ""
            self._assistant_transcript_in_progress = False
            return

        if event_type == "response.done":
            # Some sessions may not send transcript.done; flush on done.
            transcript = self._assistant_transcript.strip()
            if transcript and self.on_assistant_transcript:
                self._schedule_callback(self.on_assistant_transcript, transcript)
            self._assistant_transcript = ""
            self._assistant_transcript_in_progress = False
            self.drain_requested = False
            return

        # Optional: some servers may include plain text fields
        if isinstance(data.get("text"), str) and data.get("text") and not self._assistant_transcript_in_progress:
            self._schedule_callback(callback, data["text"])

    async def _send_text_message(self, text: str, callback):
        await self.ensure_connection()
        self._initialize_output_stream()

        # Create user message
        event = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            },
        }
        await self.ws.send(json.dumps(event))

        # Request response (docs: required when using client VAD; safe to send here)
        response_create = {"type": "response.create", "response": {"modalities": ["text", "audio"]}}
        if self.temperature is not None:
            response_create["response"]["temperature"] = self.temperature
        await self.ws.send(json.dumps(response_create))

        # Read until response.done
        self._assistant_transcript = ""
        self._assistant_transcript_in_progress = False
        while True:
            msg = await self.ws.recv()
            if not isinstance(msg, str):
                continue
            data = json.loads(msg)
            await self._handle_server_event(data, callback)
            if data.get("type") == "response.done":
                break

    async def _drain_then_stop(self):
        try:
            await asyncio.sleep(0.75)
        finally:
            self.drain_requested = False
