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
import subprocess

from model_cards import get_card


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

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


def _has_playerctl() -> bool:
    """
    Return True if playerctl is available on this system.

    This mirrors the runtime check used in ChatGTK._control_music_via_beets,
    but is evaluated once at import time to tailor the tool guidance.
    """
    try:
        subprocess.run(
            ["playerctl", "--version"],
            capture_output=True,
            text=True,
            check=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError, OSError, ValueError):
        return False


_MUSIC_TOOL_PROMPT_BASE = (
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
)

if _has_playerctl():
    _MUSIC_TOOL_PROMPT_PLAYERCTL = (
        "On this system, non-play actions (pause, resume, stop, next, previous, volume_up, "
        "volume_down, set_volume) are available via MPRIS using the external 'playerctl' "
        "command targeting the configured player. Use these actions when the user explicitly "
        "asks to control currently playing music (for example, to pause, resume, or adjust "
        "volume).\n\n"
    )
else:
    _MUSIC_TOOL_PROMPT_PLAYERCTL = (
        "On this system, non-play actions (pause, resume, stop, next, previous, volume_up, "
        "volume_down, set_volume) require the external 'playerctl' command for MPRIS control, "
        "which does not appear to be installed. Prefer using 'play' with an explicit beets "
        "query, and avoid other actions unless the user insists—if they do, explain that they "
        "need to install 'playerctl' for advanced playback control.\n\n"
    )

_MUSIC_TOOL_PROMPT_ARTISTS = (
    "Convert artist names to their correct international spelling (e.g., bjork → Björk)."
)

MUSIC_TOOL_PROMPT_APPENDIX = (
    _MUSIC_TOOL_PROMPT_BASE + _MUSIC_TOOL_PROMPT_PLAYERCTL + _MUSIC_TOOL_PROMPT_ARTISTS
)

# Guidance appended to system prompts when the read aloud tool is enabled.
READ_ALOUD_TOOL_PROMPT_APPENDIX = (
    "You have access to a read_aloud tool that can speak text aloud to the user "
    "using text-to-speech. Use this tool when the user asks you to read something "
    "out loud, announce something, or when audible output would enhance the user's "
    "experience (e.g. reading a poem, story, or important announcement)."
)

# Guidance appended to system prompts when the search/memory tool is enabled.
SEARCH_TOOL_PROMPT_APPENDIX = (
    "You have access to a search_memory tool that can search the user's past "
    "conversations and configured document directories for relevant context. "
    "Use this tool when:\n"
    "  - The user asks about something they mentioned before\n"
    "  - You need context from previous conversations\n"
    "  - The user references past discussions or decisions\n"
    "  - Finding relevant information from the user's documents would help\n\n"
    "The search uses word-boundary matching, so searching for 'dog' will match "
    "'dog', 'dog,', 'dog.' but not 'doggedly' or 'hotdog'. You can search "
    "'history' (past conversations), 'documents' (configured directories), or 'all'."
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

SEARCH_TOOL_SPEC = ToolSpec(
    name="search_memory",
    description=(
        "Search the user's past conversations and configured document directories "
        "for relevant context. Use this when the user asks about something they "
        "mentioned before, references past discussions, or when finding relevant "
        "information from their documents would help answer their question."
    ),
    parameters={
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": (
                    "The word or phrase to search for. Uses word-boundary matching, "
                    "so 'dog' matches 'dog', 'dog,', 'dog.' but not 'doggedly'."
                ),
            },
            "source": {
                "type": "string",
                "enum": ["history", "documents", "all"],
                "description": (
                    "Where to search: 'history' for past conversations, "
                    "'documents' for configured directories, or 'all' for both. "
                    "Defaults to 'history'."
                ),
            },
        },
        "required": ["keyword"],
    },
    prompt_appendix=SEARCH_TOOL_PROMPT_APPENDIX,
)

# Registry mapping tool name to spec for easy lookup.
TOOL_REGISTRY: Dict[str, ToolSpec] = {
    IMAGE_TOOL_SPEC.name: IMAGE_TOOL_SPEC,
    MUSIC_TOOL_SPEC.name: MUSIC_TOOL_SPEC,
    READ_ALOUD_TOOL_SPEC.name: READ_ALOUD_TOOL_SPEC,
    SEARCH_TOOL_SPEC.name: SEARCH_TOOL_SPEC,
}


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------

def is_chat_completion_model(model_name: str, custom_models: dict = None) -> bool:
    """
    Return True if the model behaves like a standard text chat completion model.
    
    Uses the model card system to determine if a model is a chat model.
    For unknown models (not in catalog), defaults to True.
    """
    card = get_card(model_name, custom_models)
    if card:
        return card.is_chat_model()
    
    # Unknown model - default to assuming it's a chat model
    return True


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
        One of 'openai', 'grok', 'claude', 'custom', 'gemini'.

    Returns
    -------
    List[Dict[str, Any]]
        List of tool declarations in the provider's expected format.
    """
    declarations: List[Dict[str, Any]] = []
    for tool_name in sorted(enabled_tools):
        spec = TOOL_REGISTRY.get(tool_name)
        if not spec:
            print(f"[build_tools_for_provider] WARNING: No spec found for tool '{tool_name}'")
            continue
        if provider_name in ("openai", "grok", "claude", "custom"):
            declarations.append(build_openai_tool_declaration(spec))
        elif provider_name == "gemini":
            declarations.append(build_gemini_function_declaration(spec))
    print(f"[build_tools_for_provider] Built {len(declarations)} tools for {provider_name}: {[d.get('function', d).get('name', d.get('name')) for d in declarations]}")
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
    search_handler: Optional[Callable[[str, Optional[str]], str]] = None


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

    elif tool_name == "search_memory":
        if context.search_handler is None:
            return "Error: search/memory tool is not available."
        keyword = args.get("keyword", "")
        source = args.get("source", "history")
        try:
            return context.search_handler(keyword, source)
        except Exception as e:
            print(f"Error in search_handler: {e}")
            return f"Error searching memory: {e}"

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


# Prefix used by tools to indicate their result should not be shown in the chat UI
HIDE_TOOL_RESULT_PREFIX = "__HIDE_TOOL_RESULT__"


def should_hide_tool_result(result: str) -> bool:
    """Return True if the tool result should be hidden from chat output."""
    return result and result.startswith(HIDE_TOOL_RESULT_PREFIX)


def strip_hide_prefix(result: str) -> str:
    """Strip the hide prefix from a tool result (for sending to model)."""
    if result and result.startswith(HIDE_TOOL_RESULT_PREFIX):
        return result[len(HIDE_TOOL_RESULT_PREFIX):]
    return result


def build_enabled_tools_from_handlers(
    image_handler=None,
    music_handler=None,
    read_aloud_handler=None,
    search_handler=None,
) -> Set[str]:
    """
    Build the set of enabled tool names based on which handlers are provided.
    
    This centralizes the logic for determining which tools are enabled,
    eliminating the need to update multiple places when adding a new tool.
    """
    enabled: Set[str] = set()
    if image_handler is not None:
        enabled.add("generate_image")
    if music_handler is not None:
        enabled.add("control_music")
    if read_aloud_handler is not None:
        enabled.add("read_aloud")
    if search_handler is not None:
        enabled.add("search_memory")
    return enabled


def process_tool_result(result: str, snippets: List[str]) -> str:
    """
    Process a tool result: add to snippets list if visible, return cleaned result.
    
    Parameters
    ----------
    result : str
        The raw tool result, possibly with HIDE_TOOL_RESULT_PREFIX.
    snippets : List[str]
        List to append visible results to (modified in place).
    
    Returns
    -------
    str
        The cleaned result (prefix stripped) for sending to the model.
    """
    cleaned = strip_hide_prefix(result) if result else ""
    if result and not should_hide_tool_result(result):
        snippets.append(cleaned)
    return cleaned


# ---------------------------------------------------------------------------
# ToolManager – model capability checks and handler creation
# ---------------------------------------------------------------------------

class ToolManager:
    """
    Encapsulates model capability checks and handler creation for tools.

    This class centralizes the logic for determining which tools a model supports
    and for building the appropriate handlers to pass to providers.
    """

    def __init__(
        self,
        image_tool_enabled: bool = True,
        music_tool_enabled: bool = False,
        read_aloud_tool_enabled: bool = False,
        search_tool_enabled: bool = False,
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
        search_tool_enabled : bool
            Whether the search/memory tool is globally enabled.
        """
        self.image_tool_enabled = image_tool_enabled
        self.music_tool_enabled = music_tool_enabled
        self.read_aloud_tool_enabled = read_aloud_tool_enabled
        self.search_tool_enabled = search_tool_enabled

    def get_provider_name_for_model(
        self,
        model_name: str,
        model_provider_map: Optional[Dict[str, str]] = None,
        custom_models: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> str:
        """
        Determine the provider name for a given model.

        Parameters
        ----------
        model_name : str
            The model name.
        model_provider_map : Optional[Dict[str, str]]
            Optional mapping of model names to provider names.
        custom_models : Optional[Dict[str, Dict[str, Any]]]
            Optional dict of custom model configurations.

        Returns
        -------
        str
            The provider name ('openai', 'gemini', 'grok', 'claude', 'perplexity', 'custom').
        """
        if not model_name:
            return "openai"

        # Card-first: check model card for provider
        card = get_card(model_name, custom_models)
        if card:
            return card.provider

        # Fallback: check model_provider_map
        if model_provider_map:
            provider = model_provider_map.get(model_name)
            if provider:
                return provider

        # Unknown model - default to openai
        return "openai"

    def is_image_model_for_provider(self, model_name: str, provider_name: str, custom_models: Optional[Dict[str, Dict[str, Any]]] = None) -> bool:
        """
        Return True if the given model is an image-generation model.
        
        Parameters
        ----------
        model_name : str
            The model name.
        provider_name : str
            The provider name.
        custom_models : Optional[Dict[str, Dict[str, Any]]]
            Optional dict of custom model configurations. If provided and provider_name is "custom",
            checks if the model has api_type "images".
        """
        if not model_name:
            return False

        # Check model card for image_gen capability
        # Note: We check image_gen directly, not is_image_model(), because multimodal
        # models (like Gemini image models) have both text=True and image_gen=True
        card = get_card(model_name, custom_models)
        if card:
            return card.capabilities.image_gen

        # Unknown model - default to not an image model
        return False

    def _model_supports_tool_calling(
        self,
        model_name: str,
        model_provider_map: Optional[Dict[str, str]] = None,
        custom_models: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> bool:
        """
        Internal helper: Return True if the model supports tool/function calling.
        
        This is the card-based check used by all tool support methods.
        """
        if not model_name:
            return False

        # Check model card for tool support
        card = get_card(model_name, custom_models)
        if card:
            # Model must support tools AND be a chat model (not an image-only model)
            return card.supports_tools() and card.is_chat_model()

        # Unknown model - default to no tool support
        return False

    def supports_image_tools(self, model_name: str, model_provider_map: Optional[Dict[str, str]] = None, custom_models: Optional[Dict[str, Dict[str, Any]]] = None) -> bool:
        """
        Return True if the given model should be offered the image-generation tool.
        """
        if not self.image_tool_enabled:
            return False
        return self._model_supports_tool_calling(model_name, model_provider_map, custom_models)

    def supports_music_tools(self, model_name: str, model_provider_map: Optional[Dict[str, str]] = None, custom_models: Optional[Dict[str, Dict[str, Any]]] = None) -> bool:
        """
        Return True if the given model should be offered the music-control tool.
        """
        if not self.music_tool_enabled:
            return False
        return self._model_supports_tool_calling(model_name, model_provider_map, custom_models)

    def supports_read_aloud_tools(self, model_name: str, model_provider_map: Optional[Dict[str, str]] = None, custom_models: Optional[Dict[str, Dict[str, Any]]] = None) -> bool:
        """
        Return True if the given model should be offered the read-aloud tool.
        """
        if not self.read_aloud_tool_enabled:
            return False
        return self._model_supports_tool_calling(model_name, model_provider_map, custom_models)

    def supports_search_tools(self, model_name: str, model_provider_map: Optional[Dict[str, str]] = None, custom_models: Optional[Dict[str, Dict[str, Any]]] = None) -> bool:
        """
        Return True if the given model should be offered the search/memory tool.
        """
        if not self.search_tool_enabled:
            print(f"[SearchTool] Tool globally disabled (search_tool_enabled={self.search_tool_enabled})")
            return False
        supports = self._model_supports_tool_calling(model_name, model_provider_map, custom_models)
        print(f"[SearchTool] supports_search_tools({model_name}) = {supports}")
        return supports

    def get_enabled_tools_for_model(
        self,
        model_name: str,
        model_provider_map: Optional[Dict[str, str]] = None,
        custom_models: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Set[str]:
        """
        Return the set of tool names enabled for the given model.
        """
        enabled: Set[str] = set()
        if self.supports_image_tools(model_name, model_provider_map, custom_models):
            enabled.add("generate_image")
        if self.supports_music_tools(model_name, model_provider_map, custom_models):
            enabled.add("control_music")
        if self.supports_read_aloud_tools(model_name, model_provider_map, custom_models):
            enabled.add("read_aloud")
        if self.supports_search_tools(model_name, model_provider_map, custom_models):
            enabled.add("search_memory")
        print(f"[ToolManager] get_enabled_tools_for_model({model_name}) = {enabled}")
        return enabled

    def build_tool_context(
        self,
        model_name: str,
        image_handler: Optional[Callable[[str], str]] = None,
        music_handler: Optional[Callable[[str, Optional[str], Optional[float]], str]] = None,
        read_aloud_handler: Optional[Callable[[str], str]] = None,
        search_handler: Optional[Callable[[str, Optional[str]], str]] = None,
        model_provider_map: Optional[Dict[str, str]] = None,
        custom_models: Optional[Dict[str, Dict[str, Any]]] = None,
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
        search_handler : Optional[Callable[[str, Optional[str]], str]]
            Handler for search/memory.
        model_provider_map : Optional[Dict[str, str]]
            Optional mapping of model names to provider names.
        custom_models : Optional[Dict[str, Dict[str, Any]]]
            Optional dict of custom model configurations.

        Returns
        -------
        ToolContext
            A context with the appropriate handlers set.
        """
        ctx = ToolContext()
        if self.supports_image_tools(model_name, model_provider_map, custom_models):
            ctx.image_handler = image_handler
        if self.supports_music_tools(model_name, model_provider_map, custom_models):
            ctx.music_handler = music_handler
        if self.supports_read_aloud_tools(model_name, model_provider_map, custom_models):
            ctx.read_aloud_handler = read_aloud_handler
        if self.supports_search_tools(model_name, model_provider_map, custom_models):
            ctx.search_handler = search_handler
        return ctx

