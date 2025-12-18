"""
Repository for managing API keys persistence.
"""

import os
import json
from typing import Dict, Optional, List
from pathlib import Path

from config import API_KEYS_FILE
from utils import API_KEY_FIELDS, get_api_key_env_vars


class APIKeysRepository:
    """
    Repository for managing API keys.
    
    This repository handles loading, saving, and validating API keys
    stored in a JSON file, with support for environment variable references.
    """
    
    def __init__(self, api_keys_file: str = None):
        """
        Initialize the API keys repository.
        
        Parameters
        ----------
        api_keys_file : str, optional
            Path to the API keys file. Defaults to API_KEYS_FILE from config.
        """
        self.api_keys_file = Path(api_keys_file or API_KEYS_FILE)
        self._keys: Dict[str, str] = {}
        self._load()
    
    def _load(self) -> None:
        """Load API keys from file."""
        self._keys = {}
        
        if not self.api_keys_file.exists():
            return
        
        try:
            with open(self.api_keys_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if isinstance(data, dict):
                self._keys = data
        
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading API keys: {e}")
    
    def get_key(self, provider: str) -> Optional[str]:
        """
        Get an API key for a provider.
        
        This method resolves environment variable references (strings starting with $)
        and returns the actual key value.
        
        Parameters
        ----------
        provider : str
            The provider name (e.g., 'openai', 'gemini').
            
        Returns
        -------
        Optional[str]
            The API key if found, None otherwise.
        """
        provider = provider.lower()
        key_value = self._keys.get(provider)
        
        if not key_value:
            return None
        
        # Resolve environment variable reference
        if key_value.startswith('$'):
            env_var_name = key_value[1:]
            return os.environ.get(env_var_name)
        
        return key_value
    
    def get_raw_value(self, provider: str) -> Optional[str]:
        """
        Get the raw stored value for a provider (without resolving env vars).
        
        Parameters
        ----------
        provider : str
            The provider name.
            
        Returns
        -------
        Optional[str]
            The raw stored value (may be an env var reference like '$OPENAI_API_KEY').
        """
        return self._keys.get(provider.lower())
    
    def set_key(self, provider: str, key: str) -> None:
        """
        Set an API key for a provider.
        
        Parameters
        ----------
        provider : str
            The provider name.
        key : str
            The API key or environment variable reference (e.g., '$OPENAI_API_KEY').
        """
        provider = provider.lower()
        self._keys[provider] = key
    
    def delete_key(self, provider: str) -> None:
        """
        Delete an API key for a provider.
        
        Parameters
        ----------
        provider : str
            The provider name.
        """
        provider = provider.lower()
        if provider in self._keys:
            del self._keys[provider]
    
    def list_providers(self) -> List[str]:
        """
        List all providers with stored keys.
        
        Returns
        -------
        List[str]
            List of provider names.
        """
        return list(self._keys.keys())
    
    def save(self) -> None:
        """Save API keys to file."""
        try:
            # Ensure parent directory exists
            self.api_keys_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.api_keys_file, 'w', encoding='utf-8') as f:
                json.dump(self._keys, f, indent=2)
        
        except IOError as e:
            print(f"Error saving API keys: {e}")
            raise
    
    def validate_key_format(self, provider: str, key: str) -> bool:
        """
        Validate the format of an API key.
        
        This is a basic validation that checks if the key is non-empty
        and has a reasonable format. Provider-specific validation could
        be added in the future.
        
        Parameters
        ----------
        provider : str
            The provider name.
        key : str
            The API key to validate.
            
        Returns
        -------
        bool
            True if the key format appears valid, False otherwise.
        """
        if not key or not isinstance(key, str):
            return False
        
        key = key.strip()
        
        # Allow environment variable references
        if key.startswith('$'):
            return len(key) > 1
        
        # Basic validation: key should be at least 10 characters
        # and contain only alphanumeric characters, hyphens, and underscores
        if len(key) < 10:
            return False
        
        # Provider-specific validation could be added here
        # For now, just check it's not empty and has reasonable length
        return True
    
    def get_all_keys(self) -> Dict[str, str]:
        """
        Get all API keys (resolved).
        
        Returns
        -------
        Dict[str, str]
            Dictionary mapping provider names to resolved API keys.
        """
        resolved = {}
        for provider in self._keys:
            key = self.get_key(provider)
            if key:
                resolved[provider] = key
        return resolved
    
    def get_all_raw(self) -> Dict[str, str]:
        """
        Get all API keys (raw, unresolved).
        
        Returns
        -------
        Dict[str, str]
            Dictionary mapping provider names to raw stored values.
        """
        return self._keys.copy()
    
    def has_key(self, provider: str) -> bool:
        """
        Check if a provider has an API key configured.
        
        Parameters
        ----------
        provider : str
            The provider name.
            
        Returns
        -------
        bool
            True if the provider has a key configured, False otherwise.
        """
        key = self.get_key(provider)
        return bool(key)
