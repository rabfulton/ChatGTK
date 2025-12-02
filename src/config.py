import os

# Base directory of the project
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Paths
PARENT_DIR = os.path.dirname(BASE_DIR)
SETTINGS_FILE = os.path.join(PARENT_DIR, "settings.cfg")
HISTORY_DIR = os.path.join(PARENT_DIR, "history")
CHATGTK_SCRIPT = os.path.join(BASE_DIR, "ChatGTK.py")

# Define settings configuration with their types and defaults
SETTINGS_CONFIG = {
    'AI_NAME': {'type': str, 'default': 'Assistant'},
    'FONT_FAMILY': {'type': str, 'default': 'Sans'},
    'FONT_SIZE': {'type': int, 'default': 12},
    'USER_COLOR': {'type': str, 'default': '#2E7D32'},
    'AI_COLOR': {'type': str, 'default': '#0D47A1'},
    'DEFAULT_MODEL': {'type': str, 'default': 'gpt-3.5-turbo'},
    # Preferred image model for both autonomous tool calls and the `img:` prefix.
    # This can be any supported image-capable model from OpenAI, Gemini, or Grok.
    'IMAGE_MODEL': {'type': str, 'default': 'dall-e-3'},
    # Master switch for exposing the image-generation tool to text models.
    # When false, models will not be told about the tool and cannot call it.
    'IMAGE_TOOL_ENABLED': {'type': bool, 'default': True},
    # Master switch for exposing the music control tool (kew + MPRIS) to text models.
    # When false, models will not be told about the tool and cannot call it.
    'MUSIC_TOOL_ENABLED': {'type': bool, 'default': False},
    # When true, kew will be launched inside a separate terminal window for music playback.
    # This is useful if you want to see kew's UI and logs instead of running it headless.
    'MUSIC_LAUNCH_IN_TERMINAL': {'type': bool, 'default': False},
    # Command prefix used when launching kew in a terminal, e.g. "gnome-terminal --"
    # or "konsole -e". The kew command and its arguments will be appended to this.
    'MUSIC_TERMINAL_PREFIX': {'type': str, 'default': ''},
    'WINDOW_WIDTH': {'type': int, 'default': 800},
    'WINDOW_HEIGHT': {'type': int, 'default': 600},
    'SETTINGS_DIALOG_WIDTH': {'type': int, 'default': 950},
    'SETTINGS_DIALOG_HEIGHT': {'type': int, 'default': 800},
    'SYSTEM_MESSAGE': {'type': str, 'default': 'You are a helpful assistant.'},
    'TEMPERAMENT': {'type': float, 'default': 0.7},
    'MICROPHONE': {'type': str, 'default': 'default'},
    'TTS_VOICE': {'type': str, 'default': 'alloy'},
    'TTS_HD': {'type': bool, 'default': False},
    'REALTIME_VOICE': {'type': str, 'default': 'alloy'},
    'SIDEBAR_VISIBLE': {'type': bool, 'default': True},
    'SIDEBAR_WIDTH': {'type': int, 'default': 200},
    'MAX_TOKENS': {'type': int, 'default': 0},
    'SOURCE_THEME': {'type': str, 'default': 'solarized-dark'},
    'LATEX_DPI': {'type': int, 'default': 200},
    'LATEX_COLOR': {'type': str, 'default': '#000000'},
    # Model whitelists per provider – comma-separated model IDs.
    # These defaults mirror the curated sets previously hardcoded in ai_providers.py.
    'OPENAI_MODEL_WHITELIST': {
        'type': str,
        'default': 'gpt-3.5-turbo,gpt-4,dall-e-3,gpt-image-1,gpt-4o-mini-realtime-preview,o1-mini,o1-preview,chatgpt-4o-latest,gpt-4-turbo,gpt-4.1,gpt-4o-mini,gpt-4o-audio-preview,gpt-4o-mini-audio-preview,gpt-4o,gpt-4o-realtime-preview,gpt-realtime,o3,o3-mini,gpt-5.1,gpt-5.1-chat-latest,gpt-5-pro'
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
}
