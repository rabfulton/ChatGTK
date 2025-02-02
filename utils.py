import os
import json

# Path to settings file (in same directory as this script)
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.cfg")

def load_settings():
    """Load settings from the SETTINGS_FILE if it exists, returning a dict of key-value pairs."""
    settings = {
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
        'TTS_VOICE': 'alloy'  # New setting for TTS voice
    }
    
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
            print(f"Successfully loaded settings from {SETTINGS_FILE}")
            print(f"Loaded settings: {settings}")
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
