"""
Audio service for handling recording, transcription, and text-to-speech.
"""

import os
import threading
import tempfile
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
    
    def _emit(self, event_type: EventType, **data) -> None:
        """Emit an event if event bus is configured."""
        if self._event_bus:
            self._event_bus.publish(Event(type=event_type, data=data, source='audio_service'))
    
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
    ) -> Optional[Path]:
        """
        Synthesize speech using OpenAI TTS.
        
        Returns path to audio file or None on error.
        """
        try:
            audio_data = provider.generate_speech(text, voice, model=model)
            return self._save_tts_audio(audio_data, chat_id, "openai_tts")
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
    ) -> Optional[Path]:
        """
        Synthesize speech using Gemini TTS.
        
        Returns path to audio file or None on error.
        """
        try:
            audio_data = provider.generate_speech(text, voice)
            return self._save_tts_audio(audio_data, chat_id, "gemini_tts")
        except Exception as e:
            print(f"Gemini TTS error: {e}")
            self._emit(EventType.ERROR_OCCURRED, error=str(e), context='tts_gemini')
            return None
    
    def synthesize_audio_preview(
        self,
        text: str,
        provider: Any,
        model_id: str,
        prompt_template: str,
        chat_id: Optional[str] = None,
    ) -> Optional[Path]:
        """
        Synthesize speech using audio-preview models.
        
        Returns path to audio file or None on error.
        """
        try:
            prompt = prompt_template.replace("{text}", text) if "{text}" in prompt_template else text
            audio_data = provider.generate_audio_response(prompt, model=model_id)
            return self._save_tts_audio(audio_data, chat_id, "audio_preview")
        except Exception as e:
            print(f"Audio preview TTS error: {e}")
            self._emit(EventType.ERROR_OCCURRED, error=str(e), context='tts_audio_preview')
            return None
    
    def synthesize_custom_tts(
        self,
        text: str,
        provider: Any,
        chat_id: Optional[str] = None,
    ) -> Optional[Path]:
        """
        Synthesize speech using custom TTS provider.
        
        Returns path to audio file or None on error.
        """
        try:
            audio_data = provider.generate_speech(text, voice=provider.voice or "default")
            return self._save_tts_audio(audio_data, chat_id, "custom_tts")
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
    
    def stop_playback(self) -> None:
        """Stop current playback."""
        try:
            sd.stop()
            if self._current_playback_stop:
                self._current_playback_stop.set()
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
        **kwargs
            Additional arguments for synthesis (voice, model, etc.)
            
        Returns
        -------
        bool
            True if successful.
        """
        # Check for stop before starting
        if stop_event and stop_event.is_set():
            return False
        
        # Synthesize based on provider type
        audio_path = None
        
        if provider_type == 'openai':
            audio_path = self.synthesize_openai_tts(
                text, provider,
                voice=kwargs.get('voice', 'alloy'),
                model=kwargs.get('model', 'tts-1'),
                chat_id=chat_id,
            )
        elif provider_type == 'gemini':
            audio_path = self.synthesize_gemini_tts(
                text, provider,
                voice=kwargs.get('voice', 'Kore'),
                chat_id=chat_id,
            )
        elif provider_type == 'audio_preview':
            audio_path = self.synthesize_audio_preview(
                text, provider,
                model_id=kwargs.get('model_id', 'gpt-4o-audio-preview'),
                prompt_template=kwargs.get('prompt_template', '{text}'),
                chat_id=chat_id,
            )
        elif provider_type == 'custom':
            audio_path = self.synthesize_custom_tts(
                text, provider,
                chat_id=chat_id,
            )
        
        if not audio_path:
            return False
        
        # Check for stop before playing
        if stop_event and stop_event.is_set():
            return False
        
        return self.play_audio(audio_path, stop_event)
