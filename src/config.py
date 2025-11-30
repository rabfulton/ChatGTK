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
    'WINDOW_WIDTH': {'type': int, 'default': 800},
    'WINDOW_HEIGHT': {'type': int, 'default': 600},
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
    'LATEX_COLOR': {'type': str, 'default': '#000000'}
}
