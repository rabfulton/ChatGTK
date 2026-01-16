from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Protocol


@dataclass(frozen=True)
class RealtimeAudioConfig:
    input_sample_rate: int = 48000
    output_sample_rate: int = 24000
    channels: int = 1
    min_audio_ms: int = 75


class CallbackScheduler(Protocol):
    def __call__(self, callback: Callable, *args) -> None: ...


class RealtimeClient(Protocol):
    on_user_transcript: Optional[Callable[[str], None]]
    on_assistant_transcript: Optional[Callable[[str], None]]

    def connect(
        self,
        model: Optional[str] = None,
        system_message: Optional[str] = None,
        temperature: Optional[float] = None,
        voice: Optional[str] = None,
        api_key: Optional[str] = None,
        realtime_prompt: Optional[str] = None,
        mute_mic_during_playback: Optional[bool] = None,
    ) -> bool: ...

    def disconnect(self) -> None: ...

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
    ) -> None: ...

    def stop_streaming(self) -> None: ...

    def send_text(self, text: str, callback) -> None: ...

