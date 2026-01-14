"""
Audio service for handling recording, transcription, and text-to-speech.
"""

import os
import re
import hashlib
import subprocess
import threading
import tempfile
import time
from pathlib import Path
from typing import Optional, Dict, Any, Callable, Tuple
from datetime import datetime

import numpy as np
import sounddevice as sd
import soundfile as sf

from config import HISTORY_DIR
from events import EventBus, EventType, Event


class AudioService:
    """
    Service for managing audio operations.
    
    Handles recording, transcription, TTS synthesis, and playback.
    GTK-free - can be used with any UI framework.
    """
    
    def __init__(self, event_bus: Optional[EventBus] = None):
        self._event_bus = event_bus
        self._current_playback_stop = None
        self._current_process = None
    
    def _emit(self, event_type: EventType, **data) -> None:
        """Emit an event if event bus is configured."""
        if self._event_bus:
            self._event_bus.publish(Event(type=event_type, data=data, source='audio_service'))
    
    # -------------------------------------------------------------------------
    # Text Cleaning and Caching
    # -------------------------------------------------------------------------
    
    def _clean_tts_text(self, text: str) -> str:
        """Remove audio_file tags and clean text for TTS."""
        return re.sub(r'<audio_file>.*?</audio_file>', '', text).strip()
    
    def _get_cache_path(
        self,
        text: str,
        chat_id: str,
        provider: str,
        voice: str,
        extra_key: str = "",
    ) -> Optional[Path]:
        """Get cache path for TTS audio."""
        if not chat_id:
            return None
        
        cache_key = f"{text}_{voice}_{extra_key}" if extra_key else f"{text}_{voice}"
        text_hash = hashlib.md5(cache_key.encode()).hexdigest()[:8]
        
        # Get audio directory - handle .json suffix
        chat_dir_name = chat_id.replace('.json', '')
        audio_dir = Path(HISTORY_DIR) / chat_dir_name / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        
        safe_provider = "".join(c if c.isalnum() else "_" for c in provider)
        safe_voice = "".join(c if c.isalnum() else "_" for c in voice)
        return audio_dir / f"{safe_provider}_{safe_voice}_{text_hash}.wav"
    
    def _check_cache(self, cache_path: Optional[Path]) -> bool:
        """Check if cached audio exists."""
        return cache_path is not None and cache_path.exists()
    
    # -------------------------------------------------------------------------
    # Recording
    # -------------------------------------------------------------------------
    
    def record_audio(
        self,
        microphone: Any,
        stop_event: threading.Event,
    ) -> Tuple[Optional[np.ndarray], Optional[int]]:
        """
        Record audio from microphone until stop_event is set.
        
        Parameters
        ----------
        microphone : Any
            Name or index of input device.
        stop_event : threading.Event
            Event to signal recording should stop.
            
        Returns
        -------
        Tuple[Optional[np.ndarray], Optional[int]]
            (recording_data, sample_rate) or (None, None) on error.
        """
        try:
            recorded_chunks = []
            os.environ['AUDIODEV'] = 'pulse'
            
            device_info = sd.query_devices(microphone, 'input')
            if device_info is None:
                print(f"Warning: Could not find microphone '{microphone}', using default")
                device_info = sd.query_devices(sd.default.device[0], 'input')
            
            sample_rate = int(device_info['default_samplerate'])
            
            def audio_callback(indata, frames, time, status):
                if status:
                    print(f'Status: {status}')
                recorded_chunks.append(indata.copy())
            
            stream = sd.InputStream(
                device=microphone,
                channels=1,
                samplerate=sample_rate,
                callback=audio_callback,
                dtype=np.float32
            )
            
            self._emit(EventType.RECORDING_STARTED, microphone=str(microphone))
            
            with stream:
                print(f"Recording started at {sample_rate} Hz")
                while stop_event.is_set():
                    sd.sleep(100)
            
            self._emit(EventType.RECORDING_STOPPED)
            
            if recorded_chunks:
                recording = np.concatenate(recorded_chunks, axis=0)
                return recording, sample_rate
            
            return None, None
            
        except Exception as e:
            print(f"Error recording audio: {e}")
            self._emit(EventType.ERROR_OCCURRED, error=str(e), context='recording')
            return None, None
    
    def save_recording(
        self,
        recording: np.ndarray,
        sample_rate: int,
        path: Optional[Path] = None,
    ) -> Path:
        """Save recording to file, return path."""
        if path is None:
            path = Path(tempfile.gettempdir()) / "voice_input.wav"
        
        if len(recording.shape) == 1:
            recording = recording.reshape(-1, 1)
        
        sf.write(str(path), recording, sample_rate)
        return path
    
    # -------------------------------------------------------------------------
    # Transcription
    # -------------------------------------------------------------------------
    
    def transcribe(
        self,
        audio_path: Path,
        provider: Any,
        model: str = "whisper-1",
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> Optional[str]:
        """
        Transcribe audio file to text.
        
        Parameters
        ----------
        audio_path : Path
            Path to audio file.
        provider : Any
            AI provider with transcribe_audio method.
        model : str
            Transcription model.
        base_url : Optional[str]
            Custom base URL for API.
        api_key : Optional[str]
            Custom API key.
            
        Returns
        -------
        Optional[str]
            Transcribed text or None on error.
        """
        try:
            with open(audio_path, "rb") as audio_file:
                transcript = provider.transcribe_audio(
                    audio_file,
                    model=model,
                    prompt="Please transcribe this audio file. Return only the transcribed text.",
                    base_url=base_url,
                    api_key=api_key,
                )
            
            self._emit(EventType.TRANSCRIPTION_COMPLETE, text=transcript[:100] if transcript else '')
            return transcript
            
        except Exception as e:
            print(f"Transcription error: {e}")
            self._emit(EventType.ERROR_OCCURRED, error=str(e), context='transcription')
            return None
    
    # -------------------------------------------------------------------------
    # TTS Synthesis
    # -------------------------------------------------------------------------
    
    def synthesize_openai_tts(
        self,
        text: str,
        provider: Any,
        voice: str = "alloy",
        model: str = "tts-1",
        chat_id: Optional[str] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> Optional[Path]:
        """
        Synthesize speech using OpenAI TTS with streaming.
        
        Returns path to audio file or None on error.
        """
        try:
            # Check cache first
            cache_path = self._get_cache_path(text, chat_id, f"openai_{model}", voice) if chat_id else None
            if self._check_cache(cache_path):
                return cache_path
            
            # Determine output path
            if cache_path:
                audio_path = cache_path
            else:
                text_hash = hashlib.md5(text.encode()).hexdigest()[:8]
                audio_path = Path(tempfile.gettempdir()) / f"tts_openai_{text_hash}.wav"
            
            # Stream audio to file
            with provider.audio.speech.with_streaming_response.create(
                model=model,
                voice=voice,
                input=text
            ) as response:
                with open(audio_path, 'wb') as f:
                    for chunk in response.iter_bytes():
                        if stop_event and stop_event.is_set():
                            audio_path.unlink(missing_ok=True)
                            return None
                        f.write(chunk)
            
            self._emit(EventType.TTS_COMPLETE, audio_path=str(audio_path))
            return audio_path
        except Exception as e:
            print(f"OpenAI TTS error: {e}")
            self._emit(EventType.ERROR_OCCURRED, error=str(e), context='tts_openai')
            return None
    
    def synthesize_gemini_tts(
        self,
        text: str,
        provider: Any,
        voice: str = "Kore",
        chat_id: Optional[str] = None,
        prompt_template: str = "",
        stop_event: Optional[threading.Event] = None,
    ) -> Optional[Path]:
        """
        Synthesize speech using Gemini TTS.
        
        Returns path to audio file or None on error.
        """
        try:
            # Apply prompt template if provided
            if prompt_template and '{text}' in prompt_template:
                prompt_text = prompt_template.replace('{text}', text)
            else:
                prompt_text = text
            
            # Check cache
            extra_key = prompt_template if prompt_template else ""
            cache_path = self._get_cache_path(prompt_text, chat_id, "gemini", voice, extra_key) if chat_id else None
            if self._check_cache(cache_path):
                return cache_path
            
            if stop_event and stop_event.is_set():
                return None
            
            # Determine output path
            if cache_path:
                audio_path = cache_path
            else:
                text_hash = hashlib.md5(f"{prompt_text}_{voice}".encode()).hexdigest()[:8]
                audio_path = Path(tempfile.gettempdir()) / f"tts_gemini_{text_hash}.wav"
            
            audio_data = provider.generate_speech(prompt_text, voice)
            
            if stop_event and stop_event.is_set():
                return None
            
            with open(audio_path, 'wb') as f:
                f.write(audio_data)
            
            self._emit(EventType.TTS_COMPLETE, audio_path=str(audio_path))
            return audio_path
        except Exception as e:
            print(f"Gemini TTS error: {e}")
            self._emit(EventType.ERROR_OCCURRED, error=str(e), context='tts_gemini')
            return None
    
    def synthesize_audio_preview(
        self,
        text: str,
        provider: Any,
        model_id: str,
        voice: str = "alloy",
        prompt_template: str = 'Please say the following verbatim: "{text}"',
        chat_id: Optional[str] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> Optional[Path]:
        """
        Synthesize speech using audio-preview models.
        
        Returns path to audio file or None on error.
        """
        import base64
        try:
            # Build prompt
            prompt = prompt_template.replace("{text}", text) if "{text}" in prompt_template else text
            
            # Check cache
            extra_key = f"{model_id}_{prompt_template}"
            cache_path = self._get_cache_path(prompt, chat_id, "audio_preview", voice, extra_key) if chat_id else None
            if self._check_cache(cache_path):
                return cache_path
            
            if stop_event and stop_event.is_set():
                return None
            
            # Determine output path
            if cache_path:
                audio_path = cache_path
            else:
                text_hash = hashlib.md5(f"{prompt}_{voice}_{model_id}".encode()).hexdigest()[:8]
                audio_path = Path(tempfile.gettempdir()) / f"tts_audio_preview_{text_hash}.wav"
            
            response = provider.client.chat.completions.create(
                model=model_id,
                modalities=["text", "audio"],
                audio={"voice": voice, "format": "wav"},
                messages=[{"role": "user", "content": prompt}]
            )
            
            if stop_event and stop_event.is_set():
                return None
            
            if hasattr(response.choices[0].message, 'audio') and response.choices[0].message.audio:
                audio_data = response.choices[0].message.audio.data
                audio_bytes = base64.b64decode(audio_data)
                
                with open(audio_path, 'wb') as f:
                    f.write(audio_bytes)
                
                self._emit(EventType.TTS_COMPLETE, audio_path=str(audio_path))
                return audio_path
            else:
                print("TTS: No audio in response from audio-preview model")
                return None
        except Exception as e:
            print(f"Audio preview TTS error: {e}")
            self._emit(EventType.ERROR_OCCURRED, error=str(e), context='tts_audio_preview')
            return None
    
    def synthesize_custom_tts(
        self,
        text: str,
        provider: Any,
        voice: str = "default",
        model_id: str = "custom",
        chat_id: Optional[str] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> Optional[Path]:
        """
        Synthesize speech using custom TTS provider.
        
        Returns path to audio file or None on error.
        """
        try:
            # Check cache
            cache_path = self._get_cache_path(text, chat_id, f"custom_{model_id}", voice) if chat_id else None
            if self._check_cache(cache_path):
                return cache_path
            
            if stop_event and stop_event.is_set():
                return None
            
            # Determine output path
            if cache_path:
                audio_path = cache_path
            else:
                text_hash = hashlib.md5(f"{text}_{model_id}_{voice}".encode()).hexdigest()[:8]
                audio_path = Path(tempfile.gettempdir()) / f"tts_custom_{text_hash}.wav"
            
            audio_data = provider.generate_speech(text, voice)
            
            if stop_event and stop_event.is_set():
                return None
            
            with open(audio_path, 'wb') as f:
                f.write(audio_data)
            
            self._emit(EventType.TTS_COMPLETE, audio_path=str(audio_path))
            return audio_path
        except Exception as e:
            print(f"Custom TTS error: {e}")
            self._emit(EventType.ERROR_OCCURRED, error=str(e), context='tts_custom')
            return None
    
    def _save_tts_audio(
        self,
        audio_data: bytes,
        chat_id: Optional[str],
        prefix: str,
    ) -> Optional[Path]:
        """Save TTS audio data to file."""
        if not audio_data:
            return None
        
        # Determine directory
        if chat_id:
            audio_dir = Path(HISTORY_DIR) / chat_id.replace('.json', '') / 'audio'
        else:
            audio_dir = Path(tempfile.gettempdir())
        
        audio_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Detect format from header
        if audio_data[:4] == b'RIFF':
            ext = '.wav'
        elif audio_data[:3] == b'ID3' or audio_data[:2] == b'\xff\xfb':
            ext = '.mp3'
        else:
            ext = '.wav'
        
        audio_path = audio_dir / f"{prefix}_{timestamp}{ext}"
        
        with open(audio_path, 'wb') as f:
            f.write(audio_data)
        
        self._emit(EventType.TTS_COMPLETE, audio_path=str(audio_path))
        return audio_path
    
    # -------------------------------------------------------------------------
    # Playback
    # -------------------------------------------------------------------------
    
    def play_audio(
        self,
        audio_path: Path,
        stop_event: Optional[threading.Event] = None,
        callback: Optional[Callable[[], None]] = None,
    ) -> bool:
        """
        Play audio file. Blocks until complete or stopped.
        
        Parameters
        ----------
        audio_path : Path
            Path to audio file.
        stop_event : Optional[threading.Event]
            Event to signal playback should stop.
        callback : Optional[Callable]
            Called when playback completes.
            
        Returns
        -------
        bool
            True if played successfully.
        """
        try:
            self._emit(EventType.PLAYBACK_STARTED, audio_path=str(audio_path))
            
            data, sample_rate = sf.read(str(audio_path))
            
            # Track current stop event for external stop
            self._current_playback_stop = stop_event
            
            # Play with ability to stop
            sd.play(data, sample_rate)
            
            while sd.get_stream().active:
                if stop_event and stop_event.is_set():
                    sd.stop()
                    break
                sd.sleep(100)
            
            sd.wait()
            
            self._current_playback_stop = None
            self._emit(EventType.PLAYBACK_STOPPED, audio_path=str(audio_path))
            
            if callback:
                callback()
            
            return True
            
        except Exception as e:
            print(f"Playback error: {e}")
            self._emit(EventType.ERROR_OCCURRED, error=str(e), context='playback')
            return False
    
    def play_audio_subprocess(
        self,
        audio_path: Path,
        stop_event: Optional[threading.Event] = None,
    ) -> bool:
        """Play audio using paplay subprocess."""
        try:
            self._emit(EventType.PLAYBACK_STARTED, audio_path=str(audio_path))
            
            self._current_process = subprocess.Popen(['paplay', str(audio_path)])
            
            while self._current_process.poll() is None:
                if stop_event and stop_event.is_set():
                    self._current_process.terminate()
                    self._current_process = None
                    return False
                time.sleep(0.1)
            
            self._current_process = None
            self._emit(EventType.PLAYBACK_STOPPED, audio_path=str(audio_path))
            return True
        except Exception as e:
            print(f"Subprocess playback error: {e}")
            self._emit(EventType.ERROR_OCCURRED, error=str(e), context='playback')
            return False
    
    def stop_playback(self) -> None:
        """Stop current playback."""
        try:
            sd.stop()
            if self._current_playback_stop:
                self._current_playback_stop.set()
            if self._current_process:
                self._current_process.terminate()
                self._current_process = None
        except Exception as e:
            print(f"Error stopping playback: {e}")
    
    # -------------------------------------------------------------------------
    # Convenience: Synthesize and Play
    # -------------------------------------------------------------------------
    
    def synthesize_and_play(
        self,
        text: str,
        provider_type: str,
        provider: Any,
        stop_event: Optional[threading.Event] = None,
        chat_id: Optional[str] = None,
        use_subprocess: bool = True,
        **kwargs,
    ) -> bool:
        """
        Synthesize speech and play it.
        
        Parameters
        ----------
        text : str
            Text to synthesize.
        provider_type : str
            One of: 'openai', 'gemini', 'audio_preview', 'custom'
        provider : Any
            The AI provider instance.
        stop_event : Optional[threading.Event]
            Event to signal stop.
        chat_id : Optional[str]
            Chat ID for caching audio.
        use_subprocess : bool
            Use paplay subprocess instead of sounddevice.
        **kwargs
            Additional arguments for synthesis (voice, model, etc.)
            
        Returns
        -------
        bool
            True if successful.
        """
        # Clean text
        clean_text = self._clean_tts_text(text)
        if not clean_text:
            return True  # Nothing to say
        
        # Check for stop before starting
        if stop_event and stop_event.is_set():
            return False
        
        # Synthesize based on provider type
        audio_path = None
        
        if provider_type == 'openai':
            audio_path = self.synthesize_openai_tts(
                clean_text, provider,
                voice=kwargs.get('voice', 'alloy'),
                model=kwargs.get('model', 'tts-1'),
                chat_id=chat_id,
                stop_event=stop_event,
            )
        elif provider_type == 'gemini':
            audio_path = self.synthesize_gemini_tts(
                clean_text, provider,
                voice=kwargs.get('voice', 'Kore'),
                chat_id=chat_id,
                prompt_template=kwargs.get('prompt_template', ''),
                stop_event=stop_event,
            )
        elif provider_type == 'audio_preview':
            audio_path = self.synthesize_audio_preview(
                clean_text, provider,
                model_id=kwargs.get('model_id', 'gpt-4o-audio-preview'),
                voice=kwargs.get('voice', 'alloy'),
                prompt_template=kwargs.get('prompt_template', 'Please say the following verbatim: "{text}"'),
                chat_id=chat_id,
                stop_event=stop_event,
            )
        elif provider_type == 'custom':
            audio_path = self.synthesize_custom_tts(
                clean_text, provider,
                voice=kwargs.get('voice', ''),
                model_id=kwargs.get('model_id', 'custom'),
                chat_id=chat_id,
                stop_event=stop_event,
            )
        
        if not audio_path:
            return False
        
        # Check for stop before playing
        if stop_event and stop_event.is_set():
            return False
        
        # Play
        if use_subprocess:
            return self.play_audio_subprocess(audio_path, stop_event)
        else:
            return self.play_audio(audio_path, stop_event)
