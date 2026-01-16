from __future__ import annotations

OPENAI_REALTIME_VOICES = [
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "sage",
    "shimmer",
    "verse",
    "marin",
    "cedar",
]

GROK_REALTIME_VOICES = ["Ara", "Rex", "Sal", "Eve", "Leo"]


def get_realtime_voices(provider_id: str) -> list[str]:
    provider_id = (provider_id or "").lower()
    if provider_id in ("grok", "xai"):
        return list(GROK_REALTIME_VOICES)
    return list(OPENAI_REALTIME_VOICES)

