"""
Chat view UI component.

This component manages the message display area.
It wraps the MessageRenderer and provides event-driven updates.
"""

from typing import Optional, Callable, List, Any

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib

from .base import UIComponent
from events import EventBus, EventType


class ChatView(UIComponent):
    """
    Chat view component for displaying conversation messages.
    
    Features:
    - Scrollable message display
    - Delegates rendering to MessageRenderer
    - Event-driven message updates
    - Thinking animation support
    """
    
    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        window: Any = None,
    ):
        """
        Initialize the chat view.
        
        Parameters
        ----------
        event_bus : Optional[EventBus]
            Event bus for communication.
        window : Any
            Parent window for dialogs and URI handling.
        """
        super().__init__(event_bus)
        
        self._window = window
        self._message_renderer = None
        self._thinking_container = None
        self.message_widgets: List[Any] = []
        
        # Build UI
        self.widget, self.conversation_box = self._build_ui()
        
        # Subscribe to events
        self.subscribe(EventType.THINKING_STARTED, self._on_thinking_started)
        self.subscribe(EventType.THINKING_STOPPED, self._on_thinking_stopped)
    
    def _build_ui(self):
        """Build the chat view UI."""
        # Scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        
        # Conversation box
        conversation_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        conversation_box.set_margin_start(0)
        conversation_box.set_margin_end(5)
        conversation_box.set_margin_top(0)
        conversation_box.set_margin_bottom(5)
        scrolled.add(conversation_box)
        
        return scrolled, conversation_box
    
    def set_message_renderer(self, renderer):
        """
        Set the message renderer.
        
        Parameters
        ----------
        renderer : MessageRenderer
            The message renderer instance.
        """
        self._message_renderer = renderer
    
    def append_message(self, sender: str, text: str, index: int):
        """
        Append a message to the view.
        
        Parameters
        ----------
        sender : str
            'user' or 'ai'
        text : str
            Message text (may contain HTML/markdown)
        index : int
            Message index in conversation
        """
        if self._message_renderer:
            self._message_renderer.append_message(sender, text, index)
    
    def clear(self):
        """Clear all messages from the view."""
        for child in self.conversation_box.get_children():
            child.destroy()
        self.message_widgets.clear()
    
    def update_chat_id(self, chat_id: str):
        """Update the current chat ID for image paths."""
        if self._message_renderer:
            self._message_renderer.update_chat_id(chat_id)
    
    def scroll_to_bottom(self):
        """Scroll to the bottom of the conversation."""
        adj = self.widget.get_vadjustment()
        GLib.idle_add(lambda: adj.set_value(adj.get_upper() - adj.get_page_size()))
    
    def show_thinking(self):
        """Show thinking animation."""
        self.schedule_ui_update(self._show_thinking_impl)
    
    def hide_thinking(self):
        """Hide thinking animation."""
        self.schedule_ui_update(self._hide_thinking_impl)
    
    def _show_thinking_impl(self):
        """Implementation of show thinking animation."""
        # Remove existing thinking container
        if self._thinking_container:
            self._thinking_container.destroy()
            self._thinking_container = None
        
        # Create thinking container
        self._thinking_container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        
        # Spinner
        spinner = Gtk.Spinner()
        spinner.start()
        self._thinking_container.pack_start(spinner, False, False, 0)
        
        # Label
        label = Gtk.Label(label="Thinking...")
        self._thinking_container.pack_start(label, False, False, 0)
        
        self.conversation_box.pack_start(self._thinking_container, False, False, 0)
        self._thinking_container.show_all()
        self.scroll_to_bottom()
    
    def _hide_thinking_impl(self):
        """Implementation of hide thinking animation."""
        if self._thinking_container:
            self._thinking_container.destroy()
            self._thinking_container = None
    
    def _on_thinking_started(self, event):
        """Handle THINKING_STARTED event."""
        self.show_thinking()
    
    def _on_thinking_stopped(self, event):
        """Handle THINKING_STOPPED event."""
        self.hide_thinking()
