import os
import json
from datetime import datetime
from pathlib import Path
import re
from config import SETTINGS_FILE, HISTORY_DIR, SETTINGS_CONFIG, API_KEYS_FILE, CUSTOM_MODELS_FILE

# Re-export GTK-specific functions for backward compatibility
# These are defined in gtk_utils.py to keep this module toolkit-agnostic
from gtk_utils import parse_color_to_rgba, insert_resized_image

# History dir getter for project support (can be overridden)
_history_dir_getter = None

def get_current_history_dir():
    """Get the current history directory (supports projects)."""
    if _history_dir_getter:
        return _history_dir_getter()
    return HISTORY_DIR

def set_history_dir_getter(getter):
    """Set the function used to get the current history directory."""
    global _history_dir_getter
    _history_dir_getter = getter

# Global repository instances (lazy-initialized)
# Import is deferred to avoid circular dependencies
_settings_repo = None
_api_keys_repo = None
_model_cache_repo = None
_chat_history_repo = None

def _get_settings_repo():
    """Get or create the settings repository instance."""
    global _settings_repo
    if _settings_repo is None:
        from repositories import SettingsRepository
        _settings_repo = SettingsRepository()
    return _settings_repo

def _get_api_keys_repo():
    """Get or create the API keys repository instance."""
    global _api_keys_repo
    if _api_keys_repo is None:
        from repositories import APIKeysRepository
        _api_keys_repo = APIKeysRepository()
    return _api_keys_repo

def _get_model_cache_repo():
    """Get or create the model cache repository instance."""
    global _model_cache_repo
    if _model_cache_repo is None:
        from repositories import ModelCacheRepository
        _model_cache_repo = ModelCacheRepository()
    return _model_cache_repo

def _get_chat_history_repo():
    """Get or create the chat history repository instance."""
    global _chat_history_repo
    if _chat_history_repo is None:
        from repositories import ChatHistoryRepository
        _chat_history_repo = ChatHistoryRepository()
    return _chat_history_repo


# Create DEFAULT_SETTINGS from SETTINGS_CONFIG
DEFAULT_SETTINGS = {key: config['default'] for key, config in SETTINGS_CONFIG.items()}

# Known API key fields we persist in a separate JSON file under PARENT_DIR.
API_KEY_FIELDS = ['openai', 'gemini', 'grok', 'claude', 'perplexity']

def get_api_key_env_vars():
    """
    Scan environment variables and return those matching *API_KEY or *API_SECRET pattern.
    Returns a dict of {var_name: value} for non-empty values.
    """
    result = {}
    for key, value in os.environ.items():
        if (key.endswith('_API_KEY') or key.endswith('_API_SECRET') or 
            key.endswith('_KEY') and 'API' in key):
            if value and value.strip():
                result[key] = value.strip()
    return result


def resolve_api_key(value):
    """
    Resolve an API key value. If it starts with '$', treat it as an env var reference.
    Returns the resolved value or empty string if env var not found.
    """
    if not value:
        return ''
    value = str(value).strip()
    if value.startswith('$'):
        env_var = value[1:]
        return os.environ.get(env_var, '')
    return value

def _migrate_legacy_tts_settings(settings, explicit_keys=None):
    """
    Migrate legacy READ_ALOUD_* settings to unified TTS_* settings.
    
    This handles backward compatibility for users upgrading from older versions
    that had separate Read Aloud settings. The new unified TTS settings are used
    by the play button, automatic read-aloud, and the read-aloud tool.
    
    Args:
        settings: The settings dict to migrate
        explicit_keys: Set of keys that were explicitly present in the settings file.
                      If None, migration is skipped to avoid overwriting user choices.
    """
    # If we don't know which keys were explicit, skip migration to be safe
    if explicit_keys is None:
        return settings
    
    # Map legacy READ_ALOUD_PROVIDER values to new TTS_VOICE_PROVIDER values
    legacy_provider_map = {
        'tts': 'openai',
        'gemini-tts': 'gemini',
        'gpt-4o-audio-preview': 'gpt-4o-audio-preview',
        'gpt-4o-mini-audio-preview': 'gpt-4o-mini-audio-preview',
    }
    
    # Only migrate if TTS_VOICE_PROVIDER was NOT explicitly set in the file
    # This prevents the legacy setting from overwriting user's explicit choice
    if 'TTS_VOICE_PROVIDER' not in explicit_keys:
        legacy_provider = settings.get('READ_ALOUD_PROVIDER', 'tts')
        if legacy_provider in legacy_provider_map:
            new_provider = legacy_provider_map[legacy_provider]
            settings['TTS_VOICE_PROVIDER'] = new_provider
    
    # Only migrate TTS_VOICE if not explicitly set
    if 'TTS_VOICE' not in explicit_keys:
        legacy_voice = settings.get('READ_ALOUD_VOICE', 'alloy')
        if legacy_voice:
            settings['TTS_VOICE'] = legacy_voice
    
    # Only migrate TTS_PROMPT_TEMPLATE if not explicitly set
    if 'TTS_PROMPT_TEMPLATE' not in explicit_keys:
        legacy_template = settings.get('READ_ALOUD_AUDIO_PROMPT_TEMPLATE', '')
        if legacy_template:
            settings['TTS_PROMPT_TEMPLATE'] = legacy_template
    
    return settings

def load_settings():
    """Load settings with type conversion based on config.
    
    DEPRECATED: Use SettingsRepository or SettingsManager directly.
    """
    # Use repository backend
    repo = _get_settings_repo()
    return repo.get_all()

def save_settings(settings_dict):
    """Save the settings dictionary to the SETTINGS_FILE in a simple key=value format.
    
    DEPRECATED: Use SettingsRepository or SettingsManager directly.
    """
    # Use repository backend
    repo = _get_settings_repo()
    for key, value in settings_dict.items():
        repo.set(key, value)
    repo.save()


def load_api_keys():
    """
    Load saved API keys from disk.

    Returns a dict keyed by provider name (openai, gemini, grok, claude, perplexity),
    plus any custom keys, defaulting to empty strings when no file or value exists.
    """
    # Use repository backend
    repo = _get_api_keys_repo()
    keys = {k: '' for k in API_KEY_FIELDS}
    
    # Get all raw (unresolved) keys from repository
    all_keys = repo.get_all_raw()
    
    # Populate standard keys
    for name in API_KEY_FIELDS:
        keys[name] = all_keys.get(name, '')
    
    # Add custom keys
    for name, value in all_keys.items():
        if name not in API_KEY_FIELDS:
            keys[name] = value
    
    return keys


def save_api_keys(api_keys: dict):
    """
    Persist API keys to disk in a small JSON file under PARENT_DIR.

    Standard provider fields and custom keys are written; all values are stored as strings.
    """
    # Use repository backend
    repo = _get_api_keys_repo()
    
    # Update all keys in repository
    for name, value in api_keys.items():
        if value is None:
            value = ''
        value = str(value).strip()
        if value:
            repo.set_key(name, value)
        else:
            # Remove empty keys
            repo.delete_key(name)
    
    repo.save()


def load_custom_models() -> dict:
    """
    Load custom model definitions from disk.

    Structure:
    {
        "model_id": {
            "display_name": "...",
            "model_name": "...",
            "endpoint": "...",
            "api_key": "...",
            "api_type": "chat.completions|responses|images|tts"
        }
    }
    """
    try:
        with open(CUSTOM_MODELS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"Error loading custom models: {e}")
    return {}


def save_custom_models(models: dict) -> None:
    """Persist custom model definitions to disk."""
    try:
        Path(CUSTOM_MODELS_FILE).parent.mkdir(parents=True, exist_ok=True)
        with open(CUSTOM_MODELS_FILE, 'w', encoding='utf-8') as f:
            json.dump(models or {}, f, indent=2)
    except Exception as e:
        print(f"Error saving custom models: {e}")


def load_model_display_names() -> dict:
    """
    Load model display name mappings from settings.
    
    Returns a dict mapping model_id -> display_name.
    """
    settings = load_settings()
    display_names_json = settings.get('MODEL_DISPLAY_NAMES', '') or ''
    
    if not display_names_json.strip():
        return {}
    
    try:
        data = json.loads(display_names_json)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    
    return {}


def save_model_display_names(display_names: dict) -> None:
    """
    Save model display name mappings to settings.
    
    Args:
        display_names: dict mapping model_id -> display_name
    """
    settings = load_settings()
    # Remove empty display names
    cleaned = {k: v for k, v in display_names.items() if v and v.strip()}
    settings['MODEL_DISPLAY_NAMES'] = json.dumps(cleaned) if cleaned else ''
    save_settings(settings)


def get_model_display_name(model_id: str, custom_models: dict = None) -> str:
    """
    Get the display name for a model, checking custom models first, then display names setting.
    
    Args:
        model_id: The model identifier
        custom_models: Optional dict of custom model definitions (from load_custom_models())
    
    Returns:
        Display name if available and different from model_id, otherwise empty string
        (This allows the dropdown to show only display name when set, or model_id when not)
    """
    display_name = None
    
    # Check custom models first (they have display_name in their structure)
    if custom_models:
        custom_model = custom_models.get(model_id)
        if custom_model and custom_model.get('display_name'):
            display_name = custom_model['display_name']
    
    # Check the display names setting if not found in custom models
    if not display_name:
        display_names = load_model_display_names()
        display_name = display_names.get(model_id, '')
    
    # Return display name only if it's set and different from model_id
    if display_name and display_name.strip() and display_name != model_id:
        return display_name
    
    # Return empty string so caller can use model_id
    return ''

def ensure_history_dir():
    """Ensure the history directory exists."""
    Path(get_current_history_dir()).mkdir(parents=True, exist_ok=True)

def clean_display_text(text):
    """Strip markdown and normalize whitespace for sidebars and titles."""
    if not text:
        return ""
    # Remove markdown headers (### ), bold (**), italic (*), code (`)
    text = re.sub(r'[#*`]', '', text)
    # Remove list markers (- , 1. ) at start of lines (though we flatten lines anyway)
    text = re.sub(r'^\s*[-*]\s+', '', text)
    # Normalize unicode whitespace and newlines to single space
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def generate_chat_name(first_message):
    """Generate a filename for the chat based on first message and timestamp."""
    # Use clean_display_text to normalize whitespace and strip markdown
    clean_msg = clean_display_text(first_message)
    truncated_msg = clean_msg[:20].strip()
    # Remove any characters that might be problematic in filenames
    safe_msg = re.sub(r'[^\w\s-]', '', truncated_msg)
    safe_msg = safe_msg.replace(' ', '_')
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{safe_msg}_{timestamp}.json"

def save_chat_history(chat_name, conversation_history, metadata=None):
    """Save a chat history to a file with optional metadata.
    
    DEPRECATED: Use ChatHistoryRepository or ChatService directly.
    """
    # Use repository backend
    repo = _get_chat_history_repo()
    chat_id = chat_name.replace('.json', '') if chat_name.endswith('.json') else chat_name
    repo.save(chat_id, conversation_history, metadata)

def load_chat_history(chat_name, messages_only=True):
    """Load a chat history from a file.
    
    DEPRECATED: Use ChatHistoryRepository or ChatService directly.
    
    Args:
        chat_name: Name of the chat file
        messages_only: If True, returns only the messages. If False, returns full data structure
    """
    # Use repository backend
    repo = _get_chat_history_repo()
    chat_id = chat_name.replace('.json', '') if chat_name.endswith('.json') else chat_name
    conv = repo.get(chat_id)
    if conv is None:
        return [] if messages_only else {"messages": [], "metadata": {}}
    if messages_only:
        return conv.to_list()
    return {"messages": conv.to_list(), "metadata": conv.metadata or {}}

def delete_chat_history(chat_name):
    """Delete a chat history and its associated files (images, audio, etc.).
    
    DEPRECATED: Use ChatHistoryRepository or ChatService directly.
    
    Args:
        chat_name: Name of the chat file (with or without .json extension)
    
    Returns:
        bool: True if deletion was successful, False otherwise
    """
    # Use repository backend
    repo = _get_chat_history_repo()
    chat_id = chat_name.replace('.json', '') if chat_name.endswith('.json') else chat_name
    return repo.delete(chat_id)


def get_chat_dir(chat_name):
    """Get the directory path for a chat's associated files.
    
    Args:
        chat_name: Name of the chat file (with or without .json extension)
    
    Returns:
        Path: The directory path for the chat's files
    """
    if chat_name.endswith('.json'):
        chat_name = chat_name.replace('.json', '')
    return Path(get_current_history_dir()) / chat_name


def get_chat_metadata(chat_name):
    """Get metadata for a specific chat."""
    data = load_chat_history(chat_name, messages_only=False)
    return data.get("metadata", {})

def set_chat_title(chat_name, title):
    """Set a custom title for a chat."""
    data = load_chat_history(chat_name, messages_only=False)
    if "metadata" not in data:
        data["metadata"] = {}
    data["metadata"]["title"] = title
    save_chat_history(chat_name, data["messages"], data["metadata"])

def get_chat_title(chat_name):
    """Get the title for a chat, falling back to first message if no custom title."""
    metadata = get_chat_metadata(chat_name)
    if "title" in metadata:
        return metadata["title"]
    
    # Fall back to first message
    data = load_chat_history(chat_name, messages_only=False)  # Get full data structure
    messages = data.get("messages", []) if isinstance(data, dict) else data
    
    if messages and len(messages) > 1:  # Skip system message
        first_msg = messages[1].get("content", "")  # Get first user message
        return clean_display_text(first_msg)[:40] + ("..." if len(first_msg) > 40 else "")
    return "Untitled Chat"

def list_chat_histories():
    """List all saved chat histories."""
    # Use repository backend
    repo = _get_chat_history_repo()
    metadata_list = repo.list_all()
    
    histories = []
    for meta in metadata_list:
        # Clean display text (strip markdown and newlines)
        display_text = clean_display_text(meta.title or "Empty chat")
        histories.append({
            'filename': f"{meta.chat_id}.json",
            'first_message': display_text[:50] + '...' if len(display_text) > 50 else display_text
        })
    
    return histories


# Note: parse_color_to_rgba is re-exported from gtk_utils at the top of this file

def rgb_to_hex(color_str):
    """Convert rgb(r,g,b) color string to hex format (#RRGGBB).
    
    Args:
        color_str (str): Color in 'rgb(r,g,b)' format
    
    Returns:
        str: Color in hex format (#RRGGBB)
    """
    if color_str.startswith('rgb('):
        rgb_match = re.match(r'rgb\((\d+),\s*(\d+),\s*(\d+)\)', color_str)
        if rgb_match:
            r = int(rgb_match.group(1))
            g = int(rgb_match.group(2))
            b = int(rgb_match.group(3))
            return f'#{r:02x}{g:02x}{b:02x}'
    return color_str  # Return unchanged if not rgb format

# Note: insert_resized_image is re-exported from gtk_utils at the top of this file
