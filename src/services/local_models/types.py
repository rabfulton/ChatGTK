"""
Data types for local models.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional


@dataclass
class LocalModelCapabilities:
    """Capabilities of a local model."""
    tools: bool = False
    vision: bool = False
    audio_in: bool = False
    audio_out: bool = False


@dataclass
class LocalModelEntry:
    """
    A local model configuration entry.
    
    Stored in local_models.json and used to configure local backends.
    """
    id: str                           # Stable ID (e.g., "ollama:llama3.2:3b")
    type: str                         # "chat", "stt", or "tts"
    backend: str                      # "ollama", "sherpa-onnx", etc.
    display_name: str                 # Human-readable name
    enabled: bool = True
    config: Dict[str, Any] = field(default_factory=dict)
    capabilities: LocalModelCapabilities = field(default_factory=LocalModelCapabilities)
    
    @classmethod
    def from_dict(cls, data: dict) -> "LocalModelEntry":
        """Create a LocalModelEntry from a dictionary."""
        caps_data = data.get("capabilities", {})
        capabilities = LocalModelCapabilities(
            tools=caps_data.get("tools", False),
            vision=caps_data.get("vision", False),
            audio_in=caps_data.get("audio_in", False),
            audio_out=caps_data.get("audio_out", False),
        )
        return cls(
            id=data["id"],
            type=data.get("type", "chat"),
            backend=data.get("backend", "ollama"),
            display_name=data.get("display_name", data["id"]),
            enabled=data.get("enabled", True),
            config=data.get("config", {}),
            capabilities=capabilities,
        )
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "type": self.type,
            "backend": self.backend,
            "display_name": self.display_name,
            "enabled": self.enabled,
            "config": self.config,
            "capabilities": {
                "tools": self.capabilities.tools,
                "vision": self.capabilities.vision,
                "audio_in": self.capabilities.audio_in,
                "audio_out": self.capabilities.audio_out,
            },
        }


@dataclass
class LocalModelHealth:
    """Health check result for a local model or backend."""
    ok: bool
    detail: str
    latency_ms: float = 0.0
