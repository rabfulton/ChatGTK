"""
tools.py – Centralized tool definitions, prompt helpers, and dispatcher.

This module provides:
- Lightweight ToolSpec definitions for image and music tools.
- Prompt appendix constants and helpers to inject tool guidance into system prompts.
- Builder functions to construct provider-specific tool declarations (OpenAI, Grok, Gemini).
- A generic dispatcher to route tool calls to the appropriate handler.
- A ToolManager class to encapsulate model capability checks and handler creation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Terms that indicate a model is NOT a standard chat completion model.
CHAT_COMPLETION_EXCLUDE_TERMS = ("dall", "image", "realtime", "audio", "tts", "whisper")

# Guidance appended to system prompts for math formatting.
SYSTEM_PROMPT_APPENDIX = (
    "When writing mathematical equations use LaTeX syntax with parentheses: \\( ... \\) for inline math and \\[ ... \\] for block math. "
    "You always format your responses using markdown."
)

# Guidance appended to system prompts when the image tool is enabled.
IMAGE_TOOL_PROMPT_APPENDIX = (
    "You have access to a generate_image tool that can create actual images for the user "
    "from a natural language description. Use this tool when the user explicitly asks for "
    "an image or when a diagram, illustration, or example image would significantly help "
    "them understand the answer. After using the tool, describe the generated image in "
    "your reply so the user knows what it contains."
)

# Guidance appended to system prompts when the music tool is enabled.
MUSIC_TOOL_PROMPT_APPENDIX = (
    "You have access to a control_music tool that can play music from the user's local "
    "beets-managed music library using a local player. Use this tool when the "
    "user asks to play music.\n\n"
    "For 'play' actions, construct a **beets query string** in the 'keyword' parameter. "
    "Beets queries support fields like artist, album, title, genre, year, etc. Examples:\n"
    "  - 'year:1980..1989' for music from the 1980s\n"
    "  - 'genre:rock year:1990..1999' for 90s rock\n"
    "  - 'artist:\"Miles Davis\" year:1959' for Miles Davis tracks from 1959\n"
    "  - 'genre:jazz' for jazz music\n"
    "  - 'album:\"Kind of Blue\"' for a specific album\n"
    "  - 'artist:Beatles' for Beatles songs\n\n"
    "Translate natural language requests into beets queries. For example:\n"
    "  - 'Play some 80s music' → keyword='year:1980..1989'\n"
    "  - 'Play jazz from the 1950s' → keyword='genre:jazz year:1950..1959'\n"
    "  - 'Play something by Pink Floyd' → keyword='artist:\"Pink Floyd\"'\n\n"
    "Non-play actions (pause, resume, stop, next, previous) are limited in this implementation. "
    "Prefer using 'play' and only use other actions when the user explicitly requests them."
    "Convert artist names to their correct international spelling (e.g., bjork → Björk)."
)

# Guidance appended to system prompts when the read aloud tool is enabled.
READ_ALOUD_TOOL_PROMPT_APPENDIX = (
    "You have access to a read_aloud tool that can speak text aloud to the user "
    "using text-to-speech. Use this tool when the user asks you to read something "
    "out loud, announce something, or when audible output would enhance the user's "
    "experience (e.g. reading a poem, story, or important announcement)."
)


# ---------------------------------------------------------------------------
# ToolSpec dataclass
# ---------------------------------------------------------------------------

@dataclass
class ToolSpec:
    """Lightweight specification for a callable tool."""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema for parameters
    prompt_appendix: str = ""   # Guidance to add to system prompt when tool is enabled


# ---------------------------------------------------------------------------
# Built-in tool specifications
# ---------------------------------------------------------------------------

IMAGE_TOOL_SPEC = ToolSpec(
    name="generate_image",
    description=(
        "Generate an image for the user based on a textual description. "
        "Use this when the user explicitly asks for an image or when an "
        "image would significantly help them understand something."
    ),
    parameters={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": (
                    "A concise but detailed description of the image to generate, "
                    "in natural language."
                ),
            },
        },
        "required": ["prompt"],
    },
    prompt_appendix=IMAGE_TOOL_PROMPT_APPENDIX,
)

MUSIC_TOOL_SPEC = ToolSpec(
    name="control_music",
    description=(
        "Control music playback on the user's computer using a beets-managed "
        "music library and a local player. Use this when the user asks to play music. "
        "For play actions, provide a beets query string (e.g. 'year:1980..1989', "
        "'genre:rock', 'artist:\"Miles Davis\"') in the keyword parameter."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "The music control action to perform. Primarily use 'play'. "
                    "Other actions ('pause', 'resume', 'stop', 'next', 'previous') "
                    "have limited support."
                ),
            },
            "keyword": {
                "type": "string",
                "description": (
                    "For 'play' actions: a beets query string to search the music library. "
                    "Examples: 'year:1980..1989' for 80s music, 'genre:jazz', "
                    "'artist:\"Pink Floyd\"', 'album:\"Abbey Road\"'."
                ),
            },
            "volume": {
                "type": "number",
                "description": (
                    "For 'set_volume' actions: desired volume level (0–100). "
                    "Note: volume control has limited support."
                ),
            },
        },
        "required": ["action"],
    },
    prompt_appendix=MUSIC_TOOL_PROMPT_APPENDIX,
)

READ_ALOUD_TOOL_SPEC = ToolSpec(
    name="read_aloud",
    description=(
        "Read text aloud to the user using text-to-speech. Use this when "
        "the user asks you to speak, read, or announce something out loud."
    ),
    parameters={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": (
                    "The text to be read aloud to the user."
                ),
            },
        },
        "required": ["text"],
    },
    prompt_appendix=READ_ALOUD_TOOL_PROMPT_APPENDIX,
)

# Registry mapping tool name to spec for easy lookup.
TOOL_REGISTRY: Dict[str, ToolSpec] = {
    IMAGE_TOOL_SPEC.name: IMAGE_TOOL_SPEC,
    MUSIC_TOOL_SPEC.name: MUSIC_TOOL_SPEC,
    READ_ALOUD_TOOL_SPEC.name: READ_ALOUD_TOOL_SPEC,
}


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------

def is_chat_completion_model(model_name: str) -> bool:
    """Return True if the model behaves like a standard text chat completion model."""
    if not model_name:
        return True
    lower_name = model_name.lower()
    return not any(term in lower_name for term in CHAT_COMPLETION_EXCLUDE_TERMS)


def append_tool_guidance(
    system_prompt: str,
    enabled_tools: Set[str],
    include_math: bool = True,
) -> str:
    """
    Return a new system prompt with guidance for enabled tools appended.

    Parameters
    ----------
    system_prompt : str
        The original system prompt.
    enabled_tools : Set[str]
        Set of tool names that are enabled (e.g. {"generate_image", "control_music"}).
    include_math : bool
        Whether to include math formatting guidance.

    Returns
    -------
    str
        The system prompt with relevant guidance appended.
    """
    result = system_prompt.rstrip() if system_prompt else ""

    if include_math and SYSTEM_PROMPT_APPENDIX not in result:
        if result:
            result = f"{result}\n\n{SYSTEM_PROMPT_APPENDIX}"
        else:
            result = SYSTEM_PROMPT_APPENDIX

    for tool_name in sorted(enabled_tools):
        spec = TOOL_REGISTRY.get(tool_name)
        if spec and spec.prompt_appendix and spec.prompt_appendix not in result:
            result = f"{result}\n\n{spec.prompt_appendix}"

    return result


# ---------------------------------------------------------------------------
# Tool declaration builders for providers
# ---------------------------------------------------------------------------

def build_openai_tool_declaration(spec: ToolSpec) -> Dict[str, Any]:
    """Build an OpenAI/Grok-compatible tool declaration from a ToolSpec."""
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        },
    }


def build_gemini_function_declaration(spec: ToolSpec) -> Dict[str, Any]:
    """Build a Gemini-compatible function declaration from a ToolSpec."""
    return {
        "name": spec.name,
        "description": spec.description,
        "parameters": spec.parameters,
    }


def build_tools_for_provider(
    enabled_tools: Set[str],
    provider_name: str,
) -> List[Dict[str, Any]]:
    """
    Build a list of tool declarations for the given provider.

    Parameters
    ----------
    enabled_tools : Set[str]
        Set of tool names that are enabled.
    provider_name : str
        One of 'openai', 'grok', 'gemini'.

    Returns
    -------
    List[Dict[str, Any]]
        List of tool declarations in the provider's expected format.
    """
    declarations: List[Dict[str, Any]] = []
    for tool_name in sorted(enabled_tools):
        spec = TOOL_REGISTRY.get(tool_name)
        if not spec:
            continue
        if provider_name in ("openai", "grok", "claude"):
            declarations.append(build_openai_tool_declaration(spec))
        elif provider_name == "gemini":
            declarations.append(build_gemini_function_declaration(spec))
    return declarations


# ---------------------------------------------------------------------------
# Tool context and dispatcher
# ---------------------------------------------------------------------------

@dataclass
class ToolContext:
    """
    Context passed to tool handlers during execution.

    Handlers are stored as callables. The dispatcher will invoke the appropriate
    handler based on the tool name.
    """
    image_handler: Optional[Callable[[str], str]] = None
    music_handler: Optional[Callable[[str, Optional[str], Optional[float]], str]] = None
    read_aloud_handler: Optional[Callable[[str], str]] = None


def run_tool_call(
    tool_name: str,
    args: Dict[str, Any],
    context: ToolContext,
) -> str:
    """
    Dispatch a tool call to the appropriate handler.

    Parameters
    ----------
    tool_name : str
        The name of the tool being called.
    args : Dict[str, Any]
        The arguments parsed from the tool call.
    context : ToolContext
        Context containing the handler callables.

    Returns
    -------
    str
        The result of the tool call (e.g. an <img> tag or status message).
    """
    if tool_name == "generate_image":
        if context.image_handler is None:
            return "Error: image tool is not available."
        prompt_arg = args.get("prompt", "")
        try:
            return context.image_handler(prompt_arg)
        except Exception as e:
            print(f"Error in image_handler: {e}")
            return f"Error generating image: {e}"

    elif tool_name == "control_music":
        if context.music_handler is None:
            return "Error: music tool is not available."
        action = args.get("action", "")
        keyword = args.get("keyword")
        volume = args.get("volume")
        try:
            return context.music_handler(action, keyword, volume)
        except Exception as e:
            print(f"Error in music_handler: {e}")
            return f"Error controlling music: {e}"

    elif tool_name == "read_aloud":
        if context.read_aloud_handler is None:
            return "Error: read aloud tool is not available."
        text = args.get("text", "")
        try:
            return context.read_aloud_handler(text)
        except Exception as e:
            print(f"Error in read_aloud_handler: {e}")
            return f"Error reading aloud: {e}"

    else:
        return f"Error: unknown tool '{tool_name}' requested."


def parse_tool_arguments(raw_args: str) -> Dict[str, Any]:
    """
    Parse raw JSON arguments from a tool call.

    Parameters
    ----------
    raw_args : str
        The raw JSON string of arguments.

    Returns
    -------
    Dict[str, Any]
        Parsed arguments, or an empty dict on failure.
    """
    try:
        return json.loads(raw_args or "{}")
    except Exception as e:
        print(f"Error parsing tool arguments: {e}")
        return {}


# ---------------------------------------------------------------------------
# ToolManager – model capability checks and handler creation
# ---------------------------------------------------------------------------

class ToolManager:
    """
    Encapsulates model capability checks and handler creation for tools.

    This class centralizes the logic for determining which tools a model supports
    and for building the appropriate handlers to pass to providers.
    """

    # Models that are explicitly image-generation models (not chat models).
    IMAGE_ONLY_MODELS = {
        "dall-e-3",
        "gpt-image-1",
        "gpt-image-1-mini",
        "gemini-3-pro-image-preview",
        "gemini-2.5-flash-image",
    }

    def __init__(
        self,
        image_tool_enabled: bool = True,
        music_tool_enabled: bool = False,
        read_aloud_tool_enabled: bool = False,
    ):
        """
        Initialize the ToolManager.

        Parameters
        ----------
        image_tool_enabled : bool
            Whether the image tool is globally enabled.
        music_tool_enabled : bool
            Whether the music tool is globally enabled.
        read_aloud_tool_enabled : bool
            Whether the read aloud tool is globally enabled.
        """
        self.image_tool_enabled = image_tool_enabled
        self.music_tool_enabled = music_tool_enabled
        self.read_aloud_tool_enabled = read_aloud_tool_enabled

    def get_provider_name_for_model(self, model_name: str, model_provider_map: Optional[Dict[str, str]] = None) -> str:
        """
        Determine the provider name for a given model.

        Parameters
        ----------
        model_name : str
            The model name.
        model_provider_map : Optional[Dict[str, str]]
            Optional mapping of model names to provider names.

        Returns
        -------
        str
            The provider name ('openai', 'gemini', 'grok').
        """
        if not model_name:
            return "openai"
        if model_provider_map:
            provider = model_provider_map.get(model_name)
            if provider:
                return provider

        lower = model_name.lower()
        if lower.startswith("gemini-"):
            return "gemini"
        if lower.startswith("grok-"):
            return "grok"
        if lower.startswith("claude-"):
            return "claude"
        return "openai"

    def is_image_model_for_provider(self, model_name: str, provider_name: str) -> bool:
        """
        Return True if the given model is an image-generation model.
        """
        if not model_name:
            return False
        lower = model_name.lower()

        if provider_name == "openai":
            return lower in ("dall-e-3", "gpt-image-1", "gpt-image-1-mini")
        if provider_name == "gemini":
            return lower in ("gemini-3-pro-image-preview", "gemini-2.5-flash-image")
        if provider_name == "grok":
            return lower.startswith("grok-2-image")
        return False

    def supports_image_tools(self, model_name: str, model_provider_map: Optional[Dict[str, str]] = None) -> bool:
        """
        Return True if the given model should be offered the image-generation tool.
        """
        if not model_name:
            return False
        if not self.image_tool_enabled:
            return False

        provider = self.get_provider_name_for_model(model_name, model_provider_map)
        if provider not in ("openai", "gemini", "grok", "claude"):
            return False

        lower = model_name.lower()
        if any(term in lower for term in CHAT_COMPLETION_EXCLUDE_TERMS):
            return False
        if self.is_image_model_for_provider(model_name, provider):
            return False

        # OpenAI GPT chat models.
        if provider == "openai":
            return lower.startswith("gpt-")

        # Gemini chat models that support function calling.
        if provider == "gemini":
            return (
                lower.startswith("gemini-2.5")
                or lower.startswith("gemini-3-pro")
                or lower.startswith("gemini-pro")
                or lower.startswith("gemini-flash")
            )

        # Grok chat models.
        if provider == "grok":
            return lower.startswith("grok-")

        # Claude chat models via the OpenAI SDK compatibility layer.
        if provider == "claude":
            return lower.startswith("claude-")

        return False

    def supports_music_tools(self, model_name: str, model_provider_map: Optional[Dict[str, str]] = None) -> bool:
        """
        Return True if the given model should be offered the music-control tool.
        """
        if not model_name:
            return False
        if not self.music_tool_enabled:
            return False

        provider = self.get_provider_name_for_model(model_name, model_provider_map)
        if provider not in ("openai", "gemini", "grok", "claude"):
            return False

        lower = model_name.lower()
        if any(term in lower for term in CHAT_COMPLETION_EXCLUDE_TERMS):
            return False
        if self.is_image_model_for_provider(model_name, provider):
            return False

        # OpenAI GPT chat models.
        if provider == "openai":
            return lower.startswith("gpt-")

        # Gemini chat models that support function calling.
        if provider == "gemini":
            return (
                lower.startswith("gemini-2.5")
                or lower.startswith("gemini-3-pro")
                or lower.startswith("gemini-pro")
                or lower.startswith("gemini-flash")
            )

        # Grok chat models.
        if provider == "grok":
            return lower.startswith("grok-")

        # Claude chat models via the OpenAI SDK compatibility layer.
        if provider == "claude":
            return lower.startswith("claude-")

        return False

    def supports_read_aloud_tools(self, model_name: str, model_provider_map: Optional[Dict[str, str]] = None) -> bool:
        """
        Return True if the given model should be offered the read-aloud tool.
        """
        if not model_name:
            return False
        if not self.read_aloud_tool_enabled:
            return False

        provider = self.get_provider_name_for_model(model_name, model_provider_map)
        if provider not in ("openai", "gemini", "grok", "claude"):
            return False

        lower = model_name.lower()
        if any(term in lower for term in CHAT_COMPLETION_EXCLUDE_TERMS):
            return False
        if self.is_image_model_for_provider(model_name, provider):
            return False

        # OpenAI GPT chat models.
        if provider == "openai":
            return lower.startswith("gpt-")

        # Gemini chat models that support function calling.
        if provider == "gemini":
            return (
                lower.startswith("gemini-2.5")
                or lower.startswith("gemini-3-pro")
                or lower.startswith("gemini-pro")
                or lower.startswith("gemini-flash")
            )

        # Grok chat models.
        if provider == "grok":
            return lower.startswith("grok-")

        # Claude chat models via the OpenAI SDK compatibility layer.
        if provider == "claude":
            return lower.startswith("claude-")

        return False

    def get_enabled_tools_for_model(
        self,
        model_name: str,
        model_provider_map: Optional[Dict[str, str]] = None,
    ) -> Set[str]:
        """
        Return the set of tool names enabled for the given model.
        """
        enabled: Set[str] = set()
        if self.supports_image_tools(model_name, model_provider_map):
            enabled.add("generate_image")
        if self.supports_music_tools(model_name, model_provider_map):
            enabled.add("control_music")
        if self.supports_read_aloud_tools(model_name, model_provider_map):
            enabled.add("read_aloud")
        return enabled

    def build_tool_context(
        self,
        model_name: str,
        image_handler: Optional[Callable[[str], str]] = None,
        music_handler: Optional[Callable[[str, Optional[str], Optional[float]], str]] = None,
        read_aloud_handler: Optional[Callable[[str], str]] = None,
        model_provider_map: Optional[Dict[str, str]] = None,
    ) -> ToolContext:
        """
        Build a ToolContext with handlers for the tools supported by the model.

        Parameters
        ----------
        model_name : str
            The model name.
        image_handler : Optional[Callable[[str], str]]
            Handler for image generation.
        music_handler : Optional[Callable[[str, Optional[str], Optional[float]], str]]
            Handler for music control.
        read_aloud_handler : Optional[Callable[[str], str]]
            Handler for read aloud.
        model_provider_map : Optional[Dict[str, str]]
            Optional mapping of model names to provider names.

        Returns
        -------
        ToolContext
            A context with the appropriate handlers set.
        """
        ctx = ToolContext()
        if self.supports_image_tools(model_name, model_provider_map):
            ctx.image_handler = image_handler
        if self.supports_music_tools(model_name, model_provider_map):
            ctx.music_handler = music_handler
        if self.supports_read_aloud_tools(model_name, model_provider_map):
            ctx.read_aloud_handler = read_aloud_handler
        return ctx

