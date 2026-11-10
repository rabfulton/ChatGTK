"""
Realtime voice (WebSocket) clients.

This package is intended to host provider-specific realtime implementations
(OpenAI, xAI, etc.) plus shared plumbing (audio, background event loop, event
normalization) as we refactor `OpenAIWebSocketProvider` out of `ai_providers.py`.
"""

__all__ = ["OpenAIWebSocketProvider"]


def __getattr__(name):
    """Load the audio engine only when its provider class is requested."""
    if name == "OpenAIWebSocketProvider":
        from .openai import OpenAIWebSocketProvider

        return OpenAIWebSocketProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

