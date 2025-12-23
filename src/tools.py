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

from model_cards import get_card


# Settings repository singleton for tools
_settings_repo = None

def _get_settings_repo():
    """Get or create the settings repository singleton."""
    global _settings_repo
    if _settings_repo is None:
        from repositories import SettingsRepository
        _settings_repo = SettingsRepository()
    return _settings_repo


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Constants have been moved to config.py and are now loaded via settings.


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
        "Generate or edit an image based on a textual description. "
        "Use this when the user explicitly asks for an image or when an "
        "image would significantly help them understand something. "
        "To edit an existing image, provide the image_path parameter with "
        "the path to the source image."
    ),
    parameters={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": (
                    "A concise but detailed description of the image to generate "
                    "or the edits to make to an existing image, in natural language."
                ),
            },
            "image_path": {
                "type": "string",
                "description": (
                    "Optional: Path to an existing image to edit. If provided, "
                    "the prompt describes the desired modifications to this image."
                ),
            },
        },
    },
)

TEXT_GET_TOOL_SPEC = ToolSpec(
    name="text_get",
    description=(
        "Return the full text for a named target buffer. "
        "Use this to read the current document or other editable text target."
    ),
    parameters={
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "The logical target name (e.g. document, system_prompt).",
            },
        },
        "required": ["target"],
    },
    prompt_appendix=(
        "Use text_get to read the current text for a target before editing."
    ),
)

APPLY_TEXT_EDIT_TOOL_SPEC = ToolSpec(
    name="apply_text_edit",
    description=(
        "Apply a single text edit to a named target. Use operation=diff with a unified diff "
        "when possible; use operation=replace to provide full replacement text."
    ),
    parameters={
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "The logical target name (e.g. document, system_prompt).",
            },
            "operation": {
                "type": "string",
                "enum": ["replace", "diff"],
                "description": "The edit operation to apply.",
            },
            "text": {
                "type": "string",
                "description": "Replacement text or unified diff, depending on operation.",
            },
            "summary": {
                "type": "string",
                "description": "Short summary of the edit for UI status.",
            },
        },
        "required": ["target", "operation", "text"],
    },
    prompt_appendix=(
        "When updating a text target, call apply_text_edit with operation=diff and "
        "include a short summary."
    ),
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
    },
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
    },
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
    },
)

MEMORY_RETRIEVAL_TOOL_SPEC = ToolSpec(
    name="retrieve_memory",
    description=(
        "Search your semantic memory of past conversations with the user for relevant context. "
        "Use this when the user references past discussions, asks about something they mentioned before, "
        "or when historical context would help answer their question. This uses AI-powered semantic search."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Natural language query to search memories semantically. "
                    "Describe what you're looking for in plain language."
                ),
            },
        },
    },
)

# Registry mapping tool name to spec for easy lookup.
TOOL_REGISTRY: Dict[str, ToolSpec] = {
    IMAGE_TOOL_SPEC.name: IMAGE_TOOL_SPEC,
    MUSIC_TOOL_SPEC.name: MUSIC_TOOL_SPEC,
    READ_ALOUD_TOOL_SPEC.name: READ_ALOUD_TOOL_SPEC,
    SEARCH_TOOL_SPEC.name: SEARCH_TOOL_SPEC,
    MEMORY_RETRIEVAL_TOOL_SPEC.name: MEMORY_RETRIEVAL_TOOL_SPEC,
    TEXT_GET_TOOL_SPEC.name: TEXT_GET_TOOL_SPEC,
    APPLY_TEXT_EDIT_TOOL_SPEC.name: APPLY_TEXT_EDIT_TOOL_SPEC,
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


def _get_setting_value(key: str, default: str = "", settings_manager=None) -> str:
    if settings_manager is not None:
        return settings_manager.get(key, default)
    return _get_settings_repo().get(key, default)


def append_tool_guidance(
    system_prompt: str,
    enabled_tools: Set[str],
    include_math: bool = True,
    settings_manager=None,
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
    if include_math:
        math_appendix = _get_setting_value(
            "SYSTEM_PROMPT_APPENDIX",
            "",
            settings_manager=settings_manager
        )
        if math_appendix and math_appendix not in result:
            if result:
                result = f"{result}\n\n{math_appendix}"
            else:
                result = math_appendix

    for tool_name in sorted(enabled_tools):
        appendix = ""
        if tool_name == "generate_image":
            appendix = _get_setting_value(
                "IMAGE_TOOL_PROMPT_APPENDIX",
                "",
                settings_manager=settings_manager
            )
        elif tool_name == "control_music":
            appendix = _get_setting_value(
                "MUSIC_TOOL_PROMPT_APPENDIX",
                "",
                settings_manager=settings_manager
            )
        elif tool_name == "read_aloud":
            appendix = _get_setting_value(
                "READ_ALOUD_TOOL_PROMPT_APPENDIX",
                "",
                settings_manager=settings_manager
            )
        elif tool_name == "search_memory":
            appendix = _get_setting_value(
                "SEARCH_TOOL_PROMPT_APPENDIX",
                "",
                settings_manager=settings_manager
            )
        elif tool_name == "apply_text_edit":
            appendix = _get_setting_value(
                "TEXT_EDIT_TOOL_PROMPT_APPENDIX",
                "",
                settings_manager=settings_manager
            )
        elif tool_name == "retrieve_memory":
            appendix = _get_setting_value(
                "MEMORY_PROMPT_APPENDIX",
                "",
                settings_manager=settings_manager
            )
        
        # Fallback to spec if available (though now specs default to empty)
        if not appendix:
            spec = TOOL_REGISTRY.get(tool_name)
            if spec and spec.prompt_appendix:
                appendix = spec.prompt_appendix

        if appendix and appendix not in result:
            result = f"{result}\n\n{appendix}"

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
    image_handler: Optional[Callable[[str, Optional[str]], str]] = None  # (prompt, image_path) -> result
    music_handler: Optional[Callable[[str, Optional[str], Optional[float]], str]] = None
    read_aloud_handler: Optional[Callable[[str], str]] = None
    search_handler: Optional[Callable[[str, Optional[str]], str]] = None
    memory_handler: Optional[Callable[[str], str]] = None  # (query) -> result
    text_get_handler: Optional[Callable[[str], str]] = None
    text_edit_handler: Optional[Callable[[str, str, str, Optional[str]], str]] = None


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
        image_path_arg = args.get("image_path")
        try:
            result = context.image_handler(prompt_arg, image_path_arg)
            # Hide the img tag from the model but still show it in UI
            # This prevents the model from echoing the file path
            if result and result.startswith("<img"):
                return HIDE_TOOL_RESULT_PREFIX + result
            return result
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
            return "Error: search tool is not available."
        keyword = args.get("keyword", "")
        source = args.get("source", "history")
        try:
            return context.search_handler(keyword, source)
        except Exception as e:
            print(f"Error in search_handler: {e}")
            return f"Error searching memory: {e}"

    elif tool_name == "retrieve_memory":
        if context.memory_handler is None:
            return "Error: memory retrieval tool is not available."
        query = args.get("query", "")
        try:
            return context.memory_handler(query)
        except Exception as e:
            print(f"Error in memory_handler: {e}")
            return f"Error retrieving memory: {e}"

    elif tool_name == "text_get":
        if context.text_get_handler is None:
            return "Error: text_get tool is not available."
        target = args.get("target", "")
        try:
            result = context.text_get_handler(target)
            if isinstance(result, str) and result.startswith("Error:"):
                return result
            return HIDE_TOOL_RESULT_PREFIX + (result or "")
        except Exception as e:
            print(f"Error in text_get_handler: {e}")
            return f"Error reading text target: {e}"

    elif tool_name == "apply_text_edit":
        if context.text_edit_handler is None:
            return "Error: apply_text_edit tool is not available."
        target = args.get("target", "")
        operation = args.get("operation", "replace")
        text = args.get("text", "")
        summary = args.get("summary")
        try:
            result = context.text_edit_handler(target, operation, text, summary)
            return HIDE_TOOL_RESULT_PREFIX + (result or "")
        except Exception as e:
            print(f"Error in text_edit_handler: {e}")
            return f"Error applying text edit: {e}"

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
    text_get_handler=None,
    text_edit_handler=None,
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
    if text_get_handler is not None:
        enabled.add("text_get")
    if text_edit_handler is not None:
        enabled.add("apply_text_edit")
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
        text_edit_tool_enabled: bool = False,
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
        text_edit_tool_enabled : bool
            Whether the text edit tools are globally enabled.
        """
        self.image_tool_enabled = image_tool_enabled
        self.music_tool_enabled = music_tool_enabled
        self.read_aloud_tool_enabled = read_aloud_tool_enabled
        self.search_tool_enabled = search_tool_enabled
        self.text_edit_tool_enabled = text_edit_tool_enabled

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
        Return True if the given model should be routed to an image generation endpoint
        (i.e., the images API or a multimodal image generation API).
        
        This returns True for:
        - Dedicated image models with api_family="images" (dall-e-3, gpt-image-1)
        - Multimodal image models with the "multimodal_image_gen" quirk (Gemini image models)
        
        This returns False for:
        - Chat models that can generate images via tools (gpt-5.x with responses API)
        
        Parameters
        ----------
        model_name : str
            The model name.
        provider_name : str
            The provider name.
        custom_models : Optional[Dict[str, Dict[str, Any]]]
            Optional dict of custom model configurations.
        """
        if not model_name:
            return False

        card = get_card(model_name, custom_models)
        if card:
            # Check for dedicated image API models
            if card.api_family == "images":
                return True
            # Check for multimodal image generation models (Gemini)
            if card.quirks.get("multimodal_image_gen"):
                return True
            return False

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

    def supports_text_edit_tools(
        self,
        model_name: str,
        model_provider_map: Optional[Dict[str, str]] = None,
        custom_models: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> bool:
        """Return True if the given model should be offered text edit tools."""
        if not self.text_edit_tool_enabled:
            return False
        return self._model_supports_tool_calling(model_name, model_provider_map, custom_models)

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
        if self.supports_text_edit_tools(model_name, model_provider_map, custom_models):
            enabled.add("text_get")
            enabled.add("apply_text_edit")
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
