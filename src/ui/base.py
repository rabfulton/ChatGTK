"""
Base class for UI components.
"""

from typing import Optional, Callable, List, Tuple
from events import EventBus, EventType, Event

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib


class UIComponent:
    """
    Base class for UI components.
    
    Provides common functionality for event subscription and GTK integration.
    """
    
    def __init__(self, event_bus: Optional[EventBus] = None):
        """
        Initialize the UI component.
        
        Parameters
        ----------
        event_bus : Optional[EventBus]
            Event bus for communication. If None, events are disabled.
        """
        self._event_bus = event_bus
        self._subscriptions: List[Tuple[EventType, Callable]] = []
    
    def subscribe(self, event_type: EventType, handler: Callable[[Event], None]) -> None:
        """Subscribe to an event type."""
        if self._event_bus:
            self._event_bus.subscribe(event_type, handler)
            self._subscriptions.append((event_type, handler))
    
    def emit(self, event_type: EventType, **data) -> None:
        """Emit an event."""
        if self._event_bus:
            self._event_bus.publish(Event(
                type=event_type,
                data=data,
                source=self.__class__.__name__
            ))
    
    def schedule_ui_update(self, callback: Callable, *args) -> None:
        """Schedule a callback to run on the GTK main thread."""
        GLib.idle_add(callback, *args)
    
    def cleanup(self) -> None:
        """Unsubscribe from all events. Call when component is destroyed."""
        if self._event_bus:
            for event_type, handler in self._subscriptions:
                self._event_bus.unsubscribe(event_type, handler)
        self._subscriptions.clear()
