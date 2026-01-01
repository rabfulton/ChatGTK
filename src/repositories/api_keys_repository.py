"""
Repository for managing API keys persistence.
"""

import os
import json
from typing import Dict, Optional, List
from pathlib import Path

from config import API_KEYS_FILE
from utils import API_KEY_FIELDS, get_api_key_env_vars

# Keyring is imported lazily to avoid slow startup
keyring = None
KEYRING_AVAILABLE = True  # Assume available, will be set False on import failure

KEYRING_SERVICE = "chatgtk"


def _get_keyring():
    """Lazily import keyring module."""
    global keyring, KEYRING_AVAILABLE
    if keyring is None and KEYRING_AVAILABLE:
        try:
            import keyring as kr
            keyring = kr
        except ImportError:
            KEYRING_AVAILABLE = False
    return keyring


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


class KeyringAPIKeysRepository(APIKeysRepository):
    """
    API keys repository that stores keys in the system keyring.
    Falls back to file storage if keyring is unavailable.
    """
    
    def __init__(self, api_keys_file: str = None, use_keyring: bool = False):
        self.api_keys_file = Path(api_keys_file or API_KEYS_FILE)
        self._keys: Dict[str, str] = {}
        self._use_keyring = use_keyring and KEYRING_AVAILABLE
        self._loaded = False
    
    def _ensure_loaded(self) -> None:
        """Lazy load keys on first access."""
        if self._loaded:
            return
        self._loaded = True
        if self._use_keyring:
            try:
                self._load_from_keyring()
            except Exception as e:
                print(f"Keyring load failed, falling back to file: {e}")
                self._use_keyring = False
                super()._load()
        else:
            super()._load()
    
    def _load(self) -> None:
        """Load API keys from keyring or file based on setting."""
        self._keys = {}
        if self._use_keyring:
            self._load_from_keyring()
        else:
            super()._load()
    
    def _load_from_keyring(self) -> None:
        """Load keys from system keyring."""
        kr = _get_keyring()
        if not kr:
            return
        try:
            index_str = kr.get_password(KEYRING_SERVICE, "_index")
            if not index_str:
                return
            providers = json.loads(index_str)
            for provider in providers:
                value = kr.get_password(KEYRING_SERVICE, provider)
                if value:
                    self._keys[provider] = value
        except Exception as e:
            print(f"Error loading from keyring: {e}")
    
    def get_key(self, provider: str) -> Optional[str]:
        self._ensure_loaded()
        return super().get_key(provider)
    
    def get_raw_value(self, provider: str) -> Optional[str]:
        self._ensure_loaded()
        return super().get_raw_value(provider)
    
    def list_providers(self) -> List[str]:
        self._ensure_loaded()
        return super().list_providers()
    
    def get_all_keys(self) -> Dict[str, str]:
        self._ensure_loaded()
        return super().get_all_keys()
    
    def get_all_raw(self) -> Dict[str, str]:
        self._ensure_loaded()
        return super().get_all_raw()
    
    def has_key(self, provider: str) -> bool:
        self._ensure_loaded()
        return super().has_key(provider)
    
    def save(self) -> None:
        """Save API keys to keyring or file based on setting."""
        if self._use_keyring:
            self._save_to_keyring()
        else:
            super().save()
    
    def _save_to_keyring(self) -> None:
        """Save keys to system keyring."""
        kr = _get_keyring()
        if not kr:
            return
        try:
            for provider, value in self._keys.items():
                if value:
                    kr.set_password(KEYRING_SERVICE, provider, value)
            kr.set_password(KEYRING_SERVICE, "_index", json.dumps(list(self._keys.keys())))
        except Exception as e:
            print(f"Error saving to keyring: {e}")
            raise
    
    def migrate_to_keyring(self) -> int:
        """
        Migrate keys from file to keyring.
        Returns the number of keys migrated.
        """
        kr = _get_keyring()
        if not kr:
            raise RuntimeError("Keyring not available")
        
        # Load from file first
        file_keys = {}
        if self.api_keys_file.exists():
            try:
                with open(self.api_keys_file, 'r', encoding='utf-8') as f:
                    file_keys = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        
        # Merge: file keys first, then current keys override
        merged = dict(file_keys)
        merged.update(self._keys)
        self._keys = merged
        
        # Save to keyring
        self._use_keyring = True
        self._save_to_keyring()
        
        # Verify the write worked by reading back
        kr = _get_keyring()
        verify_keys = {}
        try:
            index_str = kr.get_password(KEYRING_SERVICE, "_index")
            if index_str:
                providers = json.loads(index_str)
                for provider in providers:
                    val = kr.get_password(KEYRING_SERVICE, provider)
                    if val:
                        verify_keys[provider] = val
        except Exception as e:
            raise RuntimeError(f"Keyring write verification failed: {e}")
        
        if len(verify_keys) < len([k for k, v in self._keys.items() if v]):
            raise RuntimeError("Keyring write verification failed - not all keys were stored")
        
        # Only remove file after successful verification
        if self.api_keys_file.exists():
            try:
                self.api_keys_file.unlink()
            except IOError as e:
                print(f"Warning: Could not remove api_keys.json: {e}")
        
        return len(self._keys)
    
    def migrate_to_file(self) -> int:
        """
        Migrate keys from keyring to file.
        Returns the number of keys migrated.
        """
        # Load from keyring first
        if self._use_keyring:
            self._load_from_keyring()
        
        # Save to file
        self._use_keyring = False
        super().save()
        
        # Remove from keyring
        kr = _get_keyring()
        if kr:
            try:
                index_str = kr.get_password(KEYRING_SERVICE, "_index")
                if index_str:
                    providers = json.loads(index_str)
                    for provider in providers:
                        try:
                            kr.delete_password(KEYRING_SERVICE, provider)
                        except Exception:
                            pass
                    kr.delete_password(KEYRING_SERVICE, "_index")
            except Exception as e:
                print(f"Warning: Could not clear keyring: {e}")
        
        return len(self._keys)
    
    def set_use_keyring(self, use_keyring: bool) -> None:
        """Update the keyring usage setting."""
        self._use_keyring = use_keyring and KEYRING_AVAILABLE
