import websockets
import asyncio
import json
import os
import numpy as np
import sounddevice as sd
import threading
import base64


class OpenAIWebSocketProvider:
    def __init__(self, callback_scheduler=None):
        """Initialize the WebSocket provider.

        Args:
            callback_scheduler: Optional callable to schedule callbacks on the main thread.
                                If not provided, callbacks are invoked directly.
        """
        self.ws = None
        self.loop = None
        self.thread = None
        self.is_recording = False
        self.audio_buffer = bytearray()
        self.is_ai_speaking = False  # New flag to track AI speech state
        self.last_event_id = None  # Track event ID for responses
        self._callback_scheduler = callback_scheduler
        self.debug = False  # Realtime logging suppressed by default
        self.api_key = None  # Allow callers to inject key directly
        self.mute_mic_during_playback = True

        # Transcript callbacks
        self.on_user_transcript = None  # Called with user's transcribed speech
        self.on_assistant_transcript = None  # Called with assistant's response transcript

        # Audio configuration
        self.input_sample_rate = 48000  # Input from mic
        self.output_sample_rate = 24000  # Server rate
        self.channels = 1
        self.dtype = np.int16
        self.min_audio_ms = 75
        self.response_started = False  # Track if a response is in flight for this turn
        self.last_send_error = None
        self.buffer_started = False  # Track per-turn buffering (no explicit start message)
        self.awaiting_response = False  # Pause mic while waiting for response.done
        self.has_pending_audio = False  # Track whether we've sent audio this turn
        self.awaiting_final_transcript = False

        self.output_stream = None
        self.message_lock = asyncio.Lock()  # Add lock for message handling
        self._lock = threading.Lock()
        self.drain_requested = False  # Track shutdown drain phase

    def _schedule_callback(self, callback, *args):
        """Schedule a callback on the main thread."""
        if self._callback_scheduler:
            self._callback_scheduler(callback, *args)
        else:
            callback(*args)

    def _log(self, msg: str):
        """Debug logger (disabled by default)."""
        if self.debug:
            print(f"[Realtime] {msg}")

    def start_loop(self):
        """Start the event loop in a new thread if not already running"""
        with self._lock:
            if self.thread is None or not self.thread.is_alive():
                self.loop = asyncio.new_event_loop()
                self.thread = threading.Thread(target=self.run_loop, daemon=True)
                self.thread.start()

    def run_loop(self):
        """Run the event loop"""
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def stop_loop(self):
        """Safely stop the event loop"""
        if self.loop and self.loop.is_running():
            try:
                # Cancel any pending tasks to avoid "Task was destroyed" warnings
                async def _cancel_tasks():
                    current = asyncio.current_task(self.loop)
                    tasks = [t for t in asyncio.all_tasks(self.loop) if not t.done() and t is not current]
                    for t in tasks:
                        t.cancel()
                    if tasks:
                        await asyncio.gather(*tasks, return_exceptions=True)

                asyncio.run_coroutine_threadsafe(_cancel_tasks(), self.loop).result(timeout=2.0)
                # Give the loop a tick to process cancellations
                asyncio.run_coroutine_threadsafe(asyncio.sleep(0), self.loop).result(timeout=1.0)
            except Exception as e:
                print(f"Error cancelling tasks: {e}")

            self.loop.call_soon_threadsafe(self.loop.stop)
            if self.thread and self.thread.is_alive():
                self.thread.join()
            try:
                self.loop.close()
            except Exception as e:
                print(f"Error closing loop: {e}")
            self.loop = None
            self.thread = None

    def __del__(self):
        """Cleanup resources"""
        self.stop_loop()
        if self.output_stream:
            try:
                self.output_stream.stop()
                self.output_stream.close()
            except Exception:
                pass

    def _ws_is_open(self):
        if not self.ws:
            return False
        # websockets >= 15 uses .state; fall back to .closed/.open
        state = getattr(self.ws, "state", None)
        if state is not None:
            try:
                # State.OPEN is an enum; compare by name for safety
                return getattr(state, "name", str(state)) == "OPEN" or state == 1
            except Exception:
                pass
        if hasattr(self.ws, "closed"):
            try:
                return not bool(self.ws.closed)
            except Exception:
                return False
        return bool(getattr(self.ws, "open", False))

    def _ws_state_debug(self):
        if not self.debug:
            return ""
        state = {
            "has_ws": bool(self.ws),
            "closed_attr": getattr(self.ws, "closed", None) if self.ws else None,
            "open_attr": getattr(self.ws, "open", None) if self.ws else None,
        }
        return f"ws_state={state}"

    async def ensure_connection(self, voice):
        """Ensure we have an active WebSocket connection"""
        if not self._ws_is_open():
            api_key = self.api_key or os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY environment variable not set")

            # Get model from URL parameters
            model = getattr(self, "model", "gpt-realtime")  # Default fallback

            headers = {
                "Authorization": f"Bearer {api_key}",
                "OpenAI-Beta": "realtime=v1",
            }
            ws_url = f"wss://api.openai.com/v1/realtime?model={model}"

            try:
                # websockets >= 15 expects additional_headers
                self.ws = await websockets.connect(ws_url, additional_headers=headers)
            except TypeError:
                # Older versions only support extra_headers
                self.ws = await websockets.connect(ws_url, extra_headers=headers)
            print(f"Connected to server using model: {model}")
            self.response_started = False  # reset stream state on fresh connect

            # Send initial configuration with session parameters
            instructions = (self.realtime_prompt or "Your name is {name}, speak quickly and professionally").strip()
            vad_threshold = getattr(self, "vad_threshold", 0.1)
            config_message = {
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "instructions": instructions,
                    "voice": voice,
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "input_audio_transcription": {
                        "model": "gpt-4o-transcribe",
                        "language": "en",
                    },
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": vad_threshold,
                        "prefix_padding_ms": 10,
                        "silence_duration_ms": 400,
                        "create_response": True,
                    },
                },
            }
            await self.ws.send(json.dumps(config_message))

            # Wait for session.updated confirmation
            while True:
                response = await self.ws.recv()
                if isinstance(response, str):
                    data = json.loads(response)
                    if data.get("type") == "session.updated":
                        self.last_event_id = data.get("event_id")  # Store the event ID
                        break

    def _initialize_output_stream(self):
        """Initialize audio output stream if needed"""
        if self.output_stream is None:
            self.output_stream = sd.OutputStream(
                channels=1,
                samplerate=self.output_sample_rate,
                dtype=np.int16,
                blocksize=4800,  # 200ms chunks at 24kHz
                latency="low",
            )
            self.output_stream.start()

    async def start_audio_stream(self, callback):
        """Start streaming audio to the API"""
        try:
            await self.ensure_connection(self.voice)
            self._log("start_audio_stream: connection ready")

            self.is_recording = True

            # Initialize audio output stream
            self._initialize_output_stream()
            self._log("start_audio_stream: output stream initialized")

            # Find the device index for the selected microphone
            devices = sd.query_devices()
            device_idx = None
            for i, device in enumerate(devices):
                if device["name"] == self.microphone and device["max_input_channels"] > 0:
                    device_idx = i
                    break

            print(f"Found device index: {device_idx}")

            # Clear any previous audio buffer state
            self.audio_buffer = bytearray()
            self.buffer_started = False
            self.has_pending_audio = False
            self.awaiting_response = False
            self.response_started = False

            # Create audio input stream with callback
            def audio_callback(indata, frames, time_info, status):
                if status:
                    self._log(f"Audio callback status: {status}")
                if not self.is_recording:
                    return

                # Optionally suppress mic capture while AI is speaking
                if getattr(self, "mute_mic_during_playback", True) and self.is_ai_speaking:
                    return

                try:
                    # Normalize and scale the audio data
                    audio_data = indata.copy()
                    audio_data = audio_data.flatten()

                    if self.debug:
                        peak = float(np.max(np.abs(audio_data))) if audio_data.size else 0.0
                        self._log(f"audio_callback frames={frames} max={peak:.4f} buffer_bytes={len(self.audio_buffer)}")

                    # Resample from input_sample_rate to output_sample_rate
                    if self.input_sample_rate != self.output_sample_rate and len(audio_data) > 0:
                        resampled_size = int(len(audio_data) * self.output_sample_rate / self.input_sample_rate)
                        resampled_data = np.interp(
                            np.linspace(0, len(audio_data), resampled_size, endpoint=False),
                            np.arange(len(audio_data)),
                            audio_data,
                        )
                    else:
                        resampled_data = audio_data

                    # Convert float to int16 PCM
                    audio_data_int16 = np.clip(resampled_data * 32767, -32768, 32767)
                    audio_bytes = audio_data_int16.astype(np.int16).tobytes()

                    self.audio_buffer.extend(audio_bytes)

                    buffer_duration_ms = (len(self.audio_buffer) / 2) * 1000 / self.output_sample_rate
                    if buffer_duration_ms >= self.min_audio_ms:
                        self._log(f"send buffer bytes={len(self.audio_buffer)} duration_ms={buffer_duration_ms:.1f}")
                        chunk_bytes = bytes(self.audio_buffer)
                        try:
                            asyncio.run_coroutine_threadsafe(
                                self._send_audio_chunk(chunk_bytes, commit_now=False),
                                self.loop,
                            )
                        except Exception as e:
                            print(f"Error scheduling audio send: {e}")
                        finally:
                            self.audio_buffer = bytearray()
                except Exception as e:
                    print(f"Error in audio callback: {e}")

            # Start input stream
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

            # Listen for responses
            while self.is_recording or self.drain_requested:
                if not self.ws or not self._ws_is_open():
                    self._log(f"stream loop: websocket not open; attempting reconnect ({self._ws_state_debug()})")
                    try:
                        await self.ensure_connection(self.voice)
                        self._log("audio_callback: reconnected websocket")
                    except Exception as e:
                        self._log(f"audio_callback: reconnect failed {e!r}")
                        await asyncio.sleep(0.25)
                        continue

                async with self.message_lock:
                    try:
                        try:
                            message = await asyncio.wait_for(self.ws.recv(), timeout=0.5)
                        except asyncio.TimeoutError:
                            if not (self.is_recording or self.drain_requested):
                                break
                            continue
                        if isinstance(message, str):
                            response = json.loads(message)

                            # Update event ID from responses
                            if "event_id" in response:
                                self.last_event_id = response["event_id"]

                            # Track when the model is speaking so we can suppress mic capture
                            if response.get("type") in ("response.created", "response.output_item.added", "response.audio.delta"):
                                self.is_ai_speaking = True
                                self.awaiting_response = True
                                if response.get("type") in ("response.created",):
                                    print("AI response starting")
                            elif response.get("type") in ("response.output_item.done", "response.done"):
                                self.is_ai_speaking = False
                                self.awaiting_response = False
                                print("AI response stopping")

                            # Handle user speech transcript
                            if response.get("type") == "conversation.item.input_audio_transcription.completed":
                                transcript = response.get("transcript", "")
                                if transcript and self.on_user_transcript:
                                    self._schedule_callback(self.on_user_transcript, transcript)

                            # Handle assistant response transcript
                            elif response.get("type") == "response.done":
                                resp_data = response.get("response", {})
                                for output in resp_data.get("output", []):
                                    if output.get("type") == "message" and output.get("role") == "assistant":
                                        for content in output.get("content", []):
                                            transcript = content.get("transcript", "")
                                            if transcript and self.on_assistant_transcript:
                                                self._schedule_callback(self.on_assistant_transcript, transcript)
                                # End drain phase once final response processed
                                self.drain_requested = False
                                self.response_started = False
                                self.buffer_started = False
                                self.awaiting_response = False
                                self.has_pending_audio = False
                                self.awaiting_final_transcript = False

                            # Handle server VAD speech detection events
                            elif response.get("type") == "input_audio_buffer.speech_started":
                                self._log("Server VAD: speech started")
                            elif response.get("type") == "input_audio_buffer.speech_stopped":
                                self._log("Server VAD: speech stopped")
                                # Server VAD will auto-commit, just track state
                                self.awaiting_response = True

                            if "text" in response and not self.awaiting_response:
                                self._schedule_callback(callback, response["text"])
                            elif response.get("type") == "response.audio.delta":
                                try:
                                    # Get the audio delta data
                                    audio_bytes = base64.b64decode(response["delta"])

                                    # Convert to numpy array
                                    audio_data = np.frombuffer(audio_bytes, dtype=np.int16)

                                    # Ensure audio is in correct shape for playback
                                    if audio_data.ndim == 1:
                                        audio_data = audio_data.reshape(-1, 1)

                                    # Write to output stream
                                    self.output_stream.write(audio_data)
                                except Exception as e:
                                    print(f"Error playing audio delta: {e}")
                                    import traceback

                                    traceback.print_exc()
                            elif response.get("type") == "error":
                                err_code = response.get("error", {}).get("code")
                                # Ignore empty buffer errors (common during shutdown)
                                if err_code == "input_audio_buffer_commit_empty":
                                    self._log("Ignoring empty buffer commit error")
                                    continue
                                print(f"Error from server: {response}")
                                # Reset buffer state on invalid audio errors
                                self.buffer_started = False
                                self.has_pending_audio = False
                                if err_code == "invalid_value":
                                    continue
                                break
                            elif "audio" in response:  # Audio data in base64
                                try:
                                    # Decode base64 audio data
                                    audio_bytes = base64.b64decode(response["audio"])
                                    if self.debug:
                                        print(f"Received audio data: {len(audio_bytes)} bytes")

                                    # Convert to numpy array and ensure correct format
                                    audio_data = np.frombuffer(audio_bytes, dtype=np.int16)

                                    # Ensure audio is in correct shape for playback
                                    if audio_data.ndim == 1:
                                        audio_data = audio_data.reshape(-1, 1)

                                    # Write to output stream
                                    self.output_stream.write(audio_data)
                                    if self.debug:
                                        print(f"Played audio chunk: shape={audio_data.shape}, dtype={audio_data.dtype}")
                                except Exception as e:
                                    print(f"Error playing audio: {e}")
                                    import traceback

                                    traceback.print_exc()

                    except websockets.exceptions.ConnectionClosed as e:
                        print(f"WebSocket closed with code {e.code}: {e.reason}")
                        self.ws = None
                    except Exception as e:
                        print(f"Error processing message: {e}")
        except Exception as e:
            print(f"Error starting audio stream: {e}")
            self.is_recording = False

    async def _send_audio_chunk(self, audio_bytes: bytes, commit_now: bool = False):
        """Append audio and optionally commit/request a response."""
        try:
            self._log(f"_send_audio_chunk bytes={len(audio_bytes)} commit={commit_now}")
            if not self.ws or not self._ws_is_open():
                self._log(f"send_audio_chunk: websocket not open ({self._ws_state_debug()})")
                return

            if audio_bytes:
                self.has_pending_audio = True
                append = {
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(audio_bytes).decode("utf-8"),
                }
                await self.ws.send(json.dumps(append))

            if commit_now:
                if not self.has_pending_audio:
                    return
                commit = {"type": "input_audio_buffer.commit"}
                await self.ws.send(json.dumps(commit))
                self._log("send_audio_chunk: sent commit")
                self.has_pending_audio = False
        except Exception as e:
            print(f"Error sending audio chunk: {e}")

    def _handle_send_audio_result(self, fut):
        """Handle the result of sending audio data"""
        try:
            fut.result()
        except Exception as e:
            print(f"Error sending audio data: {e}")

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
    ):
        """Start streaming audio in a background task"""
        self.microphone = microphone
        self.system_message = system_message
        self.temperature = temperature
        self.voice = voice or "alloy"
        if api_key:
            self.api_key = api_key
        if realtime_prompt:
            self.realtime_prompt = realtime_prompt
        if mute_mic_during_playback is not None:
            self.mute_mic_during_playback = bool(mute_mic_during_playback)
        if vad_threshold is not None:
            self.vad_threshold = float(vad_threshold)

        self.start_loop()

        # Create and run the audio stream in the event loop
        future = asyncio.run_coroutine_threadsafe(self.start_audio_stream(callback), self.loop)
        try:
            future.result(timeout=1.0)
        except Exception as e:
            # Expected: coroutine runs indefinitely; ignore timeout
            if not isinstance(e, TimeoutError):
                print(f"Error in audio stream: {e}")

    def stop_streaming(self):
        """Stop audio streaming"""
        self._log("Stopping audio stream...")
        self.is_recording = False

        # Stop input stream
        if getattr(self, "input_stream", None):
            try:
                self.input_stream.stop()
                self.input_stream.close()
            except Exception:
                pass
            self.input_stream = None

        # Only try to commit if we have local buffered audio (at least 100ms worth)
        min_buffer_bytes = int(self.output_sample_rate * 0.1) * 2  # 16-bit mono
        has_sufficient_audio = len(self.audio_buffer) >= min_buffer_bytes

        if self.loop and self.ws and self._ws_is_open():
            try:
                if has_sufficient_audio:
                    chunk_bytes = bytes(self.audio_buffer)
                    self.audio_buffer = bytearray()
                    asyncio.run_coroutine_threadsafe(self._send_audio_chunk(chunk_bytes, commit_now=True), self.loop)
                else:
                    self._log("stop_streaming: skipping commit (buffer too small)")
            except Exception as e:
                print(f"Error committing audio buffer on stop: {e}")

        # Close the websocket
        self.disconnect()

    async def send_text_message(self, text):
        """Send a text message through the realtime connection"""
        try:
            await self.ensure_connection(self.voice)

            text_message = {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": text}],
                },
            }
            await self.ws.send(json.dumps(text_message))
            if self.debug:
                print(f"Sent text message: {text}")

            # Process responses including audio
            while True:
                response = await self.ws.recv()
                if isinstance(response, str):
                    data = json.loads(response)

                    if data.get("type") == "conversation.item.created":
                        # Send response configuration
                        response_config = {
                            "type": "response.create",
                            "response": {
                                "modalities": ["audio", "text"],
                                "output_audio_format": "pcm16",
                            },
                        }
                        if self.temperature is not None:
                            response_config["response"]["temperature"] = self.temperature
                        await self.ws.send(json.dumps(response_config))
                        if self.debug:
                            print("Sent response configuration")

                    elif data.get("type") == "response.audio.delta":
                        try:
                            audio_bytes = base64.b64decode(data["delta"])

                            audio_data = np.frombuffer(audio_bytes, dtype=np.int16)
                            if audio_data.ndim == 1:
                                audio_data = audio_data.reshape(-1, 1)

                            self.output_stream.write(audio_data)
                        except Exception as e:
                            print(f"Error playing audio delta: {e}")

                    elif data.get("type") == "response.done":
                        break

        except Exception as e:
            print(f"Error sending text message: {e}")
            if self.output_stream:
                self.output_stream.stop()
                self.output_stream.close()
                self.output_stream = None

    def send_text(self, text, callback):
        """Send text message from main thread"""
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.send_text_message(text), self.loop)

    def connect(
        self,
        model=None,
        system_message=None,
        temperature=None,
        voice=None,
        api_key=None,
        realtime_prompt=None,
        mute_mic_during_playback=None,
    ):
        """Initialize WebSocket connection without starting audio stream"""
        # Store the configuration
        self.model = model or "gpt-realtime"
        self.system_message = system_message or "You are a helpful assistant."
        self.temperature = temperature
        self.voice = voice or "alloy"
        if api_key:
            self.api_key = api_key
        if realtime_prompt:
            self.realtime_prompt = realtime_prompt
        if mute_mic_during_playback is not None:
            self.mute_mic_during_playback = bool(mute_mic_during_playback)

        self.start_loop()

        # Ensure connection is established
        future = asyncio.run_coroutine_threadsafe(self.ensure_connection(self.voice), self.loop)
        try:
            future.result(timeout=10.0)  # Wait up to 10 seconds for connection
            if self.debug:
                print("WebSocket connection established")
            return True
        except Exception as e:
            print(f"Error connecting to WebSocket server: {e}")
            return False

    def disconnect(self):
        """Close the WebSocket connection and cleanup"""
        if self.output_stream:
            self.output_stream.stop()
            self.output_stream.close()
            self.output_stream = None

        if self.ws and self._ws_is_open():
            try:
                asyncio.run_coroutine_threadsafe(self.ws.close(), self.loop).result(timeout=5.0)
                asyncio.run_coroutine_threadsafe(self.ws.wait_closed(), self.loop).result(timeout=5.0)
            except Exception as e:
                print(f"Error during cleanup: {e}")

        self.stop_loop()

        self.ws = None

