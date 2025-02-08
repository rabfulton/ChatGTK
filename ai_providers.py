from abc import ABC, abstractmethod
from openai import OpenAI
import requests
from pathlib import Path
from datetime import datetime
import websockets
import asyncio
import json
import os
from gi.repository import GLib
import numpy as np
import sounddevice as sd
import threading
import base64

class AIProvider(ABC):
    """Abstract base class for AI providers."""
    
    @abstractmethod
    def initialize(self, api_key: str):
        """Initialize the AI provider with API key."""
        pass
    
    @abstractmethod
    def get_available_models(self):
        """Get list of available models."""
        pass
    
    @abstractmethod
    def generate_chat_completion(self, messages, model, temperature=0.7, max_tokens=None):
        """Generate chat completion."""
        pass
    
    @abstractmethod
    def generate_image(self, prompt, chat_id):
        """Generate image from prompt."""
        pass
    
    @abstractmethod
    def transcribe_audio(self, audio_file):
        """Transcribe audio file to text."""
        pass
    
    @abstractmethod
    def generate_speech(self, text, voice):
        """Generate speech from text."""
        pass

class OpenAIProvider(AIProvider):
    def __init__(self):
        self.client = None
    
    def initialize(self, api_key: str):
        self.client = OpenAI(api_key=api_key)
    
    def get_available_models(self):
        import re
        try:
            models = self.client.models.list()
            filtered_models = [model.id for model in models if not re.search(r'-\d{4}-\d{2}-\d{2}$', model.id)]
            return sorted(filtered_models)
        except Exception as e:
            print(f"Error fetching models: {e}")
            return sorted(["gpt-3.5-turbo", "gpt-4", "gpt-4-turbo-preview", "dall-e-3"])
    
    def generate_chat_completion(self, messages, model, temperature=0.7, max_tokens=None):
        params = {
            'model': model,
            'messages': messages,
            'temperature': temperature
        }
        
        if max_tokens and max_tokens > 0:
            params['max_tokens'] = max_tokens
        
        response = self.client.chat.completions.create(**params)
        return response.choices[0].message.content
    
    def generate_image(self, prompt, chat_id):
        response = self.client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            n=1,
        )
        
        # Get the image URL
        image_url = response.data[0].url
        
        # Download the image
        images_dir = Path('history') / chat_id.replace('.json', '') / 'images'
        images_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate unique filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        image_path = images_dir / f"dalle_{timestamp}.png"
        
        # Download and save image
        response = requests.get(image_url)
        image_path.write_bytes(response.content)
        
        return f'<img src="{image_path}"/>'
    
    def transcribe_audio(self, audio_file):
        transcript = self.client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            timeout=20
        )
        return transcript.text
    
    def generate_speech(self, text, voice):
        return self.client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text
        )

    # Add a property to access audio functionality
    @property
    def audio(self):
        return self.client.audio

class OpenAIWebSocketProvider:
    def __init__(self):
        self.ws = None
        self.loop = None
        self.current_task = None
        self.is_recording = False
        self.audio_buffer = bytearray()
        
        # Audio configuration
        self.input_sample_rate = 48000  # Input from mic
        self.output_sample_rate = 24000  # Server rate
        self.channels = 1
        self.dtype = np.int16
        self.min_audio_ms = 100
        
    async def ensure_connection(self):
        """Ensure we have an active WebSocket connection"""
        if not self.ws or not self.ws.open:
            api_key = os.getenv('OPENAI_API_KEY')
            if not api_key:
                raise ValueError("OPENAI_API_KEY environment variable not set")
                
            self.ws = await websockets.connect(
                "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview",
                extra_headers={
                    "Authorization": f"Bearer {api_key}",
                    "OpenAI-Beta": "realtime=v1"  # Correct beta header
                }
            )
            print("Connected to server.")
            
            # No need for initial config event - the URL includes the model
            
    async def start_audio_stream(self, callback):
        """Start streaming audio to the API"""
        try:
            await self.ensure_connection()
            
            self.is_recording = True
            
            # Initialize audio output stream with proper settings
            self.output_stream = sd.OutputStream(
                channels=1,
                samplerate=self.output_sample_rate,
                dtype=np.int16,
                blocksize=4800,  # 200ms chunks at 24kHz
                latency='low'
            )
            self.output_stream.start()
            
            # Find the device index for the selected microphone
            devices = sd.query_devices()
            device_idx = None
            for i, device in enumerate(devices):
                if device['name'] == self.microphone and device['max_input_channels'] > 0:
                    device_idx = i
                    break
            
            # If selected microphone not found, use default
            if device_idx is None:
                device_idx = sd.default.device[0]
            
            # Query device capabilities
            device_info = sd.query_devices(device_idx, 'input')
            if device_info is not None:
                # Use the device's supported sample rate
                supported_sample_rate = int(device_info['default_samplerate'])
            else:
                supported_sample_rate = 24000  # fallback
            
            # Start audio input stream with specific format
            stream = sd.InputStream(
                device=device_idx,
                channels=1,
                samplerate=supported_sample_rate,
                dtype=np.float32,
                blocksize=int(supported_sample_rate * 0.2),  # 200ms chunks
                callback=self.audio_callback
            )
            
            with stream:
                print(f"Started audio input stream: {supported_sample_rate}Hz, 1 channels")
                print(f"Using microphone: {devices[device_idx]['name']}")
                print(f"Resampling from {self.input_sample_rate}Hz to {self.output_sample_rate}Hz")
                
                while self.is_recording:
                    try:
                        message = await self.ws.recv()
                        if isinstance(message, str):
                            response = json.loads(message)
                            
                            # Only log non-heartbeat messages
                            if response.get("type") != "heartbeat":
                                print("Received event:", json.dumps(response, indent=2))
                            
                            if "text" in response:
                                print(f"Received text: {response['text']}")
                                GLib.idle_add(callback, response["text"])
                            elif response.get("type") == "response.audio.delta":
                                try:
                                    # Get the audio delta data
                                    audio_bytes = base64.b64decode(response["delta"])
                                    print(f"Received audio delta: {len(audio_bytes)} bytes")
                                    
                                    # Convert to numpy array
                                    audio_data = np.frombuffer(audio_bytes, dtype=np.int16)
                                    
                                    # Ensure audio is in correct shape for playback
                                    if audio_data.ndim == 1:
                                        audio_data = audio_data.reshape(-1, 1)
                                    
                                    # Write to output stream
                                    self.output_stream.write(audio_data)
                                    print(f"Played audio chunk: shape={audio_data.shape}, dtype={audio_data.dtype}")
                                except Exception as e:
                                    print(f"Error playing audio delta: {e}")
                                    import traceback
                                    traceback.print_exc()
                            elif response.get("type") == "speech.started":
                                print("Speech started")
                            elif response.get("type") == "speech.ended":
                                print("Speech ended")
                            elif response.get("type") == "error":
                                print(f"Error from server: {response}")
                                if response.get("error", {}).get("code") != "end_of_speech":
                                    break
                            elif "audio" in response:  # Audio data in base64
                                try:
                                    # Decode base64 audio data
                                    audio_bytes = base64.b64decode(response["audio"])
                                    print(f"Received audio data: {len(audio_bytes)} bytes")
                                    
                                    # Convert to numpy array and ensure correct format
                                    audio_data = np.frombuffer(audio_bytes, dtype=np.int16)
                                    
                                    # Ensure audio is in correct shape for playback
                                    if audio_data.ndim == 1:
                                        audio_data = audio_data.reshape(-1, 1)
                                    
                                    # Write to output stream
                                    self.output_stream.write(audio_data)
                                    print(f"Played audio chunk: shape={audio_data.shape}, dtype={audio_data.dtype}")
                                except Exception as e:
                                    print(f"Error playing audio: {e}")
                                    import traceback
                                    traceback.print_exc()
                        
                    except websockets.exceptions.ConnectionClosed as e:
                        print(f"WebSocket closed with code {e.code}: {e.reason}")
                        if not self.is_recording:  # Only break if we're stopping
                            break
                        # Try to reconnect
                        try:
                            await self.ensure_connection()
                            continue
                        except:
                            break
                    except Exception as e:
                        print(f"Error processing message: {e}")
                        if not self.is_recording:
                            break
                        
        except Exception as e:
            print(f"Error in audio stream: {e}")
            GLib.idle_add(callback, f"\nError: {str(e)}")
        finally:
            self.is_recording = False
            if hasattr(self, 'output_stream'):
                self.output_stream.stop()
                self.output_stream.close()
            print("Audio streaming stopped")

    def audio_callback(self, indata, frames, time, status):
        """Callback for audio input"""
        if status:
            print(f"Audio input status: {status}")
            
        if self.ws and self.ws.open and self.is_recording:
            try:
                # Normalize and scale the audio data
                audio_data = indata.copy()
                audio_data = audio_data.flatten()
                
                # Resample from 48kHz to 24kHz
                resampled_size = int(len(audio_data) * self.output_sample_rate / self.input_sample_rate)
                resampled_data = np.interp(
                    np.linspace(0, len(audio_data), resampled_size, endpoint=False),
                    np.arange(len(audio_data)),
                    audio_data
                )
                
                # Convert to int16 with proper scaling
                audio_data = np.clip(resampled_data * 32767, -32768, 32767)
                audio_bytes = audio_data.astype(np.int16).tobytes()
                
                # Add to buffer
                self.audio_buffer.extend(audio_bytes)
                
                # Calculate buffer duration in ms
                buffer_duration_ms = (len(self.audio_buffer) / 2) * 1000 / self.output_sample_rate
                
                # Send audio data if we have enough
                if buffer_duration_ms >= self.min_audio_ms:
                    print(f"Buffer size: {len(self.audio_buffer)} bytes, {buffer_duration_ms:.1f}ms at {self.output_sample_rate}Hz")
                    
                    # Just send append - let server handle VAD
                    message = {
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(bytes(self.audio_buffer)).decode('utf-8')
                    }
                    
                    future = asyncio.run_coroutine_threadsafe(
                        self.ws.send(json.dumps(message)),
                        self.loop
                    )
                    future.add_done_callback(lambda f: self._handle_send_result(f))
                    
                    # Clear buffer after sending
                    self.audio_buffer = bytearray()
                
            except Exception as e:
                print(f"Error in audio callback: {e}")
                import traceback
                traceback.print_exc()

    def _handle_send_result(self, future):
        """Handle the result of sending audio data"""
        try:
            future.result()  # Check for errors
        except Exception as e:
            print(f"Error sending audio data: {e}")

    def start_streaming(self, callback):
        """Start streaming audio in a background task"""
        if self.loop is None:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            
        if self.current_task:
            self.current_task.cancel()
            
        self.current_task = self.loop.create_task(
            self.start_audio_stream(callback)
        )
        
        # Run the event loop in a separate thread
        def run_loop():
            self.loop.run_forever()
            
        threading.Thread(target=run_loop, daemon=True).start()

    def stop_streaming(self):
        """Stop audio streaming"""
        print("Stopping audio stream...")
        self.is_recording = False
        
        if self.loop and self.ws and self.ws.open:
            try:
                # Just close the connection - no need to send end event
                future = asyncio.run_coroutine_threadsafe(
                    self.ws.close(),
                    self.loop
                )
                future.result(timeout=1.0)  # Wait for close to complete
            except Exception as e:
                print(f"Error during cleanup: {e}")
        
        if self.current_task:
            self.current_task.cancel()
            self.current_task = None
            
        if self.loop:
            try:
                self.loop.stop()
            except Exception as e:
                print(f"Error stopping loop: {e}")
            self.loop = None
            
        self.ws = None

# Factory function to get the appropriate provider
def get_ai_provider(provider_name: str) -> AIProvider:
    providers = {
        'openai': OpenAIProvider,
        # Add other providers here as they're implemented
    }
    
    provider_class = providers.get(provider_name)
    if not provider_class:
        raise ValueError(f"Unknown AI provider: {provider_name}")
    
    return provider_class() 