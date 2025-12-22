"""
History sidebar UI component.

This component manages the chat history list in the sidebar.
It subscribes to events for reactive updates.
"""

from typing import Optional, Callable, List, Dict, Any
from datetime import datetime
import re

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Gdk, Pango

from .base import UIComponent
from events import EventBus, EventType


class HistorySidebar(UIComponent):
    """
    Sidebar component for displaying and managing chat history.
    
    Features:
    - Displays list of saved chats with title and timestamp
    - Handles chat selection and right-click context menu
    - Filtering with titles-only and whole-words options
    - Event-driven updates
    """
    
    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        controller: Any = None,
        on_chat_selected: Optional[Callable[[str], None]] = None,
        on_new_chat: Optional[Callable[[], None]] = None,
        on_delete_chat: Optional[Callable[[str], None]] = None,
        on_rename_chat: Optional[Callable[[str], None]] = None,
        on_export_chat: Optional[Callable[[str], None]] = None,
        on_context_menu: Optional[Callable[[Gtk.ListBoxRow, Gdk.EventButton], None]] = None,
        width: int = 200,
    ):
        """
        Initialize the history sidebar.
        
        Parameters
        ----------
        event_bus : Optional[EventBus]
            Event bus for communication.
        controller : Any
            Controller for fetching chat list.
        on_chat_selected : Optional[Callable[[str], None]]
            Callback when a chat is selected.
        on_new_chat : Optional[Callable[[], None]]
            Callback when new chat is requested.
        on_delete_chat : Optional[Callable[[str], None]]
            Callback when delete is requested.
        on_rename_chat : Optional[Callable[[str], None]]
            Callback when rename is requested.
        on_export_chat : Optional[Callable[[str], None]]
            Callback when export is requested.
        on_context_menu : Optional[Callable]
            Callback for custom context menu handling.
        width : int
            Initial sidebar width.
        """
        super().__init__(event_bus)
        
        self._controller = controller
        self._on_chat_selected = on_chat_selected
        self._on_new_chat = on_new_chat
        self._on_delete_chat = on_delete_chat
        self._on_rename_chat = on_rename_chat
        self._on_export_chat = on_export_chat
        self._on_context_menu = on_context_menu
        
        # Filter state
        self._filter_text = ""
        self._filter_titles_only = True
        self._filter_whole_words = False
        self._filter_timeout_id = None
        
        # Selection tracking
        self._current_chat_id = None
        
        # Build UI
        self.widget = self._build_ui()
        # Don't set minimum width - let the paned control sizing
        
        # Subscribe to events
        self.subscribe(EventType.CHAT_SAVED, self._on_chat_event)
        self.subscribe(EventType.CHAT_DELETED, self._on_chat_event)
        self.subscribe(EventType.CHAT_LOADED, self._on_chat_loaded)
        self.subscribe(EventType.CHAT_CREATED, self._on_chat_event)
        
        # Set initial filter visibility from settings
        show_filter = False
        if self._controller:
            show_filter = self._controller.get_setting('SIDEBAR_FILTER_VISIBLE', False)
        self.search_toggle.set_active(show_filter)
        self.filter_container.set_no_show_all(not show_filter)
        if not show_filter:
            self.filter_container.hide()
    
    def _build_ui(self) -> Gtk.Box:
        """Build the sidebar UI."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(10)
        box.set_margin_end(10)
        
        # Top row: Project button + Search toggle + New Chat button
        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        
        # Project selector button (folder icon)
        self.project_button = Gtk.MenuButton()
        self.project_button.set_image(Gtk.Image.new_from_icon_name("folder-symbolic", Gtk.IconSize.BUTTON))
        self.project_button.set_tooltip_text("Select Project")
        self._build_project_menu()
        top_row.pack_start(self.project_button, False, False, 0)
        
        # Search/filter toggle button
        self.search_toggle = Gtk.ToggleButton()
        self.search_toggle.set_image(Gtk.Image.new_from_icon_name("edit-find-symbolic", Gtk.IconSize.BUTTON))
        self.search_toggle.set_tooltip_text("Filter History")
        self.search_toggle.connect("toggled", self._on_search_toggled)
        top_row.pack_start(self.search_toggle, False, False, 0)
        
        # New Chat button
        new_chat_btn = Gtk.Button(label="New Chat")
        new_chat_btn.connect('clicked', self._on_new_chat_clicked)
        top_row.pack_start(new_chat_btn, False, False, 0)
        
        box.pack_start(top_row, False, False, 0)
        
        # Scrolled window for history list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box.pack_start(scrolled, True, True, 0)
        
        # History list
        self.history_list = Gtk.ListBox()
        self.history_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.history_list.connect('row-activated', self._on_row_activated)
        self.history_list.connect('button-press-event', self._on_button_press)
        self.history_list.get_style_context().add_class('navigation-sidebar')
        scrolled.add(self.history_list)
        
        # Filter container (hidden by default)
        self.filter_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        
        # Filter entry
        filter_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.filter_entry = Gtk.Entry()
        self.filter_entry.set_placeholder_text("Filter history...")
        self.filter_entry.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "edit-clear-symbolic")
        self.filter_entry.connect("changed", self._on_filter_changed)
        self.filter_entry.connect("icon-press", self._on_filter_icon_pressed)
        self.filter_entry.connect("key-press-event", self._on_filter_keypress)
        filter_box.pack_start(self.filter_entry, True, True, 0)
        self.filter_container.pack_start(filter_box, False, False, 0)
        
        # Filter options
        options_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        
        self.titles_only_toggle = Gtk.CheckButton(label="Titles only")
        self.titles_only_toggle.set_active(True)
        self.titles_only_toggle.connect("toggled", self._on_titles_only_toggled)
        options_box.pack_start(self.titles_only_toggle, False, False, 0)
        
        self.whole_words_toggle = Gtk.CheckButton(label="Whole Words")
        self.whole_words_toggle.set_active(False)
        self.whole_words_toggle.connect("toggled", self._on_whole_words_toggled)
        options_box.pack_start(self.whole_words_toggle, False, False, 0)
        
        self.filter_container.pack_start(options_box, False, False, 0)
        
        box.pack_start(self.filter_container, False, False, 0)
        
        return box
    
    def _on_search_toggled(self, button) -> None:
        """Handle search toggle button."""
        active = button.get_active()
        self.filter_container.set_no_show_all(not active)
        if active:
            self.filter_container.show_all()
            self.filter_entry.grab_focus()
        else:
            self.filter_container.hide()
            self.filter_entry.set_text("")
            self._filter_text = ""
            self.refresh()
        
        # Save state
        if self._controller:
            self._controller._settings_manager.set('SIDEBAR_FILTER_VISIBLE', active)
            self._controller._settings_manager.save()
    
    def refresh(self) -> None:
        """Refresh the history list from controller."""
        if not self._controller:
            return
        
        # Get histories
        histories = self._controller.list_chats()
        
        # Apply filter
        if self._filter_text:
            histories = [h for h in histories if self._matches_filter(h)]
        
        # Preserve selection
        selected_id = self._current_chat_id
        
        # Clear and repopulate
        for child in self.history_list.get_children():
            self.history_list.remove(child)
        
        for history in histories:
            row = self._create_row(history)
            self.history_list.add(row)
        
        self.history_list.show_all()
        
        # Restore selection
        if selected_id:
            self.select_chat(selected_id)
    
    def _create_row(self, history: Dict[str, Any]) -> Gtk.ListBoxRow:
        """Create a row for a chat history entry."""
        row = Gtk.ListBoxRow()
        
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        vbox.set_margin_start(10)
        vbox.set_margin_end(10)
        
        # Get chat ID and title
        chat_id = history.get('chat_id') or history.get('filename', '')
        title = history.get('title') or chat_id
        
        title_label = Gtk.Label(label=title, xalign=0)
        title_label.get_style_context().add_class('title')
        title_label.set_line_wrap(False)
        title_label.set_ellipsize(Pango.EllipsizeMode.END)
        
        # Timestamp
        timestamp = history.get('timestamp', '')
        if isinstance(timestamp, str) and 'T' in timestamp:
            try:
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                timestamp = dt.strftime("%Y-%m-%d %H:%M")
            except:
                pass
        
        time_label = Gtk.Label(label=str(timestamp), xalign=0)
        time_label.get_style_context().add_class('timestamp')
        
        vbox.pack_start(title_label, True, True, 0)
        vbox.pack_start(time_label, True, True, 0)
        
        row.add(vbox)
        row.chat_id = chat_id
        
        return row
    
    def _matches_filter(self, history: Dict[str, Any]) -> bool:
        """Check if history matches current filter."""
        if not self._filter_text:
            return True
        
        title = history.get('title', '')
        
        if self._filter_titles_only:
            return self._text_matches(title)
        
        # Full content search - need to load chat
        if self._text_matches(title):
            return True
        
        # Search content via controller
        if self._controller:
            chat_id = history.get('chat_id') or history.get('filename', '')
            try:
                conv = self._controller.chat_service.load_chat(chat_id)
                if conv:
                    messages = conv.to_list() if hasattr(conv, 'to_list') else conv
                    for msg in messages:
                        content = msg.get('content', '')
                        if isinstance(content, str) and self._text_matches(content):
                            return True
            except:
                pass
        
        return False
    
    def _text_matches(self, text: str) -> bool:
        """Check if text matches filter."""
        if not self._filter_text:
            return True
        
        if self._filter_whole_words:
            try:
                pattern = r"\b" + re.escape(self._filter_text) + r"\b"
                return re.search(pattern, text, flags=re.IGNORECASE) is not None
            except re.error:
                return False
        
        return self._filter_text.lower() in text.lower()
    
    def select_chat(self, chat_id: str) -> None:
        """Select a chat by ID and scroll it into view."""
        self._current_chat_id = chat_id
        children = self.history_list.get_children()
        for row in children:
            row_id = getattr(row, 'chat_id', None)
            if row_id == chat_id:
                self.history_list.select_row(row)
                row.grab_focus()
                return
        # No exact match - try without .json extension
        chat_id_clean = chat_id.replace('.json', '') if chat_id else ''
        for row in children:
            row_id = getattr(row, 'chat_id', '')
            if row_id.replace('.json', '') == chat_id_clean:
                self.history_list.select_row(row)
                row.grab_focus()
                return
        self.history_list.unselect_all()
    
    def _on_new_chat_clicked(self, button) -> None:
        """Handle new chat button click."""
        self._current_chat_id = None
        self.history_list.unselect_all()
        if self._on_new_chat:
            self._on_new_chat()
    
    def _on_row_activated(self, listbox, row) -> None:
        """Handle history row selection."""
        if row and hasattr(row, 'chat_id'):
            self._current_chat_id = row.chat_id
            if self._on_chat_selected:
                self._on_chat_selected(row.chat_id)
    
    def _on_button_press(self, widget, event) -> bool:
        """Handle right-click for context menu."""
        if event.button == 3:  # Right click
            row = self.history_list.get_row_at_y(int(event.y))
            if row and self._on_context_menu:
                self._on_context_menu(row, event)
                return True
        return False
    
    def _on_filter_changed(self, entry) -> None:
        """Handle filter text change with debounce."""
        self._filter_text = entry.get_text()
        
        if self._filter_titles_only:
            if self._filter_timeout_id:
                GLib.source_remove(self._filter_timeout_id)
            self._filter_timeout_id = GLib.timeout_add(150, self._apply_filter)
    
    def _on_filter_icon_pressed(self, entry, icon_pos, event) -> None:
        """Clear filter when clear icon pressed."""
        if icon_pos == Gtk.EntryIconPosition.SECONDARY:
            entry.set_text("")
            self._filter_text = ""
            self.refresh()
    
    def _on_filter_keypress(self, entry, event) -> bool:
        """Handle filter keyboard shortcuts."""
        if event.keyval == Gdk.KEY_Escape:
            entry.set_text("")
            self._filter_text = ""
            self.refresh()
            return True
        if event.keyval == Gdk.KEY_Return:
            self._apply_filter()
            self.history_list.grab_focus()
            return True
        return False
    
    def _on_titles_only_toggled(self, toggle) -> None:
        """Handle titles-only toggle."""
        self._filter_titles_only = toggle.get_active()
        if self._filter_titles_only:
            self._apply_filter()
    
    def _on_whole_words_toggled(self, toggle) -> None:
        """Handle whole-words toggle."""
        self._filter_whole_words = toggle.get_active()
        self._apply_filter()
    
    def _apply_filter(self) -> bool:
        """Apply current filter."""
        self._filter_timeout_id = None
        self.refresh()
        return False
    
    def _on_chat_event(self, event) -> None:
        """Handle chat events - refresh list and select new/saved chats."""
        chat_id = event.data.get('chat_id', '')
        # Select chat on create or save
        should_select = event.type in (EventType.CHAT_CREATED, EventType.CHAT_SAVED) and chat_id
        def update():
            self.refresh()
            if should_select and chat_id:
                # Defer selection to ensure rows are realized
                GLib.idle_add(self.select_chat, chat_id)
        self.schedule_ui_update(update)
    
    def _on_chat_loaded(self, event) -> None:
        """Handle chat loaded - update selection."""
        chat_id = event.data.get('chat_id', '')
        if chat_id:
            self._current_chat_id = chat_id
            self.schedule_ui_update(lambda: self.select_chat(chat_id))
    
    def _build_project_menu(self) -> None:
        """Build the project selector dropdown menu."""
        menu = Gtk.Menu()
        
        # "All Chats" option (default history)
        all_chats_item = Gtk.MenuItem(label="All Chats")
        all_chats_item.connect("activate", self._on_project_selected, "")
        menu.append(all_chats_item)
        
        menu.append(Gtk.SeparatorMenuItem())
        
        # List existing projects
        if self._controller:
            projects_repo = getattr(self._controller, '_projects_repo', None)
            if projects_repo:
                for project in projects_repo.list_all():
                    item = Gtk.MenuItem(label=project.name)
                    item.connect("activate", self._on_project_selected, project.id)
                    menu.append(item)
        
        menu.append(Gtk.SeparatorMenuItem())
        
        # "New Project..." option
        new_project_item = Gtk.MenuItem(label="New Project...")
        new_project_item.connect("activate", self._on_new_project)
        menu.append(new_project_item)
        
        # "Manage Projects..." option
        manage_item = Gtk.MenuItem(label="Manage Projects...")
        manage_item.connect("activate", self._on_manage_projects)
        menu.append(manage_item)
        
        menu.show_all()
        self.project_button.set_popup(menu)
        
        # Update button tooltip with current project
        self._update_project_button_tooltip()
    
    def _update_project_button_tooltip(self) -> None:
        """Update project button tooltip to show current project."""
        if self._controller:
            current = self._controller.get_setting('CURRENT_PROJECT', '')
            if current:
                projects_repo = getattr(self._controller, '_projects_repo', None)
                if projects_repo:
                    project = projects_repo.get(current)
                    if project:
                        self.project_button.set_tooltip_text(f"Project: {project.name}")
                        return
            self.project_button.set_tooltip_text("Project: All Chats")
    
    def _on_project_selected(self, menu_item, project_id: str) -> None:
        """Handle project selection from menu."""
        if self._controller:
            self._controller.switch_project(project_id)
            self._update_project_button_tooltip()
            self.refresh()
    
    def _on_new_project(self, menu_item) -> None:
        """Handle new project creation."""
        if not self._controller:
            return
        
        dialog = Gtk.Dialog(
            title="New Project",
            transient_for=self.widget.get_toplevel(),
            flags=0
        )
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Create", Gtk.ResponseType.OK)
        
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        
        label = Gtk.Label(label="Project Name:")
        label.set_xalign(0)
        box.add(label)
        
        entry = Gtk.Entry()
        entry.set_activates_default(True)
        box.add(entry)
        
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.show_all()
        
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            name = entry.get_text().strip()
            if name:
                projects_repo = getattr(self._controller, '_projects_repo', None)
                if projects_repo:
                    project = projects_repo.create(name)
                    self._controller.switch_project(project.id)
                    self._build_project_menu()
                    self.refresh()
        
        dialog.destroy()
    
    def _on_manage_projects(self, menu_item) -> None:
        """Open project management dialog."""
        if not self._controller:
            return
        
        from dialogs import show_manage_projects_dialog
        show_manage_projects_dialog(
            self.widget.get_toplevel(),
            self._controller,
            on_change=lambda: (self._build_project_menu(), self.refresh())
        )
    
    def refresh_project_menu(self) -> None:
        """Rebuild the project menu (call after project changes)."""
        self._build_project_menu()
