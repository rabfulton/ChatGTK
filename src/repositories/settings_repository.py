"""
Repository for managing application settings persistence.
"""

import os
from typing import Dict, Any, Optional
from pathlib import Path

from config import SETTINGS_FILE, SETTINGS_CONFIG

# DEFAULT_SETTINGS is computed from SETTINGS_CONFIG
DEFAULT_SETTINGS = {key: config['default'] for key, config in SETTINGS_CONFIG.items()}


class SettingsRepository:
    """
    Repository for managing application settings.
    
    This repository handles loading, saving, and validating settings
    stored in a configuration file.
    """
    
    def __init__(self, settings_file: str = None):
        """
        Initialize the settings repository.
        
        Parameters
        ----------
        settings_file : str, optional
            Path to the settings file. Defaults to SETTINGS_FILE from config.
        """
        self.settings_file = Path(settings_file or SETTINGS_FILE)
        self._settings: Dict[str, Any] = {}
        self._explicit_keys: set = set()
        self._load()
    
    def _load(self) -> None:
        """Load settings from file."""
        self._settings = DEFAULT_SETTINGS.copy()
        self._explicit_keys = set()
        
        if not self.settings_file.exists():
            return
        
        try:
            with open(self.settings_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip().upper()
                        value = value.strip()
                        
                        if key in SETTINGS_CONFIG:
                            self._explicit_keys.add(key)
                            try:
                                if SETTINGS_CONFIG[key]['type'] == bool:
                                    self._settings[key] = value.lower() == 'true'
                                elif SETTINGS_CONFIG[key]['type'] == str:
                                    self._settings[key] = value.replace('\\n', '\n').replace('\\r', '')
                                else:
                                    self._settings[key] = SETTINGS_CONFIG[key]['type'](value)
                            except ValueError:
                                pass
        
        except Exception as e:
            print(f"Error loading settings: {e}")
        
        # Apply legacy TTS settings migration
        self._migrate_legacy_tts_settings()
        # Apply tool menu migration defaults
        self._migrate_tool_menu_settings()
    
    def _migrate_legacy_tts_settings(self) -> None:
        """Migrate legacy TTS settings to unified settings."""
        legacy_provider_map = {
            'tts': 'openai',
            'gemini': 'gemini',
            'audio_preview': 'gpt-4o-audio-preview',
        }
        
        if 'TTS_VOICE_PROVIDER' not in self._explicit_keys:
            legacy_provider = self._settings.get('READ_ALOUD_PROVIDER', 'tts')
            if legacy_provider in legacy_provider_map:
                new_provider = legacy_provider_map[legacy_provider]
                self._settings['TTS_VOICE_PROVIDER'] = new_provider
        
        if 'TTS_VOICE' not in self._explicit_keys:
            legacy_voice = self._settings.get('READ_ALOUD_VOICE', 'alloy')
            if legacy_voice:
                self._settings['TTS_VOICE'] = legacy_voice
        
        if 'TTS_PROMPT_TEMPLATE' not in self._explicit_keys:
            legacy_template = self._settings.get('READ_ALOUD_AUDIO_PROMPT_TEMPLATE', '')
            if legacy_template:
                self._settings['TTS_PROMPT_TEMPLATE'] = legacy_template

    def _migrate_tool_menu_settings(self) -> None:
        """Default tool menu toggles to visibility settings when missing."""
        mapping = {
            'TOOL_MENU_IMAGE_ENABLED': 'IMAGE_TOOL_ENABLED',
            'TOOL_MENU_MUSIC_ENABLED': 'MUSIC_TOOL_ENABLED',
            'TOOL_MENU_WEB_SEARCH_ENABLED': 'WEB_SEARCH_ENABLED',
            'TOOL_MENU_READ_ALOUD_ENABLED': 'READ_ALOUD_TOOL_ENABLED',
            'TOOL_MENU_SEARCH_ENABLED': 'SEARCH_TOOL_ENABLED',
            'TOOL_MENU_TEXT_EDIT_ENABLED': 'TEXT_EDIT_TOOL_ENABLED',
            'TOOL_MENU_WOLFRAM_ENABLED': 'WOLFRAM_TOOL_ENABLED',
        }
        for runtime_key, visibility_key in mapping.items():
            if runtime_key not in self._explicit_keys:
                self._settings[runtime_key] = bool(self._settings.get(visibility_key, False))
    
    def get_all(self) -> Dict[str, Any]:
        """
        Get all settings.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary of all settings.
        """
        return self._settings.copy()
    
    def reload(self) -> None:
        """Reload settings from disk, discarding any cached values."""
        self._load()
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a setting value.
        
        Parameters
        ----------
        key : str
            The setting key (case-insensitive, will be uppercased).
        default : Any, optional
            Default value if key not found.
            
        Returns
        -------
        Any
            The setting value, or default if not found.
        """
        key = key.upper()
        return self._settings.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        """
        Set a setting value.
        
        Parameters
        ----------
        key : str
            The setting key (case-insensitive, will be uppercased).
        value : Any
            The value to set.
        """
        key = key.upper()
        
        if key in SETTINGS_CONFIG:
            # Type conversion
            expected_type = SETTINGS_CONFIG[key]['type']
            if not isinstance(value, expected_type):
                try:
                    if expected_type == bool:
                        if isinstance(value, str):
                            value = value.lower() == 'true'
                        else:
                            value = bool(value)
                    else:
                        value = expected_type(value)
                except (ValueError, TypeError) as e:
                    raise ValueError(f"Cannot convert value for {key} to {expected_type.__name__}: {e}")
        
        self._settings[key] = value
        self._explicit_keys.add(key)
    
    def save(self) -> None:
        """Save settings to file."""
        try:
            # Ensure parent directory exists
            self.settings_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                f.write("# ChatGTK Settings\n")
                f.write("# Format: KEY=VALUE\n\n")
                
                for key in sorted(self._settings.keys()):
                    if key not in SETTINGS_CONFIG:
                        continue
                    
                    value = self._settings[key]
                    
                    # Format value for writing
                    if isinstance(value, bool):
                        value_str = 'true' if value else 'false'
                    elif isinstance(value, str):
                        value_str = value.replace('\n', '\\n').replace('\r', '\\r')
                    else:
                        value_str = str(value)
                    
                    f.write(f"{key}={value_str}\n")
        
        except IOError as e:
            print(f"Error saving settings: {e}")
            raise
    
    def reset_to_defaults(self) -> None:
        """Reset all settings to their default values."""
        self._settings = DEFAULT_SETTINGS.copy()
        self._explicit_keys = set()
    
    def validate(self, key: str, value: Any) -> bool:
        """
        Validate a setting value.
        
        Parameters
        ----------
        key : str
            The setting key.
        value : Any
            The value to validate.
            
        Returns
        -------
        bool
            True if valid, False otherwise.
        """
        key = key.upper()
        
        if key not in SETTINGS_CONFIG:
            return False
        
        expected_type = SETTINGS_CONFIG[key]['type']
        
        # Check type compatibility
        if not isinstance(value, expected_type):
            try:
                if expected_type == bool:
                    if isinstance(value, str):
                        value.lower() in ('true', 'false')
                    else:
                        bool(value)
                else:
                    expected_type(value)
            except (ValueError, TypeError):
                return False
        
        # Additional validation rules can be added here
        # For example, checking ranges for numeric values
        
        return True
    
    def is_explicitly_set(self, key: str) -> bool:
        """
        Check if a setting was explicitly set in the config file.
        
        Parameters
        ----------
        key : str
            The setting key.
            
        Returns
        -------
        bool
            True if the setting was explicitly set, False if using default.
        """
        return key.upper() in self._explicit_keys
