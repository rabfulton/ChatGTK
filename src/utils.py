import os
import json
from datetime import datetime
from pathlib import Path
import re
from config import SETTINGS_FILE, HISTORY_DIR, SETTINGS_CONFIG, API_KEYS_FILE, CUSTOM_MODELS_FILE

# Re-export GTK-specific functions for backward compatibility
# These are defined in gtk_utils.py to keep this module toolkit-agnostic
from gtk_utils import parse_color_to_rgba, insert_resized_image


# Create DEFAULT_SETTINGS from SETTINGS_CONFIG
DEFAULT_SETTINGS = {key: config['default'] for key, config in SETTINGS_CONFIG.items()}

# Known API key fields we persist in a separate JSON file under PARENT_DIR.
API_KEY_FIELDS = ['openai', 'gemini', 'grok', 'claude', 'perplexity']

def apply_settings(obj, settings):
    """Apply settings to object attributes (converting to lowercase)"""
    for key, value in settings.items():
        setattr(obj, key.lower(), value)

def get_object_settings(obj):
    """Get settings from object attributes (converting to uppercase)"""
    settings = {}
    for key in SETTINGS_CONFIG.keys():
        attr = key.lower()
        if hasattr(obj, attr):
            value = getattr(obj, attr)
            settings[key] = SETTINGS_CONFIG[key]['type'](value) if value is not None else None
    return settings

def convert_settings_for_save(settings):
    """Convert settings to strings for saving, with special handling for booleans"""
    converted = {}
    for key, value in settings.items():
        if isinstance(value, bool):
            converted[key] = str(value).lower()  # Convert True/False to 'true'/'false'
        else:
            converted[key] = str(value)
    return converted

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
    """Load settings with type conversion based on config."""
    settings = DEFAULT_SETTINGS.copy()
    explicit_keys = set()  # Track which keys were explicitly set in the file
    
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                # Expect format KEY=VALUE
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip().upper()
                    value = value.strip()
                    if key in SETTINGS_CONFIG:
                        explicit_keys.add(key)  # Mark this key as explicitly set
                        try:
                            # Special handling for boolean values
                            if SETTINGS_CONFIG[key]['type'] == bool:
                                settings[key] = value.lower() == 'true'
                            else:
                                settings[key] = SETTINGS_CONFIG[key]['type'](value)
                        except ValueError:
                            # If conversion fails, keep default value
                            pass 
    except FileNotFoundError:
        print(f"Settings file not found at: {SETTINGS_FILE}")
    except Exception as e:
        print(f"Error loading settings: {e}")
    
    # Apply migration for legacy TTS settings (only for keys not explicitly set)
    settings = _migrate_legacy_tts_settings(settings, explicit_keys)
    
    return settings

def save_settings(settings_dict):
    """Save the settings dictionary to the SETTINGS_FILE in a simple key=value format."""
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            f.write("# Application settings\n")
            for key, value in settings_dict.items():
                f.write(f"{key}={value}\n")
    except Exception as e:
        print(f"Error saving settings: {e}")


def load_api_keys():
    """
    Load saved API keys from disk.

    Returns a dict keyed by provider name (openai, gemini, grok, claude, perplexity),
    plus any custom keys, defaulting to empty strings when no file or value exists.
    """
    keys = {k: '' for k in API_KEY_FIELDS}
    try:
        with open(API_KEYS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            # Load standard keys
            for name in API_KEY_FIELDS:
                value = data.get(name, '')
                if value is None:
                    value = ''
                keys[name] = str(value).strip()
            # Load custom keys (keys that aren't in API_KEY_FIELDS)
            for name, value in data.items():
                if name not in API_KEY_FIELDS and name != '_custom':
                    if value is None:
                        value = ''
                    keys[name] = str(value).strip()
            # Also check for legacy _custom section
            if '_custom' in data and isinstance(data['_custom'], dict):
                for name, value in data['_custom'].items():
                    if value is None:
                        value = ''
                    keys[name] = str(value).strip()
    except FileNotFoundError:
        # No keys saved yet – this is fine.
        pass
    except Exception as e:
        print(f"Error loading API keys: {e}")
    return keys


def save_api_keys(api_keys: dict):
    """
    Persist API keys to disk in a small JSON file under PARENT_DIR.

    Standard provider fields and custom keys are written; all values are stored as strings.
    """
    try:
        Path(API_KEYS_FILE).parent.mkdir(parents=True, exist_ok=True)
        data = {}
        # Save standard keys
        for name in API_KEY_FIELDS:
            value = api_keys.get(name, '')
            if value is None:
                value = ''
            data[name] = str(value).strip()
        # Save custom keys (keys that aren't in API_KEY_FIELDS)
        for name, value in api_keys.items():
            if name not in API_KEY_FIELDS:
                if value is None:
                    value = ''
                data[name] = str(value).strip()
        with open(API_KEYS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error saving API keys: {e}")


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
    Path(HISTORY_DIR).mkdir(parents=True, exist_ok=True)

def generate_chat_name(first_message):
    """Generate a filename for the chat based on first message and timestamp."""
    # Truncate first message to 40 chars for filename
    truncated_msg = first_message[:20].strip()
    # Remove any characters that might be problematic in filenames
    safe_msg = re.sub(r'[^\w\s-]', '', truncated_msg)
    safe_msg = safe_msg.replace(' ', '_')
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{safe_msg}_{timestamp}.json"

def save_chat_history(chat_name, conversation_history, metadata=None):
    """Save a chat history to a file with optional metadata."""
    ensure_history_dir()
    
    # Add .json extension if not present
    if not chat_name.endswith('.json'):
        chat_name = f"{chat_name}.json"
    
    file_path = os.path.join(HISTORY_DIR, chat_name)
    
    # Create the full data structure
    chat_data = {
        "messages": conversation_history,
        "metadata": metadata or {}
    }
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(chat_data, f, indent=2)

def load_chat_history(chat_name, messages_only=True):
    """Load a chat history from a file.
    
    Args:
        chat_name: Name of the chat file
        messages_only: If True, returns only the messages. If False, returns full data structure
    """
    if not chat_name.endswith('.json'):
        chat_name = f"{chat_name}.json"
    
    file_path = os.path.join(HISTORY_DIR, chat_name)
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        # Handle old format (just an array of messages)
        if isinstance(data, list):
            return data if messages_only else {"messages": data, "metadata": {}}
            
        # Handle new format
        if messages_only:
            return data.get("messages", [])
        return data
            
    except FileNotFoundError:
        return [] if messages_only else {"messages": [], "metadata": {}}

def delete_chat_history(chat_name):
    """Delete a chat history and its associated files (images, audio, etc.).
    
    Args:
        chat_name: Name of the chat file (with or without .json extension)
    
    Returns:
        bool: True if deletion was successful, False otherwise
    """
    import shutil
    
    if not chat_name.endswith('.json'):
        chat_name = f"{chat_name}.json"
    
    try:
        # Delete the associated directory (images, audio, etc.)
        chat_dir = Path(HISTORY_DIR) / chat_name.replace('.json', '')
        if chat_dir.exists():
            shutil.rmtree(chat_dir)
        
        # Delete the history JSON file
        history_file = Path(HISTORY_DIR) / chat_name
        if history_file.exists():
            history_file.unlink()
        
        return True
    except Exception as e:
        print(f"Error deleting chat history {chat_name}: {e}")
        return False


def get_chat_dir(chat_name):
    """Get the directory path for a chat's associated files.
    
    Args:
        chat_name: Name of the chat file (with or without .json extension)
    
    Returns:
        Path: The directory path for the chat's files
    """
    if chat_name.endswith('.json'):
        chat_name = chat_name.replace('.json', '')
    return Path(HISTORY_DIR) / chat_name


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
        return first_msg[:40] + ("..." if len(first_msg) > 40 else "")
    return "Untitled Chat"

def list_chat_histories():
    """List all saved chat histories."""
    ensure_history_dir()
    histories = []
    
    try:
        for file in os.listdir(HISTORY_DIR):
            if file.endswith('.json'):
                file_path = os.path.join(HISTORY_DIR, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        # Handle both old and new formats
                        messages = data.get("messages", []) if isinstance(data, dict) else data
                        # Get first user message for display
                        first_message = next((msg['content'] for msg in messages if msg['role'] == 'user'), "Empty chat")
                        histories.append({
                            'filename': file,
                            'first_message': first_message[:50] + '...' if len(first_message) > 50 else first_message
                        })
                except Exception as e:
                    print(f"Error reading history file {file}: {e}")
    except Exception as e:
        print(f"Error listing chat histories: {e}")
    
    # Extract timestamp from filename and sort by it (newest first)
    def get_timestamp(filename):
        # Extract YYYYMMDD_HHMMSS from filename
        match = re.search(r'_(\d{8}_\d{6})\.json$', filename)
        timestamp = match.group(1) if match else '00000000_000000'
        return timestamp
    
    # Sort and print the order
    histories.sort(key=lambda x: get_timestamp(x['filename']), reverse=True)
    
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
