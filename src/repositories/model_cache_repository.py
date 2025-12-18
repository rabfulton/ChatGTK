"""
Repository for managing model cache persistence.
"""

import json
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path

from config import MODEL_CACHE_FILE


class ModelCacheRepository:
    """
    Repository for managing cached model lists per provider.
    
    This repository handles caching of available models from each provider
    to avoid repeated API calls.
    """
    
    def __init__(self, cache_file: str = None):
        """
        Initialize the model cache repository.
        
        Parameters
        ----------
        cache_file : str, optional
            Path to the cache file. Defaults to MODEL_CACHE_FILE from config.
        """
        self.cache_file = Path(cache_file or MODEL_CACHE_FILE)
        self._cache: Dict[str, Dict] = {}
        self._load()
    
    def _load(self) -> None:
        """Load cache from file."""
        self._cache = {}
        
        if not self.cache_file.exists():
            return
        
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if isinstance(data, dict):
                self._cache = data
        
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading model cache: {e}")
    
    def get_models(self, provider: str) -> List[str]:
        """
        Get cached models for a provider.
        
        Parameters
        ----------
        provider : str
            The provider name (e.g., 'openai', 'gemini').
            
        Returns
        -------
        List[str]
            List of model IDs, or empty list if not cached.
        """
        provider = provider.lower()
        provider_data = self._cache.get(provider, {})
        # Handle both formats: list directly or {'models': [...]}
        if isinstance(provider_data, list):
            return provider_data
        return provider_data.get('models', [])
    
    def set_models(self, provider: str, models: List[str]) -> None:
        """
        Set cached models for a provider.
        
        Parameters
        ----------
        provider : str
            The provider name.
        models : List[str]
            List of model IDs to cache.
        """
        provider = provider.lower()
        
        self._cache[provider] = {
            'models': models,
            'last_updated': datetime.now().isoformat(),
        }
    
    def invalidate(self, provider: str) -> None:
        """
        Invalidate (clear) the cache for a provider.
        
        Parameters
        ----------
        provider : str
            The provider name.
        """
        provider = provider.lower()
        if provider in self._cache:
            del self._cache[provider]
    
    def invalidate_all(self) -> None:
        """Invalidate the entire cache."""
        self._cache = {}
    
    def get_last_updated(self, provider: str) -> Optional[datetime]:
        """
        Get the last update timestamp for a provider's cache.
        
        Parameters
        ----------
        provider : str
            The provider name.
            
        Returns
        -------
        Optional[datetime]
            The last update timestamp, or None if not cached.
        """
        provider = provider.lower()
        provider_data = self._cache.get(provider, {})
        timestamp_str = provider_data.get('last_updated')
        
        if not timestamp_str:
            return None
        
        try:
            return datetime.fromisoformat(timestamp_str)
        except (ValueError, TypeError):
            return None
    
    def is_stale(self, provider: str, max_age_hours: int = 24) -> bool:
        """
        Check if a provider's cache is stale.
        
        Parameters
        ----------
        provider : str
            The provider name.
        max_age_hours : int
            Maximum age in hours before cache is considered stale.
            
        Returns
        -------
        bool
            True if cache is stale or doesn't exist, False otherwise.
        """
        last_updated = self.get_last_updated(provider)
        
        if not last_updated:
            return True
        
        age = datetime.now() - last_updated
        return age.total_seconds() > (max_age_hours * 3600)
    
    def save(self) -> None:
        """Save cache to file."""
        try:
            # Ensure parent directory exists
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self._cache, f, indent=2)
        
        except IOError as e:
            print(f"Error saving model cache: {e}")
            raise
    
    def get_all_cached_providers(self) -> List[str]:
        """
        Get list of all providers with cached models.
        
        Returns
        -------
        List[str]
            List of provider names.
        """
        return list(self._cache.keys())
    
    def get_cache_stats(self) -> Dict[str, Dict]:
        """
        Get statistics about the cache.
        
        Returns
        -------
        Dict[str, Dict]
            Dictionary mapping provider names to cache statistics
            (model count, last updated timestamp).
        """
        stats = {}
        for provider, data in self._cache.items():
            # Handle both dict and list formats (legacy compatibility)
            if isinstance(data, dict):
                stats[provider] = {
                    'model_count': len(data.get('models', [])),
                    'last_updated': data.get('last_updated'),
                    'is_stale': self.is_stale(provider),
                }
            elif isinstance(data, list):
                # Legacy format: just a list of models
                stats[provider] = {
                    'model_count': len(data),
                    'last_updated': None,
                    'is_stale': True,
                }
        return stats
