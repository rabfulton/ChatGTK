import os
import json
from datetime import datetime
from pathlib import Path
import re

# Path to settings file (in same directory as this script)
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.cfg")

# Add these constants at the top with the other constants
HISTORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history")

DEFAULT_SETTINGS = {
    'AI_NAME': 'Sheila',
    'FONT_FAMILY': 'Sans',
    'FONT_SIZE': '12',
    'USER_COLOR': '#0000FF',
    'AI_COLOR': '#008000',
    'DEFAULT_MODEL': 'gpt-4o-mini',  # user-specified default
    'WINDOW_WIDTH': '900',
    'WINDOW_HEIGHT': '750',
    # New setting for system message
    'SYSTEM_MESSAGE': 'You are a helpful assistant named Sheila.',
    # New setting for temperature (we'll call it TEMPERAMENT)
    'TEMPERAMENT': '0.7',
    'MICROPHONE': 'default',  # New setting for microphone
    'TTS_VOICE': 'alloy',  # New setting for TTS voice
    'SIDEBAR_WIDTH': '200',
    'SIDEBAR_VISIBLE': 'True',  # Add this new setting
    'MAX_TOKENS': '0',  # Add default max_tokens setting (0 = no limit)
    'SOURCE_THEME': 'solarized-dark',  # Add default theme setting
}

def load_settings():
    """Load settings from the SETTINGS_FILE if it exists, returning a dict of key-value pairs."""
    settings = DEFAULT_SETTINGS.copy()
    
    # First check if file exists
    if not os.path.exists(SETTINGS_FILE):
        print(f"Settings file not found at: {SETTINGS_FILE}")
        return settings
        
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
                    if key in settings:
                        settings[key] = value
            #print(f"Successfully loaded settings from {SETTINGS_FILE}")
            return settings
    except Exception as e:
        print(f"Error loading settings: {e}")
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

def ensure_history_dir():
    """Ensure the history directory exists."""
    Path(HISTORY_DIR).mkdir(parents=True, exist_ok=True)

def generate_chat_name(first_message):
    """Generate a filename for the chat based on first message and timestamp."""
    # Truncate first message to 40 chars for filename
    truncated_msg = first_message[:40].strip()
    # Remove any characters that might be problematic in filenames
    safe_msg = re.sub(r'[^\w\s-]', '', truncated_msg)
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
