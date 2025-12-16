import os
from pathlib import Path

# Base directory of the project source files (location of ChatGTK.py, icon.png, etc.)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


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

# Define settings configuration with their types and defaults
SETTINGS_CONFIG = {
    'AI_NAME': {'type': str, 'default': 'Assistant'},
    'FONT_FAMILY': {'type': str, 'default': 'Sans'},
    'FONT_SIZE': {'type': int, 'default': 12},
    'USER_COLOR': {'type': str, 'default': '#2E7D32'},
    'AI_COLOR': {'type': str, 'default': '#0D47A1'},
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
    'REALTIME_PROMPT': {'type': str, 'default': 'Your name is {name}, speak quickly and professionally'},
    'MUTE_MIC_DURING_PLAYBACK': {'type': bool, 'default': True},
    'SIDEBAR_VISIBLE': {'type': bool, 'default': True},
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
    # Model whitelists per provider – comma-separated model IDs.
    # These defaults mirror the curated sets previously hardcoded in ai_providers.py.
    'OPENAI_MODEL_WHITELIST': {
        'type': str,
        # Include current realtime releases first, keep legacy preview IDs for backward compatibility.
        'default': 'dall-e-3,gpt-image-1,gpt-image-1-mini,gpt-4o-mini-realtime-preview-2024-12-17,gpt-4o-realtime-preview-2024-12-17,gpt-realtime,gpt-realtime-mini,chatgpt-4o-latest,gpt-4o-mini,gpt-4o-audio-preview,gpt-4o-mini-audio-preview,gpt-4o,gpt-4o-realtime-preview,gpt-4o-mini-realtime-preview,gpt-realtime-2025-08-28,gpt-realtime-mini-2025-10-06,o3,o3-mini,gpt-5.1,gpt-5.1-chat-latest'
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
    # Whether to include the conversation history folder in search tool queries.
    'SEARCH_HISTORY_ENABLED': {'type': bool, 'default': True},
    # Comma-separated list of additional directories to search (for documents, notes, etc.).
    'SEARCH_DIRECTORIES': {'type': str, 'default': ''},
    # Maximum number of search results to return to the model (1-5).
    'SEARCH_RESULT_LIMIT': {'type': int, 'default': 1},
    # Whether to show search results in the chat output (if False, results are only sent to the model).
    'SEARCH_SHOW_RESULTS': {'type': bool, 'default': False},
    # When enabled, closing or minimizing the main window can hide it to the
    # system tray instead of keeping it in the taskbar. A tray icon is shown
    # which can be used to restore or quit the application.
    'MINIMIZE_TO_TRAY_ENABLED': {'type': bool, 'default': False},
}
