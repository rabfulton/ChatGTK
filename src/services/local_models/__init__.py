"""
Local Models service module.

Provides backends for non-OpenAI-compatible local LLM providers (e.g., Ollama)
and in-process model backends (e.g., sherpa-onnx for audio).
"""

from .types import LocalModelEntry, LocalModelHealth, LocalModelCapabilities
from .backend import LocalModelBackend
from .ollama_backend import OllamaBackend
from .loader import load_local_models, save_local_models

__all__ = [
    "LocalModelEntry",
    "LocalModelHealth", 
    "LocalModelCapabilities",
    "LocalModelBackend",
    "OllamaBackend",
    "load_local_models",
    "save_local_models",
]
