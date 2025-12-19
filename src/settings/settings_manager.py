"""
Unified settings manager for ChatGTK application.

Provides a single point of access for all application settings with:
- Type-safe access
- Validation
- Change notifications via events
- Caching for performance
"""

from typing import Any, Dict, Optional, Set
from repositories import SettingsRepository
from events import EventBus, EventType, Event
from config import SETTINGS_CONFIG


class SettingsManager:
    """
    Centralized settings management with event-based change notifications.
    
    This class provides a unified interface for accessing and modifying
    application settings, replacing scattered getattr/setattr patterns.
    """
    
    def __init__(
        self,
        repository: Optional[SettingsRepository] = None,
        event_bus: Optional[EventBus] = None,
    ):
        """
        Initialize the settings manager.
        
        Parameters
        ----------
        repository : Optional[SettingsRepository]
            Settings repository for persistence. Creates new if None.
        event_bus : Optional[EventBus]
            Event bus for change notifications. If None, no events emitted.
        """
        self._repo = repository or SettingsRepository()
        self._event_bus = event_bus
        self._cache: Dict[str, Any] = {}
        self._dirty: Set[str] = set()
        
        # Load all settings into cache
        self._cache = self._repo.get_all()
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a setting value.
        
        Parameters
        ----------
        key : str
            The setting key (e.g., 'DEFAULT_MODEL', 'FONT_SIZE').
        default : Any
            Default value if setting not found.
            
        Returns
        -------
        Any
            The setting value.
        """
        if key in self._cache:
            return self._cache[key]
        return default
    
    def set(self, key: str, value: Any, emit_event: bool = True) -> None:
        """
        Set a setting value.
        
        Parameters
        ----------
        key : str
            The setting key.
        value : Any
            The new value.
        emit_event : bool
            Whether to emit SETTINGS_CHANGED event.
        """
        old_value = self._cache.get(key)
        
        # Validate if we have config for this key
        if key in SETTINGS_CONFIG:
            value = self._coerce_type(key, value)
        
        self._cache[key] = value
        self._repo.set(key, value)
        self._dirty.add(key)
        
        if emit_event and self._event_bus and old_value != value:
            self._event_bus.publish(Event(
                type=EventType.SETTINGS_CHANGED,
                data={'key': key, 'value': value, 'old_value': old_value},
                source='settings_manager'
            ))
    
    def _coerce_type(self, key: str, value: Any) -> Any:
        """Coerce value to expected type based on SETTINGS_CONFIG."""
        config = SETTINGS_CONFIG.get(key, {})
        expected_type = config.get('type')
        
        if expected_type is None:
            return value
        
        try:
            if expected_type == bool:
                if isinstance(value, str):
                    return value.lower() in ('true', '1', 'yes')
                return bool(value)
            elif expected_type == int:
                return int(value) if value not in (None, '') else config.get('default', 0)
            elif expected_type == float:
                return float(value) if value not in (None, '') else config.get('default', 0.0)
            elif expected_type == str:
                return str(value) if value is not None else ''
        except (ValueError, TypeError):
            return config.get('default', value)
        
        return value
    
    def get_all(self) -> Dict[str, Any]:
        """
        Get all settings.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary of all settings.
        """
        return dict(self._cache)
    
    def get_section(self, prefix: str) -> Dict[str, Any]:
        """
        Get all settings with a given prefix.
        
        Parameters
        ----------
        prefix : str
            The prefix to filter by (e.g., 'TTS_', 'AUDIO_').
            
        Returns
        -------
        Dict[str, Any]
            Dictionary of matching settings.
        """
        return {
            k: v for k, v in self._cache.items()
            if k.startswith(prefix)
        }
    
    def save(self) -> None:
        """Persist all changes to disk."""
        self._repo.save()
        self._dirty.clear()
    
    def reload(self) -> None:
        """Reload settings from disk, discarding unsaved changes."""
        self._repo.reload()
        self._cache = self._repo.get_all()
        self._dirty.clear()
    
    def has_unsaved_changes(self) -> bool:
        """Check if there are unsaved changes."""
        return len(self._dirty) > 0
    
    def apply_to_object(self, obj: Any) -> None:
        """
        Apply all settings as attributes on an object.
        
        This provides backward compatibility with code that expects
        settings as object attributes.
        
        Parameters
        ----------
        obj : Any
            The object to apply settings to.
        """
        for key, value in self._cache.items():
            setattr(obj, key.lower(), value)
    
    def update_from_object(self, obj: Any, save: bool = False) -> None:
        """
        Update settings from object attributes.
        
        This provides backward compatibility with code that modifies
        settings via object attributes.
        
        Parameters
        ----------
        obj : Any
            The object to read settings from.
        save : bool
            Whether to persist changes immediately.
        """
        for key in self._cache.keys():
            attr = key.lower()
            if hasattr(obj, attr):
                value = getattr(obj, attr)
                if value != self._cache.get(key):
                    self.set(key, value, emit_event=False)
        
        if save:
            self.save()
    
    def __contains__(self, key: str) -> bool:
        """Check if a setting exists."""
        return key in self._cache
    
    def __getitem__(self, key: str) -> Any:
        """Get a setting value using bracket notation."""
        return self.get(key)
    
    def __setitem__(self, key: str, value: Any) -> None:
        """Set a setting value using bracket notation."""
        self.set(key, value)
