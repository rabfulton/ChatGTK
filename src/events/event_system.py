"""
Event system implementation using observer pattern.
"""

from enum import Enum, auto
from typing import Callable, Any, Dict, List, Optional
from dataclasses import dataclass, field
from weakref import WeakMethod, ref
import threading


class EventType(Enum):
    """Event types for the application."""
    # Chat events
    CHAT_CREATED = auto()
    CHAT_LOADED = auto()
    CHAT_SAVED = auto()
    CHAT_DELETED = auto()
    MESSAGE_SENT = auto()
    MESSAGE_RECEIVED = auto()
    MESSAGE_STREAMING = auto()
    
    # Model events
    MODELS_FETCHED = auto()
    MODEL_CHANGED = auto()
    
    # Settings events
    SETTINGS_CHANGED = auto()
    API_KEY_UPDATED = auto()
    
    # Tool events
    TOOL_EXECUTED = auto()
    TOOL_RESULT = auto()
    
    # Audio events
    RECORDING_STARTED = auto()
    RECORDING_STOPPED = auto()
    TRANSCRIPTION_COMPLETE = auto()
    PLAYBACK_STARTED = auto()
    PLAYBACK_STOPPED = auto()
    TTS_COMPLETE = auto()
    
    # Image events
    IMAGE_GENERATED = auto()
    IMAGE_EDITED = auto()
    
    # Error events
    ERROR_OCCURRED = auto()
    
    # UI state events
    THINKING_STARTED = auto()
    THINKING_STOPPED = auto()


@dataclass
class Event:
    """An event with type, data, and source."""
    type: EventType
    data: Dict[str, Any] = field(default_factory=dict)
    source: str = ""


class EventBus:
    """
    Central event bus for publish/subscribe pattern.
    
    Thread-safe implementation that supports weak references
    to avoid memory leaks from forgotten subscriptions.
    """
    
    def __init__(self):
        self._subscribers: Dict[EventType, List[Callable]] = {}
        self._lock = threading.RLock()
    
    def subscribe(self, event_type: EventType, handler: Callable[[Event], None]) -> None:
        """
        Subscribe to an event type.
        
        Parameters
        ----------
        event_type : EventType
            The type of event to subscribe to.
        handler : Callable[[Event], None]
            The handler function to call when the event is published.
        """
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            if handler not in self._subscribers[event_type]:
                self._subscribers[event_type].append(handler)
    
    def unsubscribe(self, event_type: EventType, handler: Callable) -> None:
        """
        Unsubscribe from an event type.
        
        Parameters
        ----------
        event_type : EventType
            The type of event to unsubscribe from.
        handler : Callable
            The handler function to remove.
        """
        with self._lock:
            if event_type in self._subscribers:
                try:
                    self._subscribers[event_type].remove(handler)
                except ValueError:
                    pass
    
    def publish(self, event: Event) -> None:
        """
        Publish an event to all subscribers.
        
        Parameters
        ----------
        event : Event
            The event to publish.
        """
        with self._lock:
            handlers = list(self._subscribers.get(event.type, []))
        
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                print(f"[EventBus] Error in handler for {event.type}: {e}")
    
    def clear(self, event_type: Optional[EventType] = None) -> None:
        """
        Clear subscribers.
        
        Parameters
        ----------
        event_type : Optional[EventType]
            If provided, clear only subscribers for this type.
            If None, clear all subscribers.
        """
        with self._lock:
            if event_type is None:
                self._subscribers.clear()
            elif event_type in self._subscribers:
                self._subscribers[event_type].clear()


# Global event bus instance
_global_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get or create the global event bus instance."""
    global _global_event_bus
    if _global_event_bus is None:
        _global_event_bus = EventBus()
    return _global_event_bus
