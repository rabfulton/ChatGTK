"""
Audio service for handling recording, transcription, and text-to-speech.
"""

import os
import threading
from pathlib import Path
from typing import Optional, Dict, Any, Callable
from datetime import datetime

from repositories import ChatHistoryRepository, SettingsRepository
from config import HISTORY_DIR
from events import EventBus, EventType, Event


class AudioService:
    """
    Service for managing audio operations.
    
    This service handles audio recording, transcription, text-to-speech synthesis,
    and audio playback coordination.
    """
    
    def __init__(
        self,
        chat_history_repo: ChatHistoryRepository,
        settings_repo: SettingsRepository,
        event_bus: Optional[EventBus] = None,
    ):
        """
        Initialize the audio service.
        
        Parameters
        ----------
        chat_history_repo : ChatHistoryRepository
            Repository for accessing chat directories.
        settings_repo : SettingsRepository
            Repository for audio settings.
        event_bus : Optional[EventBus]
            Event bus for publishing events.
        """
        self._chat_history_repo = chat_history_repo
        self._settings_repo = settings_repo
        self._event_bus = event_bus
        self._recording_thread: Optional[threading.Thread] = None
        self._playback_thread: Optional[threading.Thread] = None
        self._stop_recording = False
        self._stop_playback = False
    
    def _emit(self, event_type: EventType, **data) -> None:
        """Emit an event if event bus is configured."""
        if self._event_bus:
            self._event_bus.publish(Event(type=event_type, data=data, source='audio_service'))
    
    def _get_chat_audio_dir(self, chat_id: str) -> Path:
        """
        Get the audio directory for a chat.
        
        Parameters
        ----------
        chat_id : str
            The chat identifier.
            
        Returns
        -------
        Path
            Path to the chat's audio directory.
        """
        chat_dir = Path(HISTORY_DIR) / chat_id
        audio_dir = chat_dir / 'audio'
        audio_dir.mkdir(parents=True, exist_ok=True)
        return audio_dir
    
    def record_audio(
        self,
        duration: Optional[float] = None,
        chat_id: Optional[str] = None,
        callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """
        Record audio from the microphone.
        
        Parameters
        ----------
        duration : Optional[float]
            Recording duration in seconds. If None, records until stopped.
        chat_id : Optional[str]
            Chat ID for organizing recorded audio.
        callback : Optional[Callable[[str], None]]
            Callback function called when recording completes with file path.
            
        Returns
        -------
        Dict[str, Any]
            Dictionary containing:
            - 'success': Whether recording started successfully
            - 'audio_path': Path where audio will be saved
            - 'error': Error message (if failed)
        """
        try:
            import sounddevice as sd
            import soundfile as sf
            import numpy as np
            
            # Get recording settings
            sample_rate = self._settings_repo.get('AUDIO_SAMPLE_RATE', 44100)
            channels = self._settings_repo.get('AUDIO_CHANNELS', 1)
            
            # Determine save location
            if chat_id:
                audio_dir = self._get_chat_audio_dir(chat_id)
            else:
                audio_dir = Path(HISTORY_DIR) / 'temp_audio'
                audio_dir.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            audio_path = audio_dir / f"recording_{timestamp}.wav"
            
            def record_thread():
                """Thread function for recording."""
                try:
                    if duration:
                        # Fixed duration recording
                        recording = sd.rec(
                            int(duration * sample_rate),
                            samplerate=sample_rate,
                            channels=channels,
                            dtype='float32'
                        )
                        sd.wait()
                    else:
                        # Manual stop recording
                        recording_chunks = []
                        chunk_duration = 0.1  # 100ms chunks
                        chunk_samples = int(chunk_duration * sample_rate)
                        
                        with sd.InputStream(
                            samplerate=sample_rate,
                            channels=channels,
                            dtype='float32'
                        ) as stream:
                            while not self._stop_recording:
                                chunk, _ = stream.read(chunk_samples)
                                recording_chunks.append(chunk)
                        
                        recording = np.concatenate(recording_chunks, axis=0)
                    
                    # Save recording
                    sf.write(str(audio_path), recording, sample_rate)
                    
                    # Call callback if provided
                    if callback:
                        callback(str(audio_path))
                        
                except Exception as e:
                    print(f"Error during recording: {e}")
            
            # Start recording thread
            self._stop_recording = False
            self._recording_thread = threading.Thread(target=record_thread, daemon=True)
            self._recording_thread.start()
            
            self._emit(EventType.RECORDING_STARTED, audio_path=str(audio_path), chat_id=chat_id)
            
            return {
                'success': True,
                'audio_path': str(audio_path),
            }
            
        except Exception as e:
            self._emit(EventType.ERROR_OCCURRED, error=str(e), context='recording')
            return {
                'success': False,
                'error': str(e),
            }
    
    def stop_recording(self) -> bool:
        """
        Stop the current recording.
        
        Returns
        -------
        bool
            True if recording was stopped, False if no recording in progress.
        """
        if self._recording_thread and self._recording_thread.is_alive():
            self._stop_recording = True
            self._recording_thread.join(timeout=2.0)
            self._emit(EventType.RECORDING_STOPPED)
            return True
        return False
    
    def transcribe(
        self,
        audio_path: str,
        provider: Any,
        model: Optional[str] = None,
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Transcribe audio to text.
        
        Parameters
        ----------
        audio_path : str
            Path to the audio file.
        provider : Any
            The AI provider instance with transcription capability.
        model : Optional[str]
            The transcription model to use.
        language : Optional[str]
            Language code for transcription (e.g., 'en').
            
        Returns
        -------
        Dict[str, Any]
            Dictionary containing:
            - 'success': Whether transcription succeeded
            - 'text': Transcribed text (if successful)
            - 'error': Error message (if failed)
        """
        try:
            # Check if provider supports transcription
            if not hasattr(provider, 'transcribe_audio'):
                return {
                    'success': False,
                    'error': 'Provider does not support transcription',
                }
            
            # Transcribe audio
            kwargs = {}
            if model:
                kwargs['model'] = model
            if language:
                kwargs['language'] = language
            
            text = provider.transcribe_audio(audio_path, **kwargs)
            
            self._emit(EventType.TRANSCRIPTION_COMPLETE, text=text, audio_path=audio_path)
            
            return {
                'success': True,
                'text': text,
            }
            
        except Exception as e:
            self._emit(EventType.ERROR_OCCURRED, error=str(e), context='transcription')
            return {
                'success': False,
                'error': str(e),
            }
    
    def synthesize_speech(
        self,
        text: str,
        provider: Any,
        chat_id: Optional[str] = None,
        voice: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Synthesize speech from text.
        
        Parameters
        ----------
        text : str
            The text to synthesize.
        provider : Any
            The AI provider instance with TTS capability.
        chat_id : Optional[str]
            Chat ID for organizing audio files.
        voice : Optional[str]
            Voice to use for synthesis.
        model : Optional[str]
            TTS model to use.
            
        Returns
        -------
        Dict[str, Any]
            Dictionary containing:
            - 'success': Whether synthesis succeeded
            - 'audio_path': Path to synthesized audio (if successful)
            - 'error': Error message (if failed)
        """
        try:
            # Get TTS settings
            if voice is None:
                voice = self._settings_repo.get('TTS_VOICE', 'alloy')
            if model is None:
                model = self._settings_repo.get('TTS_MODEL', 'tts-1')
            
            # Determine save location
            if chat_id:
                audio_dir = self._get_chat_audio_dir(chat_id)
            else:
                audio_dir = Path(HISTORY_DIR) / 'temp_audio'
                audio_dir.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            audio_path = audio_dir / f"tts_{timestamp}.mp3"
            
            # Check if provider supports TTS
            if not hasattr(provider, 'generate_speech'):
                return {
                    'success': False,
                    'error': 'Provider does not support text-to-speech',
                }
            
            # Generate speech
            audio_data = provider.generate_speech(
                text=text,
                voice=voice,
                model=model,
            )
            
            # Save audio data
            if isinstance(audio_data, bytes):
                with open(audio_path, 'wb') as f:
                    f.write(audio_data)
            elif isinstance(audio_data, str):
                # Provider returned a file path
                audio_path = Path(audio_data)
            else:
                return {
                    'success': False,
                    'error': f'Unexpected audio data type: {type(audio_data)}',
                }
            
            self._emit(EventType.TTS_COMPLETE, audio_path=str(audio_path), text=text[:100])
            
            return {
                'success': True,
                'audio_path': str(audio_path),
            }
            
        except Exception as e:
            self._emit(EventType.ERROR_OCCURRED, error=str(e), context='tts')
            return {
                'success': False,
                'error': str(e),
            }
    
    def play_audio(
        self,
        audio_path: str,
        callback: Optional[Callable[[], None]] = None,
    ) -> Dict[str, Any]:
        """
        Play an audio file.
        
        Parameters
        ----------
        audio_path : str
            Path to the audio file.
        callback : Optional[Callable[[], None]]
            Callback function called when playback completes.
            
        Returns
        -------
        Dict[str, Any]
            Dictionary containing:
            - 'success': Whether playback started successfully
            - 'error': Error message (if failed)
        """
        try:
            def playback_thread():
                """Thread function for audio playback."""
                try:
                    # Try using pygame for playback
                    try:
                        import pygame
                        pygame.mixer.init()
                        pygame.mixer.music.load(audio_path)
                        pygame.mixer.music.play()
                        
                        while pygame.mixer.music.get_busy() and not self._stop_playback:
                            pygame.time.Clock().tick(10)
                        
                        pygame.mixer.music.stop()
                        pygame.mixer.quit()
                        
                    except ImportError:
                        # Fallback to system command
                        import subprocess
                        if os.name == 'posix':
                            # Linux/Mac
                            subprocess.run(['aplay' if audio_path.endswith('.wav') else 'mpg123', audio_path])
                        else:
                            # Windows
                            os.startfile(audio_path)
                    
                    self._emit(EventType.PLAYBACK_STOPPED, audio_path=audio_path)
                    
                    # Call callback if provided
                    if callback:
                        callback()
                        
                except Exception as e:
                    print(f"Error during playback: {e}")
            
            # Start playback thread
            self._stop_playback = False
            self._playback_thread = threading.Thread(target=playback_thread, daemon=True)
            self._playback_thread.start()
            
            self._emit(EventType.PLAYBACK_STARTED, audio_path=audio_path)
            
            return {
                'success': True,
            }
            
        except Exception as e:
            self._emit(EventType.ERROR_OCCURRED, error=str(e), context='playback')
            return {
                'success': False,
                'error': str(e),
            }
    
    def stop_playback(self) -> bool:
        """
        Stop the current audio playback.
        
        Returns
        -------
        bool
            True if playback was stopped, False if no playback in progress.
        """
        if self._playback_thread and self._playback_thread.is_alive():
            self._stop_playback = True
            self._playback_thread.join(timeout=2.0)
            return True
        return False
    
    def list_chat_audio(self, chat_id: str) -> list:
        """
        List all audio files for a chat.
        
        Parameters
        ----------
        chat_id : str
            The chat identifier.
            
        Returns
        -------
        list
            List of audio file paths.
        """
        audio_dir = self._get_chat_audio_dir(chat_id)
        
        if not audio_dir.exists():
            return []
        
        audio_files = []
        for file in audio_dir.iterdir():
            if file.is_file() and file.suffix.lower() in ['.wav', '.mp3', '.ogg', '.flac', '.m4a']:
                audio_files.append(str(file))
        
        # Sort by modification time, newest first
        audio_files.sort(key=lambda p: Path(p).stat().st_mtime, reverse=True)
        return audio_files
