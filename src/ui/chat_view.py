"""
Chat view UI component.

This component manages the message display area including thinking animation.
"""

from typing import Optional, Callable, List, Any

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib

from .base import UIComponent
from events import EventBus, EventType


def rgb_to_hex(rgb_string: str) -> str:
    """Convert 'rgb(r,g,b)' to '#rrggbb'."""
    if rgb_string.startswith('#'):
        return rgb_string
    if rgb_string.startswith('rgb'):
        import re
        match = re.match(r'rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)', rgb_string)
        if match:
            r, g, b = int(match.group(1)), int(match.group(2)), int(match.group(3))
            return f'#{r:02x}{g:02x}{b:02x}'
    return rgb_string


class ChatView(UIComponent):
    """
    Chat view component for displaying conversation messages.
    
    Features:
    - Scrollable message display
    - Delegates rendering to MessageRenderer
    - Animated thinking indicator with cancel button
    - Event-driven updates
    """
    
    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        window: Any = None,
        ai_name: str = "Assistant",
        ai_color: str = "#4a90d9",
        on_cancel: Optional[Callable[[], None]] = None,
    ):
        """
        Initialize the chat view.
        
        Parameters
        ----------
        event_bus : Optional[EventBus]
            Event bus for communication.
        window : Any
            Parent window for dialogs and URI handling.
        ai_name : str
            Name to display in thinking animation.
        ai_color : str
            Color for AI messages and thinking animation.
        on_cancel : Optional[Callable[[], None]]
            Callback when cancel button is clicked.
        """
        super().__init__(event_bus)
        
        self._window = window
        self._message_renderer = None
        self._ai_name = ai_name
        self._ai_color = ai_color
        self._on_cancel = on_cancel
        
        # Thinking animation state
        self._thinking_container = None
        self._thinking_timer = None
        self._thinking_dots = 0
        self._loader_animation_state = 0
        
        self.message_widgets: List[Any] = []
        
        # Build UI
        self.widget, self.conversation_box = self._build_ui()
        
        # Subscribe to events
        self.subscribe(EventType.THINKING_STARTED, self._on_thinking_started)
        self.subscribe(EventType.THINKING_STOPPED, self._on_thinking_stopped)
    
    def _build_ui(self):
        """Build the chat view UI."""
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        
        conversation_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        conversation_box.set_margin_start(0)
        conversation_box.set_margin_end(5)
        conversation_box.set_margin_top(0)
        conversation_box.set_margin_bottom(5)
        scrolled.add(conversation_box)
        
        return scrolled, conversation_box
    
    def set_message_renderer(self, renderer):
        """Set the message renderer."""
        self._message_renderer = renderer
    
    def set_ai_style(self, ai_name: str, ai_color: str):
        """Update AI name and color for thinking animation."""
        self._ai_name = ai_name
        self._ai_color = ai_color
    
    def append_message(self, sender: str, text: str, index: int):
        """Append a message to the view."""
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
        """Show animated thinking indicator with loader and cancel button."""
        # Remove existing
        if self._thinking_container:
            self._thinking_container.destroy()
            self._thinking_container = None
        
        hex_color = rgb_to_hex(self._ai_color)
        
        # Create container
        self._thinking_container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        
        css = """
            box {
                background-color: @theme_base_color;
                padding: 12px;
                border-radius: 12px;
            }
        """
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(css.encode())
        self._thinking_container.get_style_context().add_provider(
            css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        
        # Loader dot
        loader_box = Gtk.Box()
        loader_box.set_size_request(16, 16)
        loader_box.set_valign(Gtk.Align.CENTER)
        
        self._loader_dot = Gtk.Box()
        self._loader_dot.set_size_request(16, 16)
        
        loader_css = f"""
            box {{
                border-radius: 50%;
                background-color: {hex_color};
                min-width: 16px;
                min-height: 16px;
            }}
        """
        loader_css_provider = Gtk.CssProvider()
        loader_css_provider.load_from_data(loader_css.encode())
        self._loader_dot.get_style_context().add_provider(
            loader_css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        
        loader_box.pack_start(self._loader_dot, False, False, 0)
        self._thinking_container.pack_start(loader_box, False, False, 0)
        
        # Label
        self._thinking_label = Gtk.Label()
        self._thinking_label.set_markup(f"<span color='{hex_color}'>{self._ai_name} is thinking</span>")
        self._thinking_label.set_xalign(0)
        self._thinking_container.pack_start(self._thinking_label, True, True, 0)
        
        # Cancel button
        cancel_button = Gtk.Button()
        cancel_button.set_relief(Gtk.ReliefStyle.NONE)
        cancel_button.set_tooltip_text("Cancel request")
        
        cancel_css = """
            button {
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 0;
                min-height: 0;
                color: @theme_fg_color;
            }
            button:hover {
                background-color: alpha(@theme_fg_color, 0.1);
            }
        """
        cancel_css_provider = Gtk.CssProvider()
        cancel_css_provider.load_from_data(cancel_css.encode())
        cancel_button.get_style_context().add_provider(
            cancel_css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        
        cancel_label = Gtk.Label()
        cancel_label.set_markup("<span size='large' weight='bold'>×</span>")
        cancel_button.add(cancel_label)
        cancel_button.connect("clicked", self._on_cancel_clicked)
        self._thinking_container.pack_start(cancel_button, False, False, 0)
        
        self.conversation_box.pack_start(self._thinking_container, False, False, 0)
        self.conversation_box.show_all()
        self.scroll_to_bottom()
        
        # Start animation
        self._thinking_dots = 0
        self._loader_animation_state = 0
        self._loader_opacity = [1.0, 0.4, 1.0]
        
        def update_animation():
            if not self._thinking_container:
                return False
            
            opacity = self._loader_opacity[self._loader_animation_state]
            if self._loader_dot:
                self._loader_dot.set_opacity(opacity)
            self._loader_animation_state = (self._loader_animation_state + 1) % 3
            
            if self._thinking_label:
                self._thinking_dots = (self._thinking_dots + 1) % 4
                dots = "." * self._thinking_dots
                self._thinking_label.set_markup(
                    f"<span color='{hex_color}'>{self._ai_name} is thinking{dots}</span>"
                )
            return True
        
        self._thinking_timer = GLib.timeout_add(667, update_animation)
    
    def _hide_thinking_impl(self):
        """Remove thinking animation."""
        if self._thinking_timer:
            try:
                GLib.source_remove(self._thinking_timer)
            except:
                pass
            self._thinking_timer = None
        
        if self._thinking_container:
            self._thinking_container.destroy()
            self._thinking_container = None
        
        self._thinking_label = None
        self._loader_dot = None
    
    def _on_cancel_clicked(self, button):
        """Handle cancel button click."""
        self._hide_thinking_impl()
        if self._on_cancel:
            self._on_cancel()
    
    def _on_thinking_started(self, event):
        """Handle THINKING_STARTED event."""
        self.show_thinking()
    
    def _on_thinking_stopped(self, event):
        """Handle THINKING_STOPPED event."""
        self.hide_thinking()
