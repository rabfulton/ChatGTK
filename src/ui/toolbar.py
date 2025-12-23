"""
Toolbar UI component.

This component manages the top toolbar with settings and tools buttons.
"""

from typing import Optional, Callable

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from .base import UIComponent
from events import EventBus


class Toolbar(UIComponent):
    """
    Toolbar component with action buttons.
    
    Features:
    - Sidebar toggle button
    - Settings button
    - Tools button
    """
    
    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        on_sidebar_toggle: Optional[Callable[[], None]] = None,
        on_settings: Optional[Callable[[], None]] = None,
        on_tools: Optional[Callable[[], None]] = None,
        sidebar_visible: bool = True,
    ):
        """
        Initialize the toolbar.
        
        Parameters
        ----------
        event_bus : Optional[EventBus]
            Event bus for communication.
        on_sidebar_toggle : Optional[Callable[[], None]]
            Callback for sidebar toggle.
        on_settings : Optional[Callable[[], None]]
            Callback for settings button.
        on_tools : Optional[Callable[[], None]]
            Callback for tools button.
        sidebar_visible : bool
            Initial sidebar visibility state.
        """
        super().__init__(event_bus)
        
        self._on_sidebar_toggle = on_sidebar_toggle
        self._on_settings = on_settings
        self._on_tools = on_tools
        self._sidebar_visible = sidebar_visible
        
        # Build UI
        self.widget = self._build_ui()
    
    def _build_ui(self) -> Gtk.Box:
        """Build the toolbar UI."""
        box = Gtk.Box(spacing=6)
        
        # Sidebar toggle button
        self.sidebar_button = Gtk.Button()
        arrow_type = Gtk.ArrowType.LEFT if self._sidebar_visible else Gtk.ArrowType.RIGHT
        arrow = Gtk.Arrow(arrow_type=arrow_type, shadow_type=Gtk.ShadowType.NONE)
        self.sidebar_button.add(arrow)
        self.sidebar_button.connect("clicked", self._on_sidebar_clicked)
        
        # Style
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"button { background: @theme_bg_color; }")
        self.sidebar_button.get_style_context().add_provider(
            css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        box.pack_start(self.sidebar_button, False, False, 0)
        
        # Placeholder for model selector (added externally)
        self._model_placeholder = Gtk.Box()
        box.pack_start(self._model_placeholder, False, False, 0)
        
        # Placeholder for system prompt selector (added externally)
        self._prompt_placeholder = Gtk.Box()
        box.pack_start(self._prompt_placeholder, False, False, 0)
        
        # Settings button
        self.btn_settings = Gtk.Button(label="Settings")
        self.btn_settings.connect("clicked", self._on_settings_clicked)
        box.pack_start(self.btn_settings, False, False, 0)
        
        # Tools button
        self.btn_tools = Gtk.Button(label="Tools")
        self.btn_tools.connect("clicked", self._on_tools_clicked)
        box.pack_start(self.btn_tools, False, False, 0)
        
        # Spacer to push tool indicators to the right
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        box.pack_start(spacer, True, True, 0)
        
        # Active tools indicator (right edge)
        self.tools_indicator = Gtk.Label()
        self.tools_indicator.set_opacity(0.7)
        css = Gtk.CssProvider()
        css.load_from_data(b"label { font-size: 0.85em; }")
        self.tools_indicator.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        box.pack_end(self.tools_indicator, False, False, 6)
        
        return box
    
    def update_tool_indicators(self, image=False, music=False, web_search=False, read_aloud=False, search=False, text_edit=False):
        """Update the active tools indicator."""
        indicators = []
        if image:
            indicators.append("I")
        if music:
            indicators.append("M")
        if web_search:
            indicators.append("W")
        if read_aloud:
            indicators.append("R")
        if search:
            indicators.append("S")
        if text_edit:
            indicators.append("E")
        
        if indicators:
            self.tools_indicator.set_text(" · ".join(indicators))
            self.tools_indicator.set_tooltip_text(
                "Active tools: " + ", ".join([
                    n for n, a in [
                        ("Image", image),
                        ("Music", music),
                        ("Web Search", web_search),
                        ("Read Aloud", read_aloud),
                        ("Search", search),
                        ("Text Edit", text_edit),
                    ] if a
                ])
            )
        else:
            self.tools_indicator.set_text("")
            self.tools_indicator.set_tooltip_text("")
    
    def set_sidebar_visible(self, visible: bool):
        """Update sidebar toggle button arrow direction."""
        self._sidebar_visible = visible
        # Update arrow
        child = self.sidebar_button.get_child()
        if child:
            self.sidebar_button.remove(child)
        arrow_type = Gtk.ArrowType.LEFT if visible else Gtk.ArrowType.RIGHT
        arrow = Gtk.Arrow(arrow_type=arrow_type, shadow_type=Gtk.ShadowType.NONE)
        self.sidebar_button.add(arrow)
        self.sidebar_button.show_all()
    
    def _on_sidebar_clicked(self, button):
        """Handle sidebar toggle click."""
        if self._on_sidebar_toggle:
            self._on_sidebar_toggle()
    
    def _on_settings_clicked(self, button):
        """Handle settings button click."""
        if self._on_settings:
            self._on_settings()
    
    def _on_tools_clicked(self, button):
        """Handle tools button click."""
        if self._on_tools:
            self._on_tools()
