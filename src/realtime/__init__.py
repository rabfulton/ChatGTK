"""
Realtime voice (WebSocket) clients.

This package is intended to host provider-specific realtime implementations
(OpenAI, xAI, etc.) plus shared plumbing (audio, background event loop, event
normalization) as we refactor `OpenAIWebSocketProvider` out of `ai_providers.py`.
"""

from .openai import OpenAIWebSocketProvider

