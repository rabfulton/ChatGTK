import os
from pathlib import Path
import subprocess

# Base directory of the project source files (location of ChatGTK.py, icon.png, etc.)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _has_playerctl() -> bool:
    """
    Return True if playerctl is available on this system.
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


def _default_data_root() -> str:
    """
    Determine a writable data root for ChatGTK.

    Priority:
      1. CHATGTK_DATA_DIR environment variable (explicit override)
      2. Legacy layout: parent of BASE_DIR if it already contains settings/history
      3. XDG data directory: $XDG_DATA_HOME/chatgtk or ~/.local/share/chatgtk
    """
    # 1) Explicit override for packagers/advanced users
    override = os.environ.get("CHATGTK_DATA_DIR")
    if override:
        return override

    # 2) Legacy behavior: use project root if it already has data files
    legacy_root = os.path.dirname(BASE_DIR)
    if (
        os.path.exists(os.path.join(legacy_root, "settings.cfg"))
        or os.path.isdir(os.path.join(legacy_root, "history"))
        or os.path.exists(os.path.join(legacy_root, "model_cache.json"))
    ):
        return legacy_root

    # 3) Default to XDG data directory
    home = str(Path.home())
    xdg_data_home = os.environ.get("XDG_DATA_HOME", os.path.join(home, ".local", "share"))
    return os.path.join(xdg_data_home, "chatgtk")


# Writable application data root (per-user by default)
PARENT_DIR = _default_data_root()

# Paths
SETTINGS_FILE = os.path.join(PARENT_DIR, "settings.cfg")
HISTORY_DIR = os.path.join(PARENT_DIR, "history")
MODEL_CACHE_FILE = os.path.join(PARENT_DIR, "model_cache.json")
# Separate file for persisting API keys across sessions. This keeps
# secrets out of the main settings.cfg while still using the same
# per-user data root.
API_KEYS_FILE = os.path.join(PARENT_DIR, "api_keys.json")
# Custom model definitions (including per-model API keys) are persisted
# separately from the standard settings and API key files.
CUSTOM_MODELS_FILE = os.path.join(PARENT_DIR, "custom_models.json")
# User overrides for model cards (capabilities, quirks, etc.)
MODEL_CARD_OVERRIDES_FILE = os.path.join(PARENT_DIR, "model_card_overrides.json")
CHATGTK_SCRIPT = os.path.join(BASE_DIR, "ChatGTK.py")

# Memory database path (Qdrant embedded)
MEMORY_DB_PATH = os.path.join(PARENT_DIR, "chat_memory")

# ---------------------------------------------------------------------------
# Default Appendix Constants (formerly in tools.py)
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT_APPENDIX = (
    "When writing mathematical equations use LaTeX syntax with parentheses: \\( ... \\) for inline math and \\[ ... \\] for block math. "
    "You format your responses using markdown."
)

DEFAULT_IMAGE_TOOL_PROMPT_APPENDIX = (
    "You have access to a generate_image tool that can create or edit images for the user "
    "from a natural language description. Use this tool when the user explicitly asks for "
    "an image or when a diagram, illustration, or example image would significantly help "
    "them understand the answer.\n\n"
    "Examples:\n"
    "  - 'Create an image of a cat' → prompt='A cute cat sitting comfortably'\n"
    "  - 'Draw a sunset over mountains' → prompt='A vibrant sunset with orange and pink hues over snow-capped mountains'\n"
    "  - 'Generate a diagram of a neural network' → prompt='A clear diagram showing neural network layers with nodes and connections'\n\n"
    "To edit an existing image, provide the image_path parameter with the path to the source image. "
    "After using the tool, describe the generated or edited image in your reply so the user knows what it contains."
)

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

DEFAULT_MUSIC_TOOL_PROMPT_APPENDIX = (
    _MUSIC_TOOL_PROMPT_BASE + _MUSIC_TOOL_PROMPT_PLAYERCTL
)

DEFAULT_READ_ALOUD_TOOL_PROMPT_APPENDIX = (
    "You have access to a read_aloud tool that can speak text aloud to the user "
    "using text-to-speech. Use this tool when the user asks you to read something "
    "out loud, announce something, or when audible output would enhance the user's "
    "experience (e.g. reading a poem, story, or important announcement)."
)

DEFAULT_SEARCH_TOOL_PROMPT_APPENDIX = (
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

DEFAULT_COMPACTION_PROMPT = (
    "Summarize the following conversation concisely for future context. Preserve key details, "
    "decisions, and context required for future reference."
)

DEFAULT_TEXT_EDIT_TOOL_PROMPT_APPENDIX = (
    "You can edit the currently selected target file using apply_text_edit. "
    "When a target file is selected, use target=\"file\". Use text_get with "
    "target=\"file\" to read the full text before editing.\n\n"
    "Operations (in order of preference):\n"
    "1. search_replace: Find exact text and replace it. Provide 'search' (text to find) "
    "and 'text' (replacement). The search must match EXACTLY including whitespace.\n"
    "2. replace: For small files, provide complete new content in 'text'.\n"
    "3. diff: Only for complex multi-location edits. Use valid unified diff format.\n\n"
    "Example search_replace:\n"
    "  operation: \"search_replace\"\n"
    "  search: \"def old_function():\\n    pass\"\n"
    "  text: \"def new_function():\\n    return True\"\n\n"
    "Always provide a short summary of the change."
)

DEFAULT_DOCUMENT_MODE_PROMPT_APPENDIX = (
    "You are in Document Mode. Your task is to edit the document directly.\n\n"
    "Use apply_text_edit with target=\"document\" to make changes. "
    "Use text_get with target=\"document\" to read the current content first.\n\n"
    "Operations (in order of preference):\n"
    "1. search_replace: Find exact text and replace it.\n"
    "2. replace: Provide complete new content.\n"
    "3. diff: Only for complex multi-location edits.\n\n"
    "Keep responses brief - just apply the edit and provide a short summary. "
    "Do not explain what you're going to do, just do it."
)

DEFAULT_TEXT_EDIT_TOOL_PROMPT_APPENDIX_LEGACY = (
    "You can edit a named text target using apply_text_edit. Use text_get to read "
    "the current text. Prefer operation=diff with unified diff text; use "
    "operation=replace only when needed. Provide a short summary of the change. "
    "When a target file is selected, use target=\"file\"."
)

# ---------------------------------------------------------------------------
# Default System Prompts
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPTS = [
    {
        "id": "default",
        "name": "Default",
        "content": "You are a helpful assistant."
    },
    {
        "id": "concise",
        "name": "Concise",
        "content": "You are a helpful assistant who values brevity. Get straight to the point. Avoid unnecessary preamble, filler phrases, and excessive explanation. Give direct, actionable answers. Use bullet points for lists. Only elaborate when explicitly asked."
    },
    {
        "id": "technical",
        "name": "Technical Expert",
        "content": "You are a senior software engineer and technical expert. Provide accurate, detailed technical explanations. Include code examples when relevant. Consider edge cases, performance implications, and best practices. Cite documentation or standards when applicable. Ask clarifying questions if the technical requirements are ambiguous."
    },
    {
        "id": "creative_images",
        "name": "Creative Artist",
        "content": "You are a creative visual artist specializing in generating compelling image prompts. When asked to create images, craft detailed, evocative descriptions that capture mood, lighting, composition, style, and artistic influences. Suggest interesting visual concepts, unexpected combinations, and artistic styles. For each request, offer variations or ask about preferences for style (photorealistic, illustration, oil painting, etc.), mood, and composition."
    },
    {
        "id": "roleplay",
        "name": "Storyteller",
        "content": "You are an imaginative storyteller and roleplay partner. Bring characters to life with distinct voices, mannerisms, and personalities. Set vivid scenes with sensory details. Maintain narrative consistency and remember established story elements. Adapt your tone to match the genre - whether whimsical fantasy, gritty noir, or heartfelt drama. Invite collaboration by leaving openings for the user to shape the story."
    },
]

import json as _json
DEFAULT_SYSTEM_PROMPTS_JSON = _json.dumps(DEFAULT_SYSTEM_PROMPTS)

# Define settings configuration with their types and defaults
SETTINGS_CONFIG = {
    'AI_NAME': {'type': str, 'default': 'Assistant'},
    'FONT_FAMILY': {'type': str, 'default': 'Sans'},
    'FONT_SIZE': {'type': int, 'default': 12},
    'USER_COLOR': {'type': str, 'default': '#2E7D32'},
    'AI_COLOR': {'type': str, 'default': '#0D47A1'},
    'GROUP_MODELS_BY_PROVIDER': {'type': bool, 'default': False},
    'DEFAULT_MODEL': {'type': str, 'default': 'gpt-4o-mini'},
    # Preferred image model for both autonomous tool calls and the `img:` prefix.
    # This can be any supported image-capable model from OpenAI, Gemini, or Grok.
    'IMAGE_MODEL': {'type': str, 'default': 'dall-e-3'},
    # Master switch for exposing the image-generation tool to text models.
    # When false, models will not be told about the tool and cannot call it.
    'IMAGE_TOOL_ENABLED': {'type': bool, 'default': False},
    # Master switch for exposing the music control tool (beets + local player) to text models.
    # When false, models will not be told about the tool and cannot call it.
    'MUSIC_TOOL_ENABLED': {'type': bool, 'default': False},
    # Master switch for enabling provider-native web search tools (OpenAI web_search
    # and Gemini google_search). When false, models will not be given access to
    # these web-grounded tools.
    'WEB_SEARCH_ENABLED': {'type': bool, 'default': False},
    # Path to the music player executable used for playback (e.g. mpv, vlc).
    'MUSIC_PLAYER_PATH': {'type': str, 'default': '/usr/bin/audacious -p <playlist>'},
    # Directory where music files are stored; used by beets to locate tracks.
    'MUSIC_LIBRARY_DIR': {'type': str, 'default': ''},
    # Path to the beets library database file. If empty, uses beets' default library.
    'MUSIC_LIBRARY_DB': {'type': str, 'default': ''},
    'WINDOW_WIDTH': {'type': int, 'default': 800},
    'WINDOW_HEIGHT': {'type': int, 'default': 600},
    'SETTINGS_DIALOG_WIDTH': {'type': int, 'default': 800},
    'SETTINGS_DIALOG_HEIGHT': {'type': int, 'default': 600},
    'PROMPT_EDITOR_DIALOG_WIDTH': {'type': int, 'default': 800},
    'PROMPT_EDITOR_DIALOG_HEIGHT': {'type': int, 'default': 500},
    'SYSTEM_MESSAGE': {'type': str, 'default': 'You are a helpful assistant.'},
    # JSON-encoded list of named system prompts. Each entry is a dict with keys:
    # "id" (unique identifier), "name" (display name), "content" (prompt text).
    # Example: [{"id":"default","name":"Default","content":"You are a helpful assistant."}]
    # If empty or invalid, a single prompt is synthesized from SYSTEM_MESSAGE.
    'SYSTEM_PROMPTS_JSON': {'type': str, 'default': ''},
    # The ID of the currently active system prompt from SYSTEM_PROMPTS_JSON.
    # If empty or not found, the first prompt in the list is used.
    'ACTIVE_SYSTEM_PROMPT_ID': {'type': str, 'default': ''},
    # JSON-encoded list of default prompt IDs that have been hidden/deleted by user.
    'HIDDEN_DEFAULT_PROMPTS': {'type': str, 'default': '[]'},
    'MICROPHONE': {'type': str, 'default': 'default'},
    # Speech-to-text model for voice input. Currently only Whisper variants are supported,
    # but future releases will list any model with audio input capability.
    'SPEECH_TO_TEXT_MODEL': {'type': str, 'default': 'whisper-1'},
    # TTS Voice Provider: 'openai' uses OpenAI TTS (tts-1/tts-1-hd), 'gemini' uses Gemini TTS,
    # 'gpt-4o-audio-preview' or 'gpt-4o-mini-audio-preview' uses audio-preview models.
    # This is the unified TTS setting used by the play button, auto read-aloud, and read-aloud tool.
    'TTS_VOICE_PROVIDER': {'type': str, 'default': 'openai'},
    'TTS_VOICE': {'type': str, 'default': 'alloy'},
    'TTS_HD': {'type': bool, 'default': False},
    # Speech prompt template for Gemini TTS and audio-preview models. Use {text} as placeholder.
    'TTS_PROMPT_TEMPLATE': {'type': str, 'default': ''},
    'REALTIME_VOICE': {'type': str, 'default': 'alloy'},
    'REALTIME_PROMPT': {'type': str, 'default': 'Your name is {name}, speak quickly and professionally. Respond in the same language as the user unless directed otherwise.'},
    'REALTIME_VAD_THRESHOLD': {'type': float, 'default': 0.1},
    'MUTE_MIC_DURING_PLAYBACK': {'type': bool, 'default': True},
    'SIDEBAR_VISIBLE': {'type': bool, 'default': True},
    'SIDEBAR_FILTER_VISIBLE': {'type': bool, 'default': False},
    'SIDEBAR_WIDTH': {'type': int, 'default': 200},
    'MAX_TOKENS': {'type': int, 'default': 0},
    # Conversation buffer length controls how much of the history is sent with
    # each request. Accepted values:
    #   - "ALL" (default): send the full conversation history.
    #   - "0": send only the latest non-system message.
    #   - Any positive integer N: send the last N non-system messages.
    'CONVERSATION_BUFFER_LENGTH': {'type': str, 'default': 'ALL'},
    'SOURCE_THEME': {'type': str, 'default': 'solarized-dark'},
    'LATEX_DPI': {'type': int, 'default': 200},
    'LATEX_COLOR': {'type': str, 'default': '#000000'},
    # Last active chat filename (without .json extension) to restore on startup
    'LAST_ACTIVE_CHAT': {'type': str, 'default': ''},
    'LAST_ACTIVE_DOCUMENT': {'type': str, 'default': ''},
    # Current project ID. Empty string means default history folder (no project).
    'CURRENT_PROJECT': {'type': str, 'default': ''},
    # Display name for the default history folder (empty project ID).
    'DEFAULT_PROJECT_LABEL': {'type': str, 'default': 'Default'},
    # Model whitelists per provider – comma-separated model IDs.
    # These defaults mirror the curated sets previously hardcoded in ai_providers.py.
    'OPENAI_MODEL_WHITELIST': {
        'type': str,
        # Include current realtime releases first, keep legacy preview IDs for backward compatibility.
        'default': 'dall-e-3,gpt-image-1,gpt-image-1-mini,gpt-realtime,gpt-realtime-mini,chatgpt-4o-latest,gpt-4o-mini,gpt-4o-audio-preview,gpt-4o-mini-audio-preview,gpt-4o,gpt-realtime-2025-08-28,gpt-realtime-mini-2025-10-06,o3,o3-mini,gpt-5.1,gpt-5.1-chat-latest'
    },
    'CUSTOM_MODEL_WHITELIST': {
        'type': str,
        'default': ''
    },
    'GEMINI_MODEL_WHITELIST': {
        'type': str,
        'default': 'gemini-2.5-flash,gemini-2.5-pro,gemini-2.5-flash-image,gemini-3-pro-preview,gemini-pro,gemini-pro-vision,gemini-pro-latest,gemini-flash-latest,gemini-3-pro-image-preview'
    },
    'GROK_MODEL_WHITELIST': {
        'type': str,
        'default': 'grok-2-1212,grok-2-vision-1212,grok-2-image-1212,grok-3,grok-3-mini,grok-4-1-fast-non-reasoning,grok-4-1-fast-reasoning,grok-4-fast-non-reasoning,grok-4-fast-reasoning'
    },
    'CLAUDE_MODEL_WHITELIST': {
        'type': str,
        'default': 'claude-sonnet-4-5,claude-haiku-4-5,claude-opus-4-5,claude-3-5-sonnet-latest,claude-3-5-haiku-latest'
    },
    'PERPLEXITY_MODEL_WHITELIST': {
        'type': str,
        'default': 'sonar,sonar-pro,sonar-reasoning'
    },
    # Model display names – JSON-encoded mapping of model_id -> display_name.
    # Example: {"gpt-4o-mini": "GPT-4o Mini", "gpt-4o": "GPT-4o"}
    # If a model has no display name, its model_id is used in the dropdown.
    'MODEL_DISPLAY_NAMES': {
        'type': str,
        'default': ''
    },
    # Read Aloud settings – automatically speak assistant responses.
    # When enabled, each new assistant message is read aloud using the selected provider.
    'READ_ALOUD_ENABLED': {'type': bool, 'default': False},
    # Provider for read-aloud: 'tts' uses OpenAI tts-1/tts-1-hd, 'gemini-tts' uses Gemini TTS, or use an audio-preview model.
    'READ_ALOUD_PROVIDER': {'type': str, 'default': 'tts'},
    # Voice for read-aloud. Should match the selected provider (OpenAI voices for tts/audio-preview, Gemini voices for gemini-tts).
    'READ_ALOUD_VOICE': {'type': str, 'default': 'nova'},
    # Prompt template for Gemini TTS and audio-preview models. {text} is replaced with the response text.
    'READ_ALOUD_AUDIO_PROMPT_TEMPLATE': {
        'type': str,
        'default': 'Please say the following verbatim in a New York accent: "{text}"'
    },
    # Master switch for exposing the read_aloud tool to text models.
    # When false, models will not be told about the tool and cannot call it.
    'READ_ALOUD_TOOL_ENABLED': {'type': bool, 'default': False},
    # Master switch for exposing the search/memory tool to text models.
    # When enabled, models can search past conversations and configured directories.
    'SEARCH_TOOL_ENABLED': {'type': bool, 'default': False},
    # Master switch for exposing the text edit tools to text models.
    'TEXT_EDIT_TOOL_ENABLED': {'type': bool, 'default': False},
    # Whether to include the conversation history folder in search tool queries.
    'SEARCH_HISTORY_ENABLED': {'type': bool, 'default': True},
    # Comma-separated list of additional directories to search (for documents, notes, etc.).
    'SEARCH_DIRECTORIES': {'type': str, 'default': ''},
    # Maximum number of search results to return to the model (1-5).
    'SEARCH_RESULT_LIMIT': {'type': int, 'default': 1},
    # Number of characters to show before and after a search match.
    'SEARCH_CONTEXT_WINDOW': {'type': int, 'default': 200},
    # Whether to show search results in the chat output (if False, results are only sent to the model).
    'SEARCH_SHOW_RESULTS': {'type': bool, 'default': False},
    # --- Memory System Settings ---
    # Master switch for the semantic memory feature (requires qdrant-client and sentence-transformers).
    'MEMORY_ENABLED': {'type': bool, 'default': False},
    # Embedding mode: "local" (sentence-transformers), "openai", "gemini", or "custom".
    'MEMORY_EMBEDDING_MODE': {'type': str, 'default': 'local'},
    # Embedding model name (depends on mode).
    'MEMORY_EMBEDDING_MODEL': {'type': str, 'default': 'all-MiniLM-L6-v2'},
    # What to store: "all", "user", or "assistant" messages.
    'MEMORY_STORE_MODE': {'type': str, 'default': 'all'},
    # Number of memory results to retrieve (1-10).
    'MEMORY_RETRIEVAL_TOP_K': {'type': int, 'default': 3},
    # Minimum similarity score for retrieval (0.0-1.0).
    'MEMORY_MIN_SIMILARITY': {'type': float, 'default': 0.7},
    # Whether to automatically add new messages to memory.
    'MEMORY_AUTO_IMPORT': {'type': bool, 'default': True},
    'MEMORY_AUTO_IMPORT': {'type': bool, 'default': True},
    # Prompt appendix for memory context injection.
    'MEMORY_PROMPT_APPENDIX': {
        'type': str,
        'default': 'You have access to retrieved information about the user from previous interactions. '
                   'Use the retrieved memories only when they are relevant to the user\'s current request. '
                   'Do not invent memories. If the retrieved memory does not seem relevant, ignore it.'
    },
    # When enabled, closing or minimizing the main window can hide it to the
    # system tray instead of keeping it in the taskbar. A tray icon is shown
    # which can be used to restore or quit the application.
    'MINIMIZE_TO_TRAY_ENABLED': {'type': bool, 'default': False},
    # --- Conversation Compaction Settings ---
    # When enabled, long conversations will be summarized to reduce token usage and costs.
    'COMPACTION_ENABLED': {'type': bool, 'default': False},
    # Maximum conversation size in kilobytes before triggering compaction.
    'COMPACTION_MAX_SIZE_KB': {'type': int, 'default': 100},
    'COMPACTION_PROMPT': {'type': str, 'default': DEFAULT_COMPACTION_PROMPT},
    # Number of recent user/assistant turns to keep after compaction.
    'COMPACTION_KEEP_TURNS': {'type': int, 'default': 0},
    # Prompt Appendices
    'SYSTEM_PROMPT_APPENDIX': {'type': str, 'default': DEFAULT_SYSTEM_PROMPT_APPENDIX},
    'IMAGE_TOOL_PROMPT_APPENDIX': {'type': str, 'default': DEFAULT_IMAGE_TOOL_PROMPT_APPENDIX},
    'MUSIC_TOOL_PROMPT_APPENDIX': {'type': str, 'default': DEFAULT_MUSIC_TOOL_PROMPT_APPENDIX},
    'READ_ALOUD_TOOL_PROMPT_APPENDIX': {'type': str, 'default': DEFAULT_READ_ALOUD_TOOL_PROMPT_APPENDIX},
    'SEARCH_TOOL_PROMPT_APPENDIX': {'type': str, 'default': DEFAULT_SEARCH_TOOL_PROMPT_APPENDIX},
    'TEXT_EDIT_TOOL_PROMPT_APPENDIX': {'type': str, 'default': DEFAULT_TEXT_EDIT_TOOL_PROMPT_APPENDIX},
    # Keyboard shortcuts - JSON-encoded dict mapping action names to key combos
    'KEYBOARD_SHORTCUTS': {'type': str, 'default': ''},
    # Model shortcuts - JSON-encoded dict mapping model_1..model_5 to model IDs
    'MODEL_SHORTCUTS': {'type': str, 'default': ''},
}

# Default keyboard shortcuts (action -> key combo string)
# Format: "<Ctrl>n" or "<Ctrl><Shift>n" or "<Alt>1" etc.
DEFAULT_SHORTCUTS = {
    # Global shortcuts
    'new_chat': '<Ctrl>n',
    'voice_input': '<Ctrl>r',
    'prompt_editor': '<Ctrl>e',
    'focus_input': 'Escape',
    'submit': '<Ctrl>Return',
    # Model switching (Alt+1 through Alt+9)
    'model_1': '<Alt>1',
    'model_2': '<Alt>2',
    'model_3': '<Alt>3',
    'model_4': '<Alt>4',
    'model_5': '<Alt>5',
    # Prompt editor formatting
    'editor_bold': '<Ctrl>b',
    'editor_italic': '<Ctrl>i',
    'editor_code': '<Ctrl>grave',
    'editor_h1': '<Ctrl>1',
    'editor_h2': '<Ctrl>2',
    'editor_h3': '<Ctrl>3',
    'editor_bullet_list': '<Ctrl><Shift>8',
    'editor_numbered_list': '<Ctrl><Shift>7',
    'editor_code_block': '<Ctrl><Shift>c',
    'editor_quote': '<Ctrl><Shift>period',
    'editor_emoji': '<Ctrl>period',
}
