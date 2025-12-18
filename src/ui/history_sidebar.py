"""
History sidebar UI component.

This component manages the chat history list in the sidebar.
It subscribes to events for reactive updates.
"""

from typing import Optional, Callable, List, Dict, Any

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib

from .base import UIComponent
from events import EventBus, EventType


class HistorySidebar(UIComponent):
    """
    Sidebar component for displaying and managing chat history.
    
    This component:
    - Displays list of saved chats
    - Handles chat selection
    - Provides filtering functionality
    - Emits events when user interacts with history
    
    Note: This is a reference implementation. The actual sidebar
    is still in ChatGTK.py but can be migrated to use this pattern.
    """
    
    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        on_chat_selected: Optional[Callable[[str], None]] = None,
        on_new_chat: Optional[Callable[[], None]] = None,
    ):
        """
        Initialize the history sidebar.
        
        Parameters
        ----------
        event_bus : Optional[EventBus]
            Event bus for communication.
        on_chat_selected : Optional[Callable[[str], None]]
            Callback when a chat is selected.
        on_new_chat : Optional[Callable[[], None]]
            Callback when new chat is requested.
        """
        super().__init__(event_bus)
        
        self._on_chat_selected = on_chat_selected
        self._on_new_chat = on_new_chat
        self._filter_text = ""
        
        # Build UI
        self.widget = self._build_ui()
        
        # Subscribe to events
        self.subscribe(EventType.CHAT_SAVED, self._on_chat_saved)
        self.subscribe(EventType.CHAT_DELETED, self._on_chat_deleted)
        self.subscribe(EventType.CHAT_LOADED, self._on_chat_loaded)
    
    def _build_ui(self) -> Gtk.Box:
        """Build the sidebar UI."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(10)
        box.set_margin_end(10)
        
        # New Chat button
        new_chat_btn = Gtk.Button(label="New Chat")
        new_chat_btn.connect('clicked', self._on_new_chat_clicked)
        box.pack_start(new_chat_btn, False, False, 0)
        
        # Scrolled window for history list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box.pack_start(scrolled, True, True, 0)
        
        # History list
        self.history_list = Gtk.ListBox()
        self.history_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.history_list.connect('row-activated', self._on_row_activated)
        self.history_list.get_style_context().add_class('navigation-sidebar')
        scrolled.add(self.history_list)
        
        # Filter entry
        filter_entry = Gtk.SearchEntry()
        filter_entry.set_placeholder_text("Filter history...")
        filter_entry.connect("changed", self._on_filter_changed)
        box.pack_start(filter_entry, False, False, 0)
        self.filter_entry = filter_entry
        
        return box
    
    def refresh(self, histories: List[Dict[str, Any]]) -> None:
        """
        Refresh the history list with new data.
        
        Parameters
        ----------
        histories : List[Dict[str, Any]]
            List of chat history metadata.
        """
        # Clear existing rows
        for child in self.history_list.get_children():
            self.history_list.remove(child)
        
        # Filter if needed
        if self._filter_text:
            histories = [
                h for h in histories
                if self._filter_text.lower() in h.get('first_message', '').lower()
            ]
        
        # Add rows
        for history in histories:
            row = self._create_history_row(history)
            self.history_list.add(row)
        
        self.history_list.show_all()
    
    def _create_history_row(self, history: Dict[str, Any]) -> Gtk.ListBoxRow:
        """Create a row for a chat history entry."""
        row = Gtk.ListBoxRow()
        row.filename = history.get('filename', '')
        
        label = Gtk.Label(label=history.get('first_message', 'Untitled'))
        label.set_xalign(0)
        label.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
        label.set_max_width_chars(25)
        
        row.add(label)
        return row
    
    def _on_new_chat_clicked(self, button) -> None:
        """Handle new chat button click."""
        if self._on_new_chat:
            self._on_new_chat()
        self.emit(EventType.CHAT_CREATED, source='sidebar')
    
    def _on_row_activated(self, listbox, row) -> None:
        """Handle history row selection."""
        if row and hasattr(row, 'filename'):
            chat_id = row.filename.replace('.json', '')
            if self._on_chat_selected:
                self._on_chat_selected(chat_id)
    
    def _on_filter_changed(self, entry) -> None:
        """Handle filter text change."""
        self._filter_text = entry.get_text().strip()
        # Emit event to request refresh with filter
        self.emit(EventType.SETTINGS_CHANGED, key='history_filter', value=self._filter_text)
    
    def _on_chat_saved(self, event) -> None:
        """Handle CHAT_SAVED event."""
        # Request refresh from parent
        pass
    
    def _on_chat_deleted(self, event) -> None:
        """Handle CHAT_DELETED event."""
        # Request refresh from parent
        pass
    
    def _on_chat_loaded(self, event) -> None:
        """Handle CHAT_LOADED event - highlight loaded chat."""
        chat_id = event.data.get('chat_id', '')
        # Could highlight the loaded chat in the list
        pass
