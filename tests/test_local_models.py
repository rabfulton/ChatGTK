"""
test_local_models.py – Unit tests for the local_models module.

Tests cover:
- LocalModelEntry and LocalModelCapabilities dataclasses
- LocalModelHealth dataclass
- JSON serialization/deserialization
- OllamaBackend message conversion
"""

import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from unittest.mock import patch, MagicMock

from services.local_models.types import (
    LocalModelEntry,
    LocalModelCapabilities,
    LocalModelHealth,
)


class TestLocalModelCapabilities:
    """Tests for the LocalModelCapabilities dataclass."""

    def test_default_capabilities(self):
        """Default capabilities should all be False."""
        caps = LocalModelCapabilities()
        assert caps.tools is False
        assert caps.vision is False
        assert caps.audio_in is False
        assert caps.audio_out is False

    def test_custom_capabilities(self):
        """Can create capabilities with custom flags."""
        caps = LocalModelCapabilities(tools=True, vision=True)
        assert caps.tools is True
        assert caps.vision is True
        assert caps.audio_in is False


class TestLocalModelEntry:
    """Tests for the LocalModelEntry dataclass."""

    def test_minimal_entry(self):
        """Can create an entry with required fields."""
        entry = LocalModelEntry(
            id="ollama:llama3.2:3b",
            type="chat",
            backend="ollama",
            display_name="Llama 3.2 3B",
        )
        assert entry.id == "ollama:llama3.2:3b"
        assert entry.type == "chat"
        assert entry.backend == "ollama"
        assert entry.enabled is True
        assert entry.config == {}

    def test_entry_with_config(self):
        """Can create an entry with config dict."""
        entry = LocalModelEntry(
            id="ollama:mistral:latest",
            type="chat",
            backend="ollama",
            display_name="Mistral",
            config={
                "base_url": "http://localhost:11434",
                "model": "mistral:latest",
                "keep_alive": "5m",
            },
        )
        assert entry.config["base_url"] == "http://localhost:11434"
        assert entry.config["keep_alive"] == "5m"

    def test_from_dict(self):
        """Can create entry from dictionary."""
        data = {
            "id": "ollama:phi3:mini",
            "type": "chat",
            "backend": "ollama",
            "display_name": "Phi-3 Mini",
            "enabled": True,
            "config": {"model": "phi3:mini"},
            "capabilities": {"vision": True},
        }
        entry = LocalModelEntry.from_dict(data)
        assert entry.id == "ollama:phi3:mini"
        assert entry.display_name == "Phi-3 Mini"
        assert entry.capabilities.vision is True
        assert entry.capabilities.tools is False

    def test_from_dict_minimal(self):
        """from_dict handles missing optional fields."""
        data = {"id": "test-model"}
        entry = LocalModelEntry.from_dict(data)
        assert entry.id == "test-model"
        assert entry.type == "chat"
        assert entry.backend == "ollama"
        assert entry.display_name == "test-model"

    def test_to_dict(self):
        """Can serialize entry to dictionary."""
        entry = LocalModelEntry(
            id="ollama:gemma2:2b",
            type="chat",
            backend="ollama",
            display_name="Gemma 2 2B",
            enabled=True,
            config={"model": "gemma2:2b"},
            capabilities=LocalModelCapabilities(vision=True),
        )
        data = entry.to_dict()
        assert data["id"] == "ollama:gemma2:2b"
        assert data["display_name"] == "Gemma 2 2B"
        assert data["capabilities"]["vision"] is True
        assert data["capabilities"]["tools"] is False

    def test_roundtrip(self):
        """Entry survives to_dict -> from_dict roundtrip."""
        original = LocalModelEntry(
            id="ollama:codellama:7b",
            type="chat",
            backend="ollama",
            display_name="Code Llama 7B",
            enabled=False,
            config={"model": "codellama:7b", "threads": 4},
            capabilities=LocalModelCapabilities(tools=True),
        )
        data = original.to_dict()
        restored = LocalModelEntry.from_dict(data)
        
        assert restored.id == original.id
        assert restored.display_name == original.display_name
        assert restored.enabled == original.enabled
        assert restored.config == original.config
        assert restored.capabilities.tools == original.capabilities.tools


class TestLocalModelHealth:
    """Tests for the LocalModelHealth dataclass."""

    def test_healthy(self):
        """Can create healthy status."""
        health = LocalModelHealth(ok=True, detail="Connected", latency_ms=50.0)
        assert health.ok is True
        assert health.detail == "Connected"
        assert health.latency_ms == 50.0

    def test_unhealthy(self):
        """Can create unhealthy status."""
        health = LocalModelHealth(ok=False, detail="Connection refused")
        assert health.ok is False
        assert health.latency_ms == 0.0


class TestOllamaBackendMessageConversion:
    """Tests for OllamaBackend message format conversion."""

    def test_convert_simple_messages(self):
        """Converts simple text messages correctly."""
        from services.local_models.ollama_backend import OllamaBackend
        
        backend = OllamaBackend("http://localhost:11434")
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello!"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        
        converted = backend._convert_messages(messages)
        
        assert len(converted) == 3
        assert converted[0]["role"] == "system"
        assert converted[0]["content"] == "You are a helpful assistant."
        assert converted[1]["role"] == "user"
        assert converted[2]["role"] == "assistant"

    def test_skip_empty_messages(self):
        """Skips messages with empty content."""
        from services.local_models.ollama_backend import OllamaBackend
        
        backend = OllamaBackend("http://localhost:11434")
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": ""},  # Empty
            {"role": "user", "content": "Are you there?"},
        ]
        
        converted = backend._convert_messages(messages)
        
        assert len(converted) == 2
        assert converted[0]["content"] == "Hello"
        assert converted[1]["content"] == "Are you there?"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
