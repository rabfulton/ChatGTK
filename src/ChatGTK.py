#!/usr/bin/env python3
import os
os.environ['AUDIODEV'] = 'pulse'  # Force use of PulseAudio
import gi
import json
import re
import threading
import sounddevice as sd  # For recording audio
import soundfile as sf    # For saving audio files
import numpy as np       # For audio processing
import tempfile         # For temporary files
from pathlib import Path # For path handling
import subprocess
import mimetypes
import base64
import time
import getpass
from latex_utils import (
    tex_to_png,
    process_tex_markup,
    insert_tex_image,
    cleanup_temp_files,
    is_latex_installed,
    export_chat_to_pdf,
)
from utils import (
    generate_chat_name,
    get_chat_metadata,
    get_chat_title,
    get_chat_dir,
    parse_color_to_rgba,
    rgb_to_hex,
    insert_resized_image,
    apply_settings,
    get_object_settings,
    save_object_settings,
    convert_settings_for_save,
    load_api_keys,
    load_custom_models,
    save_custom_models,
    get_model_display_name,
)
from ai_providers import get_ai_provider, OpenAIProvider, OpenAIWebSocketProvider
from model_cards import get_card
from markup_utils import (
    format_response,
    process_inline_markup,
    escape_for_pango_markup,
    process_text_formatting
)
from gi.repository import Gdk
from datetime import datetime
from config import BASE_DIR, PARENT_DIR, SETTINGS_CONFIG
from tools import (
    ToolManager,
    is_chat_completion_model,
    append_tool_guidance,
)
from dialogs import SettingsDialog, ToolsDialog, PromptEditorDialog
from conversation import (
    create_system_message,
    create_user_message,
    create_assistant_message,
    get_first_user_content,
)
from controller import ChatController
from events import EventType, Event
from message_renderer import MessageRenderer, RenderSettings, RenderCallbacks, create_source_view

gi.require_version("Gtk", "3.0")
# For syntax highlighting:
gi.require_version("GtkSource", "4")

from gi.repository import Gtk, GLib, Pango, GtkSource, Gdk

# Note: System tray APIs are effectively deprecated across GTK3, but
# Gtk.StatusIcon remains the most practical option for cross-desktop
# “minimize to tray” behavior with a left-click activate action.

class OpenAIGTKClient(Gtk.Window):
    def __init__(self):
        super().__init__(title="ChatGTK Client")

        # Set window icon
        try:
            # Use BASE_DIR from config for icon path
            icon_path = Path(BASE_DIR) / "icon.png"
            self.set_icon_from_file(str(icon_path))
        except Exception as e:
            print(f"Could not load application icon: {e}")

        # Initialize the controller FIRST - it manages state and business logic
        # Must be created before apply_settings since property setters delegate to controller
        self.controller = ChatController()
        self.controller.initialize_providers_from_env()

        # Subscribe to events for reactive UI updates
        self._init_event_subscriptions()

        # Load and apply settings (for UI settings like window_width, font_size, etc.)
        # Note: settings like system_message will be routed to controller via properties
        # Settings are loaded via controller's settings_manager
        loaded = self.controller.settings_manager.get_all()
        apply_settings(self, loaded)
        
        # Initialize window
        self.set_default_size(self.window_width, self.window_height)

        # Tray icon / indicator (created lazily when needed)
        self.tray_icon = None
        self.tray_menu = None
        # Flag to prevent minimize events during restoration
        self._restoring_from_tray = False

        # UI-only state (not delegated to controller)
        self.message_widgets = []

        # Remember the current geometry if not maximized
        self.current_geometry = (self.window_width, self.window_height)

        # Create main container
        main_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.add(main_hbox)

        # Create paned container
        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        
        main_hbox.pack_start(self.paned, True, True, 0)
        
        # Create sidebar using UI component
        from ui import HistorySidebar
        self._history_sidebar = HistorySidebar(
            event_bus=self.controller.event_bus,
            controller=self.controller,
            on_chat_selected=self.load_chat_by_filename,
            on_new_chat=lambda: self.on_new_chat(None),
            on_context_menu=self._on_sidebar_context_menu,
            width=int(getattr(self, 'sidebar_width', 200)),
        )
        self.sidebar = self._history_sidebar.widget
        # Expose history_list for backward compatibility
        self.history_list = self._history_sidebar.history_list
        # Expose filter state for backward compatibility
        self.history_filter_text = ""
        self.history_filter_titles_only = True
        self.history_filter_whole_words = False
        
        # Pack sidebar into left pane
        self.paned.pack1(self.sidebar, False, False)

        # Create main content area
        vbox_main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        vbox_main.set_margin_top(10)
        vbox_main.set_margin_bottom(10)
        vbox_main.set_margin_start(10)
        vbox_main.set_margin_end(10)
        
        # Pack main content into right pane
        self.paned.pack2(vbox_main, True, False)

        # Track sidebar width in memory
        self.current_sidebar_width = int(getattr(self, 'sidebar_width', 200))
        self.paned.set_position(self.current_sidebar_width)

        # Update memory value without saving to file
        def on_paned_position_changed(paned, param):
            if not self.is_maximized():
                self.current_sidebar_width = paned.get_position()
                self.sidebar_width = self.current_sidebar_width

        self.paned.connect('notify::position', on_paned_position_changed)

        # Top row: API Key, Model, Settings
        hbox_top = Gtk.Box(spacing=6)

        # Add sidebar toggle button to top bar
        self.sidebar_button = Gtk.Button()
        # Set arrow direction based on initial sidebar visibility state
        # LEFT arrow = sidebar is visible (clicking will hide it)
        # RIGHT arrow = sidebar is hidden (clicking will show it)
        initial_arrow_type = Gtk.ArrowType.LEFT if getattr(self, 'sidebar_visible', True) else Gtk.ArrowType.RIGHT
        arrow = Gtk.Arrow(arrow_type=initial_arrow_type, shadow_type=Gtk.ShadowType.NONE)
        self.sidebar_button.add(arrow)
        self.sidebar_button.connect("clicked", self.on_sidebar_toggle)
        # Style to match other buttons
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"button { background: @theme_bg_color; }")
        self.sidebar_button.get_style_context().add_provider(
            css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        hbox_top.pack_start(self.sidebar_button, False, False, 0)

        # Model selector component
        from ui import ModelSelector
        self._model_selector = ModelSelector(
            event_bus=self.controller.event_bus,
            on_model_changed=self._handle_model_changed,
        )
        hbox_top.pack_start(self._model_selector.widget, False, False, 0)
        # Expose combo_model for backward compatibility
        self.combo_model = self._model_selector.widget
        self._display_to_model_id = self._model_selector._display_to_model_id
        self._model_id_to_display = self._model_selector._model_id_to_display
        
        # Provider initialization is now handled by self.controller.initialize_providers_from_env()
        # called above. Here we just fetch models if we have any providers.
        if self.providers or self.custom_models:
            self.fetch_models_async()
        else:
            default_models = self.controller.get_default_models_for_provider('openai')
            self.model_provider_map = {model: 'openai' for model in default_models}
            self.controller.model_provider_map = self.model_provider_map
            self.update_model_list(default_models, self.default_model)

        # System prompt selector (only visible when multiple prompts exist)
        self.combo_system_prompt = Gtk.ComboBoxText()
        # Connect signal first, then refresh (refresh blocks/unblocks the handler)
        self.combo_system_prompt.connect("changed", self.on_system_prompt_changed)
        self._refresh_system_prompt_combo()
        hbox_top.pack_start(self.combo_system_prompt, False, False, 0)

        # Settings button
        btn_settings = Gtk.Button(label="Settings")
        btn_settings.connect("clicked", self.on_open_settings)
        hbox_top.pack_start(btn_settings, False, False, 0)

        # Tools button (for configuring model tools such as images and music)
        btn_tools = Gtk.Button(label="Tools")
        btn_tools.connect("clicked", self.on_open_tools)
        hbox_top.pack_start(btn_tools, False, False, 0)

        vbox_main.pack_start(hbox_top, False, False, 0)

        # Chat view component for message display
        from ui import ChatView
        self._chat_view = ChatView(
            event_bus=self.controller.event_bus,
            window=self,
        )
        vbox_main.pack_start(self._chat_view.widget, True, True, 0)
        # Expose conversation_box and message_widgets for backward compatibility
        self.conversation_box = self._chat_view.conversation_box
        self.message_widgets = self._chat_view.message_widgets

        # Initialize the message renderer for displaying chat messages
        self._init_message_renderer()

        # Input panel component
        from ui import InputPanel
        self._input_panel = InputPanel(
            event_bus=self.controller.event_bus,
            on_submit=lambda text: self.on_submit(None),
            on_voice_input=lambda: self.on_voice_input(None),
            on_attach_file=lambda: self.on_attach_file(None),
            on_open_prompt_editor=lambda: self.on_open_prompt_editor(None),
        )
        vbox_main.pack_start(self._input_panel.widget, False, False, 0)
        
        # Expose widgets for backward compatibility
        self.entry_question = self._input_panel.entry
        self.btn_send = self._input_panel.btn_send
        self.btn_voice = self._input_panel.btn_voice
        self.btn_attach = self._input_panel.btn_attach
        
        # State (also tracked in component)
        self.recording = False
        self.attached_file_path = None
        self.pending_edit_image = None
        self.pending_edit_message_index = None
        self._edit_buttons = []

        # Check LaTeX installation
        if not is_latex_installed():
            print("Warning: LaTeX installation not found. Formula rendering will be disabled.")

        # Show all widgets first
        self.show_all()
        
        # Then force sidebar visibility state
        if not self.sidebar_visible:
            self.sidebar.hide()
            self.sidebar.set_visible(False)  # More forceful hide
            self.sidebar.set_no_show_all(True)  # Prevent show_all from showing it
        else:
            self.sidebar.set_no_show_all(False)
            self.sidebar.set_visible(True)
        
        # Load chat histories
        self.refresh_history_list()
        self.apply_sidebar_styles()
        
        # Load the last active conversation if it exists
        if hasattr(self, 'last_active_chat') and self.last_active_chat:
            # Use idle_add to ensure UI is fully initialized before loading
            def load_last_active():
                try:
                    # Check if the chat file still exists
                    chat_filename = self.last_active_chat
                    if not chat_filename.endswith('.json'):
                        chat_filename = f"{chat_filename}.json"
                    
                    # Verify the file exists before trying to load
                    from config import HISTORY_DIR
                    chat_path = os.path.join(HISTORY_DIR, chat_filename)
                    if os.path.exists(chat_path):
                        self.load_chat_by_filename(chat_filename, save_current=False)
                except Exception as e:
                    print(f"Error loading last active chat: {e}")
                return False  # Don't repeat
            
            GLib.idle_add(load_last_active)

        # Connect window event handlers
        self.connect("configure-event", self.on_configure_event)
        self.connect("delete-event", self.on_delete_event)
        self.connect("window-state-event", self.on_window_state_event)
        self.connect("destroy", self.on_destroy)
        self.connect("key-press-event", self._on_global_key_press)

    def _build_tray_menu(self):
        """
        Build (or rebuild) the tray context menu used by both AppIndicator and
        Gtk.StatusIcon backends.
        """
        menu = Gtk.Menu()

        item_show = Gtk.MenuItem(label="Show ChatGTK")
        item_show.connect("activate", lambda *_: self.restore_from_tray())
        menu.append(item_show)

        item_quit = Gtk.MenuItem(label="Quit")
        item_quit.connect("activate", self.on_tray_quit)
        menu.append(item_quit)

        menu.show_all()
        self.tray_menu = menu
        return menu

    def _ensure_tray_icon(self):
        """
        Lazily create the system tray icon if minimize-to-tray is enabled.

        Uses Gtk.StatusIcon, which is deprecated at the toolkit level but still
        the most practical way to provide a tray icon with a working left-click
        activate action in GTK3 apps across many Linux desktops.
        """
        if self.tray_icon is not None:
            return

        try:
            icon_path = Path(BASE_DIR) / "icon.png"
            icon_name_or_path = str(icon_path) if icon_path.exists() else "applications-system"

            status_icon = Gtk.StatusIcon()
            if icon_path.exists():
                status_icon.set_from_file(icon_name_or_path)
            else:
                status_icon.set_from_icon_name(icon_name_or_path)

            status_icon.set_title("ChatGTK")
            status_icon.set_tooltip_text("ChatGTK")
            status_icon.connect("activate", self.on_tray_activate)
            status_icon.connect("popup-menu", self.on_tray_popup_menu)
            self.tray_icon = status_icon
        except Exception as e:
            print(f"Could not create system tray icon: {e}")
            self.tray_icon = None

    def on_delete_event(self, widget, event):
        """
        Intercept window-close events. When minimize-to-tray is enabled,
        hide the window and keep the app running in the tray.
        """
        if bool(getattr(self, "minimize_to_tray_enabled", False)):
            self._ensure_tray_icon()
            if self.tray_icon is not None:
                # Hide the window and remove it from the taskbar
                self.hide()
                self.set_skip_taskbar_hint(True)
                return True  # prevent destroy / main_quit
        return False  # default behavior (destroy)

    def on_window_state_event(self, widget, event):
        """
        When minimize-to-tray is enabled, intercept minimize and hide the window
        immediately to prevent it from appearing in the taskbar.
        """
        if not bool(getattr(self, "minimize_to_tray_enabled", False)):
            return False

        # If we're currently restoring from tray, ignore minimize events
        if self._restoring_from_tray:
            return True

        changed = event.changed_mask
        new_state = event.new_window_state

        if changed & Gdk.WindowState.ICONIFIED and (new_state & Gdk.WindowState.ICONIFIED):
            self._ensure_tray_icon()
            if self.tray_icon is not None:
                # Immediately hide and skip taskbar - don't let WM iconify first
                self.hide()
                self.set_skip_taskbar_hint(True)
                # Prevent the window manager from processing the iconify event
                return True

        return False

    def on_tray_activate(self, icon):
        """
        Primary tray icon activation (usually left-click): restore window.
        """
        self.restore_from_tray()

    def on_tray_popup_menu(self, icon, button, time):
        """
        Right-click on tray icon: show a small menu with Show/Hide and Quit.
        """
        menu = self.tray_menu or self._build_tray_menu()
        menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, time)

    def restore_from_tray(self):
        """
        Common logic to restore the window from the system tray.
        """
        # Set flag to prevent minimize events during restoration
        self._restoring_from_tray = True

        try:
            # Remove taskbar skip hint so window appears in taskbar
            self.set_skip_taskbar_hint(False)
            # Show the window and bring it to front
            self.show_all()
            self.present()
        finally:
            # Clear the flag after a short delay to allow the window to stabilize
            def clear_flag():
                self._restoring_from_tray = False
                return False
            GLib.timeout_add(500, clear_flag)  # 500ms delay

    def on_tray_quit(self, *args):
        """
        Quit the application from the tray icon menu.
        """
        if self.tray_icon is not None and hasattr(self.tray_icon, "set_visible"):
            try:
                self.tray_icon.set_visible(False)
            except Exception:
                pass
        self.destroy()

    def on_destroy(self, widget):
        """Save settings and cleanup before closing."""
        if hasattr(self, 'ws_provider'):
            self.ws_provider.stop_streaming()
            
        # Save settings via controller's settings_manager
        to_save = get_object_settings(self)
        to_save['WINDOW_WIDTH'] = self.current_geometry[0]
        to_save['WINDOW_HEIGHT'] = self.current_geometry[1]
        to_save['SIDEBAR_WIDTH'] = self.current_sidebar_width
        for key, value in convert_settings_for_save(to_save).items():
            self.controller.settings_manager.set(key, value)
        
        # Hide tray icon on exit (only for StatusIcon backend)
        if self.tray_icon is not None and hasattr(self.tray_icon, "set_visible"):
            try:
                self.tray_icon.set_visible(False)
            except Exception:
                pass
        cleanup_temp_files()
        Gtk.main_quit()

    def on_configure_event(self, widget, event):
        # Called whenever window is resized or moved
        if not self.is_maximized():
            width, height = self.get_size()
            self.current_geometry = (width, height)
        return False

    def _get_shortcuts(self) -> dict:
        """Get keyboard shortcuts from settings, merged with defaults."""
        from config import DEFAULT_SHORTCUTS
        shortcuts_json = getattr(self, 'keyboard_shortcuts', '')
        try:
            shortcuts = json.loads(shortcuts_json) if shortcuts_json else {}
        except json.JSONDecodeError:
            shortcuts = {}
        # Merge with defaults
        for action, default_key in DEFAULT_SHORTCUTS.items():
            if action not in shortcuts:
                shortcuts[action] = default_key
        return shortcuts

    def _on_global_key_press(self, widget, event):
        """Handle global keyboard shortcuts."""
        shortcuts = self._get_shortcuts()
        
        # Build current key combo string
        parts = []
        if event.state & Gdk.ModifierType.CONTROL_MASK:
            parts.append('<Ctrl>')
        if event.state & Gdk.ModifierType.SHIFT_MASK:
            parts.append('<Shift>')
        if event.state & Gdk.ModifierType.MOD1_MASK:
            parts.append('<Alt>')
        
        key_name = Gdk.keyval_name(event.keyval)
        if key_name:
            parts.append(key_name)
        current_combo = ''.join(parts)
        
        # Find matching action
        for action, shortcut in shortcuts.items():
            if shortcut and shortcut.lower() == current_combo.lower():
                return self._execute_shortcut_action(action)
        
        return False

    def _execute_shortcut_action(self, action: str) -> bool:
        """Execute a shortcut action. Returns True if handled."""
        if action == 'new_chat':
            self.on_new_chat(None)
            return True
        elif action == 'voice_input':
            self.on_voice_input(None)
            return True
        elif action == 'prompt_editor':
            self._open_prompt_editor()
            return True
        elif action == 'focus_input':
            self.entry_question.grab_focus()
            return True
        elif action == 'submit':
            self.on_submit(None)
            return True
        elif action.startswith('model_'):
            # Get configured model for this slot
            model_shortcuts_json = getattr(self, 'model_shortcuts', '{}')
            try:
                model_shortcuts = json.loads(model_shortcuts_json) if model_shortcuts_json else {}
            except json.JSONDecodeError:
                model_shortcuts = {}
            
            target_model = model_shortcuts.get(action, '')
            if target_model:
                # Find and select the model in the combo
                model_store = self.combo_model.get_model()
                for i, row in enumerate(model_store):
                    # Check both display name and model ID
                    if row[0] == target_model or (hasattr(self, '_display_to_model_id') and 
                        self._display_to_model_id.get(row[0]) == target_model):
                        self.combo_model.set_active(i)
                        return True
        return False

    def _open_prompt_editor(self):
        """Open the prompt editor dialog."""
        current_text = self.entry_question.get_text()
        dialog = PromptEditorDialog(self, current_text, on_voice_input=self.on_voice_input)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            self.entry_question.set_text(dialog.get_text())
        dialog.destroy()

    def _get_model_id_from_combo(self):
        """Get the actual model_id from the combo box, mapping display text back to model_id."""
        display_text = self.combo_model.get_active_text()
        if not display_text:
            return None
        
        # Check if we have the mapping
        if hasattr(self, '_display_to_model_id') and display_text in self._display_to_model_id:
            return self._display_to_model_id[display_text]
        
        # If no mapping found, assume it's the model_id itself
        return display_text

    def _get_temperature_for_model(self, model_id: str):
        """
        Look up the configured temperature for a model.
        
        Returns a float if the model card has temperature enabled, otherwise None
        so the API call omits the temperature parameter.
        """
        if not model_id:
            return None
        card = get_card(model_id, self.custom_models)
        if card and getattr(card, "temperature", None) is not None:
            return float(card.temperature)
        return None

    def update_model_list(self, models, current_model=None):
        """Update the model combo box with fetched models."""
        if not models:
            models = self._default_models_for_provider('openai')
            self.model_provider_map = {model: 'openai' for model in models}
        
        # Build display names mapping
        display_names = {}
        for model_id in models:
            display_name = get_model_display_name(model_id, self.custom_models)
            if display_name:
                display_names[model_id] = display_name
        
        # Determine active model
        active_model = current_model
        if not active_model or active_model not in models:
            active_model = self.default_model if self.default_model in models else models[0] if models else None
        
        # Use component to set models
        if hasattr(self, '_model_selector'):
            self._model_selector.set_models(models, display_names, active_model)
            # Sync mappings
            self._display_to_model_id = self._model_selector._display_to_model_id
            self._model_id_to_display = self._model_selector._model_id_to_display
        
        return False

    def _handle_model_changed(self, model_id: str, display_name: str):
        """Handle model selection from ModelSelector component."""
        # Emit MODEL_CHANGED event
        self.controller.event_bus.publish(Event(
            type=EventType.MODEL_CHANGED,
            data={'model_id': model_id, 'display_name': display_name},
            source='ui'
        ))
        # Sync mappings from component
        if hasattr(self, '_model_selector'):
            self._display_to_model_id = self._model_selector._display_to_model_id
            self._model_id_to_display = self._model_selector._model_id_to_display

    def on_model_changed(self, combo):
        """Handle model selection changes - legacy, now handled by component."""
        pass  # Component handles this now

    def _init_message_renderer(self):
        """Initialize the MessageRenderer with current settings and callbacks."""
        settings = RenderSettings(
            font_size=self.font_size,
            font_family=self.font_family,
            ai_color=self.ai_color,
            user_color=self.user_color,
            ai_name=self.ai_name,
            source_theme=self.source_theme,
            latex_color=self.latex_color,
            latex_dpi=getattr(self, 'latex_dpi', 200),
        )
        callbacks = RenderCallbacks(
            on_context_menu=self.create_message_context_menu,
            on_delete=self.on_delete_message,
            create_speech_button=self.create_speech_button,
            create_edit_button=self.create_edit_button,
        )
        self.message_renderer = MessageRenderer(
            settings=settings,
            callbacks=callbacks,
            conversation_box=self.conversation_box,
            message_widgets=self.message_widgets,
            window=self,
            current_chat_id=self.current_chat_id,
        )
        # Connect renderer to chat view component
        if hasattr(self, '_chat_view'):
            self._chat_view.set_message_renderer(self.message_renderer)

    def _update_message_renderer_settings(self):
        """Update renderer settings after settings change."""
        if hasattr(self, 'message_renderer'):
            self.message_renderer.settings = RenderSettings(
                font_size=self.font_size,
                font_family=self.font_family,
                ai_color=self.ai_color,
                user_color=self.user_color,
                ai_name=self.ai_name,
                source_theme=self.source_theme,
                latex_color=self.latex_color,
                latex_dpi=getattr(self, 'latex_dpi', 200),
            )

    # -----------------------------------------------------------------------
    # System prompts management - delegated to controller
    # -----------------------------------------------------------------------

    @property
    def current_chat_id(self):
        """Get the current chat ID from controller."""
        return self.controller.current_chat_id

    @current_chat_id.setter
    def current_chat_id(self, value):
        """Set the current chat ID on controller."""
        self.controller.current_chat_id = value

    @property
    def system_message(self):
        """Get the system message from controller."""
        return self.controller.system_message

    @system_message.setter
    def system_message(self, value):
        """Set the system message on controller."""
        self.controller.system_message = value

    @property
    def active_system_prompt_id(self):
        """Get the active system prompt ID from controller."""
        return self.controller.active_system_prompt_id

    @active_system_prompt_id.setter
    def active_system_prompt_id(self, value):
        """Set the active system prompt ID on controller."""
        self.controller.active_system_prompt_id = value

    @property
    def conversation_history(self):
        """Get the conversation history from controller."""
        return self.controller.conversation_history

    @conversation_history.setter
    def conversation_history(self, value):
        """Set the conversation history on controller."""
        self.controller.conversation_history = value

    @property
    def providers(self):
        """Get providers from controller."""
        return self.controller.providers

    @property
    def model_provider_map(self):
        """Get model_provider_map from controller."""
        return self.controller.model_provider_map

    @model_provider_map.setter
    def model_provider_map(self, value):
        """Set model_provider_map on controller."""
        self.controller.model_provider_map = value

    @property
    def api_keys(self):
        """Get api_keys from controller."""
        return self.controller.api_keys

    @property
    def custom_models(self):
        """Get custom_models from controller."""
        return self.controller.custom_models

    @custom_models.setter
    def custom_models(self, value):
        """Set custom_models on controller."""
        self.controller.custom_models = value

    @property
    def custom_providers(self):
        """Get custom_providers from controller."""
        return self.controller.custom_providers

    @custom_providers.setter
    def custom_providers(self, value):
        """Set custom_providers on controller."""
        self.controller.custom_providers = value

    @property
    def tool_manager(self):
        """Get tool_manager from controller."""
        return self.controller.tool_manager

    @tool_manager.setter
    def tool_manager(self, value):
        """Set tool_manager on controller."""
        self.controller.tool_manager = value

    @property
    def system_prompts(self):
        """Get system_prompts from controller."""
        return self.controller.system_prompts

    @system_prompts.setter
    def system_prompts(self, value):
        """Set system_prompts on controller."""
        self.controller.system_prompts = value

    def _get_system_prompt_by_id(self, prompt_id):
        """Delegate to controller."""
        return self.controller.get_system_prompt_by_id(prompt_id)

    def _init_system_prompts_from_settings(self):
        """
        Re-initialize system prompts from updated settings.
        
        This delegates to the controller to parse the settings.
        Properties handle the delegation automatically.
        """
        # Ensure controller has the latest settings
        self.controller.system_prompts_json = getattr(self, "system_prompts_json", "")
        self.controller.active_system_prompt_id = getattr(self, "active_system_prompt_id", "")
        
        # Let controller parse/init
        self.controller.init_system_prompts()

    # -----------------------------------------------------------------------
    # Event subscriptions for reactive UI updates
    # -----------------------------------------------------------------------

    def _init_event_subscriptions(self):
        """Subscribe to events from controller/services for reactive UI updates."""
        bus = self.controller.event_bus
        
        # Chat events
        bus.subscribe(EventType.CHAT_CREATED, self._on_chat_created_event)
        bus.subscribe(EventType.CHAT_LOADED, self._on_chat_loaded_event)
        bus.subscribe(EventType.CHAT_SAVED, self._on_chat_saved_event)
        bus.subscribe(EventType.CHAT_DELETED, self._on_chat_deleted_event)
        
        # Settings events
        bus.subscribe(EventType.SETTINGS_CHANGED, self._on_settings_changed_event)
        
        # Error events
        bus.subscribe(EventType.ERROR_OCCURRED, self._on_error_event)
        
        # Thinking/processing state events
        bus.subscribe(EventType.THINKING_STARTED, self._on_thinking_started_event)
        bus.subscribe(EventType.THINKING_STOPPED, self._on_thinking_stopped_event)
        
        # Message events
        bus.subscribe(EventType.MESSAGE_SENT, self._on_message_sent_event)
        bus.subscribe(EventType.MESSAGE_RECEIVED, self._on_message_received_event)
        
        # Image events
        bus.subscribe(EventType.IMAGE_GENERATED, self._on_image_generated_event)
        
        # Audio events
        bus.subscribe(EventType.RECORDING_STARTED, self._on_recording_started_event)
        bus.subscribe(EventType.RECORDING_STOPPED, self._on_recording_stopped_event)
        bus.subscribe(EventType.TRANSCRIPTION_COMPLETE, self._on_transcription_complete_event)
        bus.subscribe(EventType.PLAYBACK_STARTED, self._on_playback_started_event)
        bus.subscribe(EventType.PLAYBACK_STOPPED, self._on_playback_stopped_event)
        bus.subscribe(EventType.TTS_COMPLETE, self._on_tts_complete_event)
        
        # Model events
        bus.subscribe(EventType.MODEL_CHANGED, self._on_model_changed_event)
        bus.subscribe(EventType.MODELS_FETCHED, self._on_models_fetched_event)
        
        # Tool events
        bus.subscribe(EventType.TOOL_EXECUTED, self._on_tool_executed_event)
        bus.subscribe(EventType.TOOL_RESULT, self._on_tool_result_event)

    def _on_chat_loaded_event(self, event):
        """Handle CHAT_LOADED event - refresh UI."""
        GLib.idle_add(self.refresh_history_list)

    def _on_chat_saved_event(self, event):
        """Handle CHAT_SAVED event - refresh history list."""
        GLib.idle_add(self.refresh_history_list)

    def _on_chat_deleted_event(self, event):
        """Handle CHAT_DELETED event - refresh history list."""
        GLib.idle_add(self.refresh_history_list)

    def _on_settings_changed_event(self, event):
        """Handle SETTINGS_CHANGED event - update UI if needed."""
        key = event.data.get('key', '')
        value = event.data.get('value')
        
        # Update local attribute for settings that affect UI
        if key:
            attr = key.lower()
            if hasattr(self, attr):
                setattr(self, attr, value)
        
        # Handle specific settings that need UI updates
        if key == 'FONT_SIZE':
            GLib.idle_add(self._update_message_renderer_settings)
        elif key == 'LATEX_DPI':
            GLib.idle_add(self._update_message_renderer_settings)

    def _on_error_event(self, event):
        """Handle ERROR_OCCURRED event - show error to user."""
        error = event.data.get('error', 'Unknown error')
        context = event.data.get('context', '')
        message = f"{context}: {error}" if context else error
        GLib.idle_add(self.display_error, message)

    def _on_thinking_started_event(self, event):
        """Handle THINKING_STARTED event - show thinking animation."""
        GLib.idle_add(self.show_thinking_animation)

    def _on_thinking_stopped_event(self, event):
        """Handle THINKING_STOPPED event - hide thinking animation."""
        GLib.idle_add(self.hide_thinking_animation)

    def emit_thinking_started(self, model: str = None):
        """Emit THINKING_STARTED event and show animation."""
        self.controller.event_bus.publish(Event(
            type=EventType.THINKING_STARTED,
            data={'model': model},
            source='ui'
        ))

    def emit_thinking_stopped(self):
        """Emit THINKING_STOPPED event and hide animation."""
        self.controller.event_bus.publish(Event(
            type=EventType.THINKING_STOPPED,
            data={},
            source='ui'
        ))

    def _on_message_sent_event(self, event):
        """Handle MESSAGE_SENT event - display user message in UI."""
        content = event.data.get('content', '')
        index = event.data.get('index', 0)
        # Only handle if source is controller (avoid double-display)
        if event.source == 'controller':
            formatted = format_response(content)
            GLib.idle_add(lambda: self.append_message('user', formatted, index))

    def _on_message_received_event(self, event):
        """Handle MESSAGE_RECEIVED event - display assistant message in UI."""
        content = event.data.get('content', '')
        index = event.data.get('index', 0)
        # Only handle if source is controller (avoid double-display)
        if event.source == 'controller':
            formatted = format_response(content)
            GLib.idle_add(lambda: self.append_message('ai', formatted, index))

    def _on_image_generated_event(self, event):
        """Handle IMAGE_GENERATED event - log for debugging."""
        image_path = event.data.get('image_path', '')
        prompt = event.data.get('prompt', '')[:50]
        print(f"[Event] Image generated: {image_path} for prompt: {prompt}...")

    def _on_chat_created_event(self, event):
        """Handle CHAT_CREATED event - refresh history list."""
        GLib.idle_add(self.refresh_history_list)

    def _on_recording_started_event(self, event):
        """Handle RECORDING_STARTED event - update voice button state."""
        def update():
            self.recording = True
            self.btn_voice.set_label("Recording... Click to Stop")
        GLib.idle_add(update)

    def _on_recording_stopped_event(self, event):
        """Handle RECORDING_STOPPED event - reset voice button state."""
        def update():
            self.recording = False
            self.btn_voice.set_label("Start Voice Input")
        GLib.idle_add(update)

    def _on_transcription_complete_event(self, event):
        """Handle TRANSCRIPTION_COMPLETE event - log completion."""
        text = event.data.get('text', '')[:50]
        print(f"[Event] Transcription complete: {text}...")

    def _on_playback_started_event(self, event):
        """Handle PLAYBACK_STARTED event - log playback start."""
        audio_path = event.data.get('audio_path', '')
        print(f"[Event] Playback started: {audio_path}")

    def _on_playback_stopped_event(self, event):
        """Handle PLAYBACK_STOPPED event - log playback stop."""
        audio_path = event.data.get('audio_path', '')
        print(f"[Event] Playback stopped: {audio_path}")

    def _on_tts_complete_event(self, event):
        """Handle TTS_COMPLETE event - log TTS completion."""
        audio_path = event.data.get('audio_path', '')
        print(f"[Event] TTS complete: {audio_path}")

    def _on_model_changed_event(self, event):
        """Handle MODEL_CHANGED event - update model combo if needed."""
        model_id = event.data.get('model_id', '')
        source = event.source
        # Only update if change came from elsewhere (not UI)
        if source != 'ui' and model_id:
            GLib.idle_add(lambda: self._select_model_in_combo(model_id))

    def _select_model_in_combo(self, model_id):
        """Select a model in the combo box by model_id."""
        if getattr(self, '_updating_model', False):
            return
        display_text = self._model_id_to_display.get(model_id, model_id)
        model_store = self.combo_model.get_model()
        iter = model_store.get_iter_first()
        idx = 0
        while iter:
            if model_store.get_value(iter, 0) == display_text:
                self.combo_model.set_active(idx)
                return
            iter = model_store.iter_next(iter)
            idx += 1

    def _on_models_fetched_event(self, event):
        """Handle MODELS_FETCHED event - refresh model list."""
        provider = event.data.get('provider', '')
        models = event.data.get('models', [])
        print(f"[Event] Models fetched for {provider}: {len(models)} models")

    def _on_tool_executed_event(self, event):
        """Handle TOOL_EXECUTED event - log tool execution."""
        tool_name = event.data.get('tool_name', '')
        print(f"[Event] Tool executed: {tool_name}")

    def _on_tool_result_event(self, event):
        """Handle TOOL_RESULT event - log tool result."""
        tool_name = event.data.get('tool_name', '')
        success = event.data.get('success', False)
        status = "success" if success else "failed"
        print(f"[Event] Tool result: {tool_name} - {status}")

    # -----------------------------------------------------------------------
    # System prompt management
    # -----------------------------------------------------------------------

    def _refresh_system_prompt_combo(self):
        """
        Refresh the system prompt combo box from self.system_prompts.
        
        Shows the combo only when there is more than one prompt.
        """
        # Block signal to avoid triggering on_system_prompt_changed during refresh
        self.combo_system_prompt.handler_block_by_func(self.on_system_prompt_changed)
        try:
            self.combo_system_prompt.remove_all()
            for prompt in getattr(self, "system_prompts", []):
                self.combo_system_prompt.append(prompt["id"], prompt["name"])
            
            # Set active to the current active_system_prompt_id
            active_id = getattr(self, "active_system_prompt_id", "")
            if active_id:
                self.combo_system_prompt.set_active_id(active_id)
            elif self.system_prompts:
                self.combo_system_prompt.set_active(0)
            
            # Only show if multiple prompts
            if len(getattr(self, "system_prompts", [])) > 1:
                self.combo_system_prompt.set_visible(True)
                self.combo_system_prompt.set_no_show_all(False)
            else:
                self.combo_system_prompt.set_visible(False)
                self.combo_system_prompt.set_no_show_all(True)
        finally:
            self.combo_system_prompt.handler_unblock_by_func(self.on_system_prompt_changed)

    def on_system_prompt_changed(self, combo):
        """Handle system prompt selection changes."""
        new_id = combo.get_active_id()
        if not new_id or new_id == getattr(self, "active_system_prompt_id", ""):
            return
        
        prompt = self._get_system_prompt_by_id(new_id)
        if not prompt:
            return
        
        # Update in-memory state
        self.active_system_prompt_id = new_id
        self.system_message = prompt["content"]
        
        # Update the system message in the current conversation history
        if self.conversation_history and self.conversation_history[0].get("role") == "system":
            self.conversation_history[0]["content"] = prompt["content"]
        
        # Persist the change
        save_object_settings(self)

    def fetch_models_async(self):
        """Fetch available models asynchronously."""
        # Check if filtering should be disabled via environment variable
        env_val = os.getenv('DISABLE_MODEL_FILTER', '')
        disable_filter = env_val.strip().lower() in ('true', '1', 'yes')

        # Gather whitelist sets from settings (parsed from comma-separated strings)
        whitelists = {}
        for provider_key in ('openai', 'gemini', 'grok', 'claude', 'perplexity', 'custom'):
            attr = f"{provider_key}_model_whitelist"
            whitelist_str = getattr(self, attr, "") or ""
            whitelists[provider_key] = set(m.strip() for m in whitelist_str.split(",") if m.strip())

        def fetch_thread():
            if not self.providers:
                default_models = self._default_models_for_provider('openai')
                mapping = {model: 'openai' for model in default_models}
                GLib.idle_add(self.apply_model_fetch_results, default_models, mapping)
                return

            collected_models = []
            mapping = {}
            for name, provider in self.providers.items():
                try:
                    # Fetch all models from the provider (no provider-side filtering)
                    provider_models = provider.get_available_models(disable_filter=True)
                except Exception as e:
                    print(f"Error fetching models for {name}: {e}")
                    provider_models = self._default_models_for_provider(name)

                # Apply whitelist filtering unless disabled
                whitelist = whitelists.get(name, set())
                if not disable_filter and whitelist:
                    provider_models = [m for m in provider_models if m in whitelist]

                for model in provider_models:
                    mapping[model] = name
                    collected_models.append(model)

            # Add custom models (persisted on disk)
            if self.custom_models:
                custom_whitelist = whitelists.get('custom', set())
                custom_ids = list(self.custom_models.keys())
                if not disable_filter and custom_whitelist:
                    custom_ids = [m for m in custom_ids if m in custom_whitelist]
                for model_id in custom_ids:
                    mapping[model_id] = 'custom'
                    collected_models.append(model_id)

            if not collected_models:
                collected_models = self._default_models_for_provider('openai')
                mapping = {model: 'openai' for model in collected_models}

            unique_models = sorted(dict.fromkeys(collected_models))
            GLib.idle_add(self.apply_model_fetch_results, unique_models, mapping)

        # Start fetch in background
        threading.Thread(target=fetch_thread, daemon=True).start()

    def _default_models_for_provider(self, provider_name):
        """Delegate to controller."""
        return self.controller.get_default_models_for_provider(provider_name)

    def initialize_provider(self, provider_name, api_key):
        """Delegate to controller, then update global ai_provider if needed."""
        global ai_provider
        provider = self.controller.initialize_provider(provider_name, api_key)
        if provider_name == 'openai':
            ai_provider = provider
        return provider

    def _get_conversation_buffer_limit(self):
        """Delegate to controller."""
        return self.controller.get_conversation_buffer_limit()

    def _apply_conversation_buffer_limit(self, history):
        """Delegate to controller."""
        return self.controller.apply_conversation_buffer_limit(history)

    def _messages_for_model(self, model_name):
        """Delegate to controller."""
        return self.controller.messages_for_model(model_name)

    def _clean_messages_for_perplexity(self, messages):
        """
        Clean messages to ensure proper alternation for Perplexity API.
        
        Perplexity requires that after the optional system message(s), user and
        assistant messages must strictly alternate, starting with a user message.
        """
        if not messages:
            return messages

        cleaned = []
        
        # First, extract system messages and other messages
        system_messages = []
        other_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == "system":
                # Keep system message with clean structure
                system_messages.append({
                    "role": "system",
                    "content": content,
                })
            elif content:  # Skip empty non-system messages
                other_messages.append({
                    "role": role,
                    "content": content,
                })
        
        # Add system messages first
        cleaned.extend(system_messages)
        
        # Process non-system messages to ensure strict alternation
        # Perplexity requires: user, assistant, user, assistant, ... ending with user
        alternating = []
        expected_role = "user"  # Must start with user after system
        
        for msg in other_messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == expected_role:
                # Correct role - add it
                alternating.append({"role": role, "content": content})
                expected_role = "assistant" if role == "user" else "user"
            elif role == "user" and expected_role == "user":
                # Another user message when we expected user - merge with previous if exists
                if alternating and alternating[-1]["role"] == "user":
                    alternating[-1]["content"] += "\n\n" + content
                else:
                    alternating.append({"role": role, "content": content})
                    expected_role = "assistant"
            elif role == "assistant" and expected_role == "assistant":
                # Another assistant message when we expected assistant - merge
                if alternating and alternating[-1]["role"] == "assistant":
                    alternating[-1]["content"] += "\n\n" + content
                else:
                    alternating.append({"role": role, "content": content})
                    expected_role = "user"
            elif role == "user" and expected_role == "assistant":
                # Got user when expecting assistant - skip the missing assistant and add user
                # This handles cases where assistant response was empty/missing
                alternating.append({"role": role, "content": content})
                expected_role = "assistant"
            elif role == "assistant" and expected_role == "user":
                # Got assistant when expecting user - skip this assistant message
                # The first message after system must be user
                continue
        
        # Ensure we have at least one user message and it ends with user
        if not alternating:
            return messages  # Return original if something went wrong
        
        # If the last message is assistant, that's fine for Perplexity
        # (they want alternation, ending with user is for the request)
        
        cleaned.extend(alternating)
        return cleaned

    def get_provider_name_for_model(self, model_name):
        if not model_name:
            return 'openai'
        
        # Card-first: check model card for provider
        card = get_card(model_name, self.custom_models)
        if card:
            return card.provider
        
        # If we have an explicit mapping from model fetch, use it.
        provider = self.model_provider_map.get(model_name)
        if provider:
            return provider

        # Custom models are explicitly configured by the user.
        if model_name in getattr(self, "custom_models", {}):
            return "custom"

        # Unknown model - default to openai
        return 'openai'

    def _is_image_model_for_provider(self, model_name, provider_name):
        """
        Return True if the given model for the specified provider should be
        treated as an image-generation model.
        """
        return self.controller.tool_service.is_image_model(model_name, provider_name, self.custom_models)

    def _supports_image_tools(self, model_name):
        """
        Return True if the given model should be offered the image-generation
        tool. Delegates to ToolService.
        """
        return self.controller.tool_service.supports_image_tools(model_name, self.model_provider_map, self.custom_models)

    def _supports_music_tools(self, model_name):
        """
        Return True if the given model should be offered the music-control tool.
        Delegates to ToolService.
        """
        return self.controller.tool_service.supports_music_tools(model_name, self.model_provider_map, self.custom_models)

    def _supports_read_aloud_tools(self, model_name):
        """
        Return True if the given model should be offered the read-aloud tool.
        Delegates to ToolService.
        """
        return self.controller.tool_service.supports_read_aloud_tools(model_name, self.model_provider_map, self.custom_models)

    def _supports_search_tools(self, model_name):
        """
        Return True if the given model should be offered the search/memory tool.
        Delegates to ToolService.
        """
        return self.controller.tool_service.supports_search_tools(model_name, self.model_provider_map, self.custom_models)

    def _normalize_image_tags(self, text):
        """
        Normalize image references into the self-closing <img src="..."/> form
        that the UI expects. Handles:
        - HTML <img> tags with extra attributes
        - Markdown image syntax ![alt](path) or ![alt](sandbox:path)
        
        Deduplicates images by src to avoid displaying the same image multiple times.
        """
        if not text:
            return text
        import re
        
        seen_src = set()
        
        # First, convert markdown images to HTML: ![alt](path) or ![alt](sandbox:path)
        def md_to_html(match):
            path = match.group(2)
            # Strip sandbox: prefix if present
            if path.startswith('sandbox:'):
                path = path[8:]
            if path in seen_src:
                return ""
            seen_src.add(path)
            return f'<img src="{path}"/>'
        
        text = re.sub(r'!\[([^\]]*)\]\((?:sandbox:)?([^)]+)\)', md_to_html, text)
        
        # Then normalize HTML img tags
        pattern = re.compile(r'<img\s+src="([^"]+)"[^>]*>', re.IGNORECASE)

        result_parts = []
        last_end = 0

        for match in pattern.finditer(text):
            result_parts.append(text[last_end:match.start()])
            src = match.group(1)

            if src in seen_src:
                replacement = ""
            else:
                seen_src.add(src)
                replacement = f'<img src="{src}"/>'

            result_parts.append(replacement)
            last_end = match.end()

        result_parts.append(text[last_end:])
        return "".join(result_parts)

    def generate_image_for_model(self, model, prompt, last_msg, chat_id, provider_name, has_attached_images):
        """
        Central helper to generate an image for any supported provider/model.
        Delegates to ImageGenerationService.
        """
        # Prepare image data for editing
        image_data = None
        mime_type = None
        
        card = get_card(model, self.custom_models)
        supports_image_edit = card.capabilities.image_edit if card else False
        
        if supports_image_edit and has_attached_images and last_msg.get("images"):
            img = last_msg["images"][0]
            image_data = img.get("data")
            mime_type = img.get("mime_type")
        
        # Get provider
        provider = self._get_image_provider(model, provider_name)
        
        return self.controller.image_service.generate_image(
            prompt=prompt,
            model=model,
            provider=provider,
            provider_name=provider_name,
            chat_id=chat_id,
            image_data=image_data,
            mime_type=mime_type,
        )
    
    def _get_image_provider(self, model, provider_name):
        """Get or initialize provider for image generation."""
        if provider_name == "custom":
            provider = self.custom_providers.get(model)
            if not provider:
                cfg = (self.custom_models or {}).get(model, {})
                if not cfg:
                    raise ValueError(f"Custom model '{model}' is not configured")
                provider = get_ai_provider("custom")
                from utils import resolve_api_key
                provider.initialize(
                    api_key=resolve_api_key(cfg.get("api_key", "")).strip(),
                    endpoint=cfg.get("endpoint"),
                    model_name=cfg.get("model_name") or model,
                    api_type=cfg.get("api_type") or "images",
                    voice=cfg.get("voice"),
                )
                self.custom_providers[model] = provider
            return provider
        else:
            # Get provider via controller
            provider = self.controller.get_provider(provider_name)
            if not provider:
                raise ValueError(f"{provider_name.title()} provider is not initialized")
            return provider

    def generate_image_via_preferred_model(self, prompt, last_msg, image_path=None):
        """
        Generate or edit an image using the user-configured preferred image model,
        falling back to a safe OpenAI default if necessary.
        
        Note: We trust the user's selection here - if they've explicitly chosen
        a model as the image handler, we'll try to use it even if it's not
        recognized as a standard image model.
        
        Args:
            prompt: The text prompt for image generation/editing
            last_msg: The last user message dict
            image_path: Optional path to source image for editing
        """
        preferred_model = getattr(self, "image_model", None) or "dall-e-3"
        provider_name = self.get_provider_name_for_model(preferred_model)

        # For standard image models, verify they're recognized. For custom models,
        # trust the user's selection - they may have configured a responses API model
        # that can generate images.
        is_standard_image_model = self._is_image_model_for_provider(preferred_model, provider_name)
        is_custom_model = provider_name == "custom" and preferred_model in (self.custom_models or {})
        
        if not is_standard_image_model and not is_custom_model:
            # Only fall back if it's not a recognized image model AND not a custom model
            preferred_model = "dall-e-3"
            provider_name = "openai"

        # If image_path is provided, create a synthetic last_msg with the image
        effective_last_msg = last_msg
        has_attached_images = "images" in last_msg and last_msg["images"]
        
        if image_path:
            try:
                effective_last_msg = {
                    **last_msg,
                    "images": [{"path": image_path, "mime_type": "image/png", "is_edit_source": True}]
                }
                has_attached_images = True
            except Exception as e:
                print(f"[Image Tool] Error loading image for editing: {e}")

        print(f"[Image Tool] Using model: {preferred_model} (provider: {provider_name}), editing: {image_path is not None}")
        try:
            return self.generate_image_for_model(
                model=preferred_model,
                prompt=prompt or last_msg.get("content", "") or "",
                last_msg=effective_last_msg,
                chat_id=self.current_chat_id or "temp",
                provider_name=provider_name,
                has_attached_images=has_attached_images,
            )
        except Exception as e:
            # If the preferred provider/model fails (e.g., missing key), fall
            # back to OpenAI dall-e-3 as a last resort.
            print(f"[Image Tool] Preferred model failed ({preferred_model} via {provider_name}): {e}")
            fallback_model = "dall-e-3"
            print(f"[Image Tool] Falling back to: {fallback_model} (provider: openai)")
            try:
                return self.generate_image_for_model(
                    model=fallback_model,
                    prompt=prompt or last_msg.get("content", "") or "",
                    last_msg=last_msg,
                    chat_id=self.current_chat_id or "temp",
                    provider_name="openai",
                    has_attached_images=False,
                )
            except Exception as inner:
                raise RuntimeError(f"Image generation failed for both preferred and fallback models: {inner}") from inner

    def _get_beets_library(self):
        """
        Get a beets Library instance based on configured settings.
        
        Returns a Library instance or raises an exception with a user-friendly message.
        """
        try:
            from beets.library import Library
        except ImportError:
            raise RuntimeError(
                "The beets library is not installed. Please install it with: pip install beets"
            )
        
        library_db = getattr(self, "music_library_db", "") or ""
        library_dir = getattr(self, "music_library_dir", "") or ""
        
        # If user provided a specific DB path, use it
        if library_db:
            if not os.path.exists(library_db):
                raise RuntimeError(
                    f"Beets library database not found at: {library_db}. "
                    "Please check your Music Library DB path in Settings → Tool Options."
                )
            return Library(library_db, directory=library_dir if library_dir else None)
        
        # Check for app-generated library in the application folder
        app_library_db = os.path.join(PARENT_DIR, "music_library.db")
        if os.path.exists(app_library_db):
            return Library(app_library_db, directory=library_dir if library_dir else None)
        
        # Otherwise try to use beets' default configuration
        try:
            import beets.util
            from beets import config as beets_config
            beets_config.read(user=True, defaults=True)
            default_db = beets_config['library'].get()
            default_dir = beets_config['directory'].get()
            
            if library_dir:
                # User specified a directory but not a DB; use default DB with custom dir
                return Library(default_db, directory=library_dir)
            else:
                return Library(default_db, directory=default_dir)
        except Exception as e:
            # If beets config fails, provide a helpful message
            raise RuntimeError(
                f"Could not load beets library. Either generate a library using the "
                f"'Generate Library' button in Settings → Tool Options, configure a "
                f"beets library DB path, or ensure beets is properly configured. "
                f"Error: {e}"
            )

    def _control_music_via_beets(self, action, keyword=None, volume=None):
        """
        Core implementation of the control_music tool using beets library
        and a local music player.
        """
        action = (action or "").strip().lower()
        if not action:
            return "Error: music control action is required."

        player_path = getattr(self, "music_player_path", "/usr/bin/mpv") or "/usr/bin/mpv"

        # Handle play action: query beets and launch player
        if action == "play":
            if not keyword or not keyword.strip():
                return "Error: 'play' action requires a beets query string describing what to play."

            try:
                lib = self._get_beets_library()
            except RuntimeError as e:
                return f"Error: {e}"

            # Query beets for matching items
            query = keyword.strip()
            try:
                items = list(lib.items(query))
            except Exception as e:
                return f"Error querying beets library: {e}"

            if not items:
                return f"No tracks found matching query: {query}"

            # Limit to a reasonable number of tracks to avoid enormous playlists
            max_tracks = 100
            if len(items) > max_tracks:
                items = items[:max_tracks]
                limited_msg = f" (limited to first {max_tracks} tracks)"
            else:
                limited_msg = ""

            # Create a temporary M3U playlist
            try:
                playlist_fd, playlist_path = tempfile.mkstemp(suffix=".m3u", prefix="chatgtk_music_")
                with os.fdopen(playlist_fd, 'w', encoding='utf-8') as f:
                    f.write("#EXTM3U\n")
                    for item in items:
                        # item.path is bytes in beets, decode it
                        path = item.path
                        if isinstance(path, bytes):
                            path = path.decode('utf-8', errors='replace')
                        f.write(f"{path}\n")
            except Exception as e:
                return f"Error creating playlist: {e}"

            # Launch the music player with the playlist.
            # The user can configure the full command (including arguments) in
            # the Music Player Executable setting, optionally using a
            # "<playlist>" placeholder.
            player_cmd_template = getattr(self, "music_player_path", "/usr/bin/mpv") or "/usr/bin/mpv"
            try:
                import shlex
                parts = shlex.split(player_cmd_template)
                if not parts:
                    raise ValueError("Music player command is empty.")
                if "<playlist>" in player_cmd_template:
                    # Replace placeholder in each argument.
                    cmd = [p.replace("<playlist>", playlist_path) for p in parts]
                else:
                    # No placeholder: append playlist path as a positional argument.
                    cmd = parts + [playlist_path]
            except ValueError as e:
                # Clean up playlist on error
                try:
                    os.unlink(playlist_path)
                except Exception:
                    pass
                return f"Error parsing music player command: {e}"

            try:
                print(f"Launching music player with command: {cmd}")
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                # Reap the child process in a background thread to avoid zombies
                def cleanup_player():
                    proc.wait()
                    # Clean up playlist file after player exits
                    try:
                        os.unlink(playlist_path)
                    except Exception:
                        pass
                threading.Thread(target=cleanup_player, daemon=True).start()
                
                return f"Started playing {len(items)} track(s) matching '{query}'{limited_msg}"
            except FileNotFoundError:
                # Clean up playlist on error
                try:
                    os.unlink(playlist_path)
                except Exception:
                    pass
                return (
                    f"Error: Music player not found at '{player_path}'. "
                    "Please check your Music Player Executable path in Settings → Tool Options."
                )
            except Exception as e:
                # Clean up playlist on error
                try:
                    os.unlink(playlist_path)
                except Exception:
                    pass
                print(f"Error launching music player: {e}")
                return f"Error starting music player: {e}"

        # Non-play actions have limited support
        # Try to use playerctl if available, targeting the configured player.
        # For playerctl we only want the base executable name, without any
        # command-line switches. For example, "mpv --playlist" should become
        # just "mpv" when used as the player name.
        player_name_source = str(player_path).strip().split()[0]
        player_name = os.path.basename(player_name_source)
        
        if action in ("pause", "resume", "stop", "next", "previous", "volume_up", "volume_down", "set_volume"):
            try:
                # Check if playerctl is available
                subprocess.run(
                    ["playerctl", "--version"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
            except (FileNotFoundError, subprocess.CalledProcessError):
                return (
                    f"Action '{action}' requires playerctl for MPRIS control, but playerctl "
                    "is not installed. Install playerctl via your package manager, or use "
                    "'play' with a new query to start different music."
                )

            # Build playerctl command - try to target the player
            base_cmd = ["playerctl", "-p", player_name]

            if action == "pause":
                cmd = base_cmd + ["pause"]
                success_msg = "Paused playback."
            elif action == "resume":
                cmd = base_cmd + ["play"]
                success_msg = "Resumed playback."
            elif action == "stop":
                cmd = base_cmd + ["stop"]
                success_msg = "Stopped playback."
            elif action == "next":
                cmd = base_cmd + ["next"]
                success_msg = "Skipped to next track."
            elif action == "previous":
                cmd = base_cmd + ["previous"]
                success_msg = "Went back to previous track."
            elif action == "volume_up":
                cmd = base_cmd + ["volume", "0.05+"]
                success_msg = "Increased volume."
            elif action == "volume_down":
                cmd = base_cmd + ["volume", "0.05-"]
                success_msg = "Decreased volume."
            elif action == "set_volume":
                if volume is None:
                    return "Error: 'set_volume' action requires a numeric volume value (0-100)."
                try:
                    vol = float(volume)
                except (TypeError, ValueError):
                    return "Error: volume must be a number between 0 and 100."
                if vol > 1.0:
                    vol = vol / 100.0
                vol = max(0.0, min(1.0, vol))
                cmd = base_cmd + ["volume", f"{vol:.2f}"]
                success_msg = f"Set volume to approximately {int(vol * 100)}%."

            try:
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    stderr = (result.stderr or "").strip()
                    stdout = (result.stdout or "").strip()
                    detail = stderr or stdout or "Unknown error from playerctl."
                    return f"Error controlling playback via playerctl: {detail}"
                return success_msg
            except Exception as e:
                print(f"Error running playerctl command {cmd}: {e}")
                return f"Error controlling playback: {e}"
        else:
            return f"Error: unsupported music control action '{action}'."

    def control_music_via_beets(self, action, keyword=None, volume=None):
        """
        Public wrapper used by AI provider tool handlers to control music via beets.
        """
        return self._control_music_via_beets(action, keyword=keyword, volume=volume)

    def _handle_read_aloud_tool(self, text: str) -> str:
        """
        Handle read_aloud tool calls from AI models.
        
        This is called when a model invokes the read_aloud tool to speak text
        to the user. Uses the unified TTS settings (tts_voice_provider, tts_voice,
        tts_hd, tts_prompt_template) and blocks until playback is complete so 
        the tool returns a proper status.
        """
        if not text:
            return "No text provided to read aloud."
        
        try:
            # Use unified TTS settings (tts_voice_provider)
            provider = getattr(self, 'tts_voice_provider', 'openai') or 'openai'
            
            # Check if this is a custom TTS model
            custom_models = getattr(self, 'custom_models', {}) or {}
            is_custom_tts = provider in custom_models and (custom_models[provider].get('api_type') or '').lower() == 'tts'
            
            if provider == 'openai':
                success = self._synthesize_and_play_tts(
                    text,
                    chat_id=self.current_chat_id,
                    stop_event=None
                )
            elif provider == 'gemini':
                success = self._synthesize_and_play_gemini_tts(
                    text,
                    chat_id=self.current_chat_id,
                    stop_event=None
                )
            elif provider in ('gpt-4o-audio-preview', 'gpt-4o-mini-audio-preview'):
                success = self._synthesize_and_play_audio_preview(
                    text,
                    chat_id=self.current_chat_id,
                    model_id=provider,
                    stop_event=None
                )
            elif is_custom_tts:
                success = self._synthesize_and_play_custom_tts(
                    text,
                    chat_id=self.current_chat_id,
                    model_id=provider,
                    stop_event=None
                )
            else:
                return f"Unknown TTS provider: {provider}"
            
            if success:
                return "Text was read aloud successfully."
            else:
                return "Failed to read text aloud."
        except Exception as e:
            return f"Error reading aloud: {e}"

    def _handle_search_memory_tool(self, keyword: str, source: str = "history") -> str:
        """
        Handle search_memory tool calls from AI models.
        
        Searches past conversations and/or configured directories for the keyword
        using word-boundary matching.
        
        Parameters
        ----------
        keyword : str
            The word or phrase to search for.
        source : str
            Where to search: 'history', 'documents', or 'all'.
        """
        import re
        import glob
        from config import HISTORY_DIR
        
        print(f"[SearchTool] Called with keyword='{keyword}', source='{source}'")
        
        if not keyword:
            return "No keyword provided for search."
        
        keyword = keyword.strip()
        source = (source or "history").strip().lower()
        
        # Get settings
        search_history_enabled = bool(getattr(self, "search_history_enabled", True))
        search_directories = getattr(self, "search_directories", "") or ""
        result_limit = int(getattr(self, "search_result_limit", 1))
        result_limit = max(1, min(5, result_limit))
        
        # Build word-boundary regex pattern
        pattern = re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)
        
        results = []
        
        # Search history if enabled and source includes history
        if search_history_enabled and source in ("history", "all"):
            history_results = self._search_history_files(keyword, pattern, result_limit)
            results.extend(history_results)
        
        # Search additional directories if source includes documents
        if source in ("documents", "all") and search_directories:
            dirs = [d.strip() for d in search_directories.split(",") if d.strip()]
            for directory in dirs:
                if os.path.isdir(directory):
                    doc_results = self._search_directory(directory, keyword, pattern, result_limit - len(results))
                    results.extend(doc_results)
                    if len(results) >= result_limit:
                        break
        
        # Limit results
        results = results[:result_limit]
        
        if not results:
            return f"No results found for '{keyword}'."
        
        # Format results for the model
        formatted = []
        for i, result in enumerate(results, 1):
            formatted.append(f"--- Result {i} ---\nSource: {result['source']}\n{result['content']}")
        
        result_text = f"Found {len(results)} result(s) for '{keyword}':\n\n" + "\n\n".join(formatted)
        
        # If show_results is disabled, prefix with __HIDE_TOOL_RESULT__ so providers
        # won't append it to the visible output (but it's still sent to the model)
        show_results = bool(getattr(self, "search_show_results", False))
        if not show_results:
            return "__HIDE_TOOL_RESULT__" + result_text
        return result_text
    
    def _search_history_files(self, keyword: str, pattern, limit: int) -> list:
        """Search conversation history JSON files for keyword matches."""
        # Use controller's search_history method which delegates to service/repository
        search_results = self.controller.search_history(keyword, limit)
        
        results = []
        for sr in search_results:
            # Format matches for display
            matches_text = "\n".join(sr.get('matches', [])[:3])
            results.append({
                "source": f"Chat: {sr.get('chat_title', sr.get('chat_id', 'Unknown'))}",
                "content": matches_text
            })
        
        return results
    
    def _search_directory(self, directory: str, keyword: str, pattern, limit: int) -> list:
        """Search text files in a directory for keyword matches."""
        import glob
        
        results = []
        
        # Search common text file types
        file_patterns = ["*.txt", "*.md", "*.json", "*.log", "*.csv"]
        
        for file_pattern in file_patterns:
            if len(results) >= limit:
                break
            
            files = glob.glob(os.path.join(directory, "**", file_pattern), recursive=True)
            
            for filepath in files:
                if len(results) >= limit:
                    break
                
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    
                    if pattern.search(content):
                        # Extract matching lines with context
                        lines = content.split('\n')
                        matching_lines = []
                        for i, line in enumerate(lines):
                            if pattern.search(line):
                                # Get line with some context
                                start = max(0, i - 1)
                                end = min(len(lines), i + 2)
                                context = '\n'.join(lines[start:end])
                                matching_lines.append(context)
                                if len(matching_lines) >= 3:
                                    break
                        
                        if matching_lines:
                            results.append({
                                "source": f"File: {filepath}",
                                "content": "\n---\n".join(matching_lines)[:1000]
                            })
                            
                except (IOError, UnicodeDecodeError):
                    continue
        
        return results

    def apply_model_fetch_results(self, models, mapping):
        if mapping:
            self.model_provider_map = mapping
        current_model = self._get_model_id_from_combo() or self.default_model
        self.update_model_list(models, current_model)

        # Also ensure the Image Model dropdown includes any image-capable models
        # that were discovered dynamically from providers.
        try:
            # Only update if combo_image_model exists (i.e., when settings dialog is open)
            if hasattr(self, 'combo_image_model') and self.combo_image_model is not None:
                image_like_models = []
                for model_id in models or []:
                    # Check if model is an image model via card
                    card = get_card(model_id, self.custom_models)
                    if card and card.is_image_model():
                        image_like_models.append(model_id)

                # Collect existing entries to avoid duplicates.
                existing = []
                model_store = self.combo_image_model.get_model()
                if model_store is not None:
                    it = model_store.get_iter_first()
                    while it:
                        existing.append(model_store.get_value(it, 0))
                        it = model_store.iter_next(it)

                for model_id in image_like_models:
                    if model_id not in existing:
                        self.combo_image_model.append_text(model_id)
        except Exception as e:
            # Failing to enrich the image model list should never break model loading.
            print(f"Error updating image model list: {e}")

        return False

    def on_open_settings(self, widget):
        # Gather current API keys from environment or stored values
        from utils import API_KEY_FIELDS
        current_api_keys = {}
        # Standard keys: prefer environment variables, fall back to stored values
        current_api_keys['openai'] = os.environ.get('OPENAI_API_KEY', self.api_keys.get('openai', ''))
        current_api_keys['gemini'] = os.environ.get('GEMINI_API_KEY', self.api_keys.get('gemini', ''))
        current_api_keys['grok'] = os.environ.get('GROK_API_KEY', self.api_keys.get('grok', ''))
        current_api_keys['claude'] = os.environ.get('CLAUDE_API_KEY', self.api_keys.get('claude', ''))
        current_api_keys['perplexity'] = os.environ.get('PERPLEXITY_API_KEY', self.api_keys.get('perplexity', ''))
        # Include all custom keys (keys that aren't in API_KEY_FIELDS)
        for key_name, key_value in self.api_keys.items():
            if key_name not in API_KEY_FIELDS:
                current_api_keys[key_name] = key_value

        # Pass ai_provider, providers dict, and api_keys to the settings dialog
        dialog = SettingsDialog(
            self,
            ai_provider=self.controller.get_provider('openai'),
            providers=self.providers,
            api_keys=current_api_keys,
            **{k.lower(): getattr(self, k.lower()) for k in SETTINGS_CONFIG.keys()}
        )
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            new_settings = dialog.get_settings()
            apply_settings(self, new_settings)
            save_object_settings(self)

            # Update message renderer settings and refresh existing message colors
            self._update_message_renderer_settings()
            if hasattr(self, 'message_renderer'):
                self.message_renderer.update_existing_message_colors()

            # Re-initialize system prompts from updated settings and refresh the combo
            self._init_system_prompts_from_settings()
            self._refresh_system_prompt_combo()
            
            # Update the system message in the current conversation if it exists
            if self.conversation_history and self.conversation_history[0].get("role") == "system":
                self.conversation_history[0]["content"] = self.system_message

            # Keep tools in sync via service
            self.controller.tool_service.enable_tool('image', bool(getattr(self, "image_tool_enabled", True)))
            self.controller.tool_service.enable_tool('music', bool(getattr(self, "music_tool_enabled", False)))
            self.controller.tool_service.enable_tool('read_aloud', bool(getattr(self, "read_aloud_tool_enabled", False)))
            self.controller.tool_service.enable_tool('search', bool(getattr(self, "search_tool_enabled", False)))

            # Handle API keys from the dialog
            new_keys = dialog.get_api_keys()
            self._apply_api_keys(new_keys)

            # Update custom models from dialog (already persisted on disk)
            if hasattr(dialog, "get_custom_models"):
                self.custom_models = dialog.get_custom_models()
                # Drop any cached custom providers to avoid stale configs
                self.custom_providers = {}

            self.fetch_models_async()
        dialog.destroy()

    def on_open_prompt_editor(self, widget):
        """Open a larger dialog for composing a more complex prompt."""
        initial_text = self.entry_question.get_text()

        def voice_input_callback(textview):
            """Handle voice input for the prompt editor textview."""
            self._audio_transcription_to_textview(textview)

        dialog = PromptEditorDialog(self, initial_text=initial_text, on_voice_input=voice_input_callback)
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            text = dialog.get_text().strip()
            self.entry_question.set_text(text)

        dialog.destroy()

    def on_question_icon_pressed(self, entry, icon_pos, event):
        """Clear the question entry when its clear icon is clicked."""
        if icon_pos == Gtk.EntryIconPosition.SECONDARY:
            entry.set_text("")

    def _apply_api_keys(self, new_keys):
        """Apply API key changes: update stored keys, environment, and providers."""
        from utils import API_KEY_FIELDS
        # Update stored keys (standard and custom)
        for key_name, key_value in new_keys.items():
            self.api_keys[key_name] = key_value
        
        # Handle standard keys (set environment variables and initialize providers)
        # Standard keys are handled below, custom keys are just stored above

        # Update environment variables and providers
        if new_keys['openai']:
            os.environ['OPENAI_API_KEY'] = new_keys['openai']
            self.initialize_provider('openai', new_keys['openai'])
        else:
            os.environ.pop('OPENAI_API_KEY', None)
            self.providers.pop('openai', None)

        if new_keys['gemini']:
            os.environ['GEMINI_API_KEY'] = new_keys['gemini']
            self.initialize_provider('gemini', new_keys['gemini'])
        else:
            os.environ.pop('GEMINI_API_KEY', None)
            self.providers.pop('gemini', None)

        if new_keys['grok']:
            os.environ['GROK_API_KEY'] = new_keys['grok']
            self.initialize_provider('grok', new_keys['grok'])
        else:
            os.environ.pop('GROK_API_KEY', None)
            self.providers.pop('grok', None)

        if new_keys['claude']:
            os.environ['CLAUDE_API_KEY'] = new_keys['claude']
            os.environ['ANTHROPIC_API_KEY'] = new_keys['claude']
            self.initialize_provider('claude', new_keys['claude'])
        else:
            os.environ.pop('CLAUDE_API_KEY', None)
            os.environ.pop('ANTHROPIC_API_KEY', None)
            self.providers.pop('claude', None)

        if new_keys.get('perplexity'):
            os.environ['PERPLEXITY_API_KEY'] = new_keys['perplexity']
            self.initialize_provider('perplexity', new_keys['perplexity'])
        else:
            os.environ.pop('PERPLEXITY_API_KEY', None)
            self.providers.pop('perplexity', None)

    def on_open_tools(self, widget):
        # Open the tools dialog for configuring image/music tools.
        current_model = self._get_model_id_from_combo()
        card = get_card(current_model, self.custom_models)
        tool_use_supported = bool(card and card.supports_tools() and card.is_chat_model())
        dialog = ToolsDialog(self, **{k.lower(): getattr(self, k.lower())
                               for k in SETTINGS_CONFIG.keys()},
                               tool_use_supported=tool_use_supported)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            tool_settings = dialog.get_tool_settings()
            # Apply the updated tool settings to the main window object.
            for key, value in tool_settings.items():
                setattr(self, key, value)
            # Enforce mutual exclusivity: if read_aloud_tool is enabled, disable auto-read
            if getattr(self, "read_aloud_tool_enabled", False) and getattr(self, "read_aloud_enabled", False):
                self.read_aloud_enabled = False
            # Update tools via service
            self.controller.tool_service.enable_tool('image', bool(getattr(self, "image_tool_enabled", True)))
            self.controller.tool_service.enable_tool('music', bool(getattr(self, "music_tool_enabled", False)))
            self.controller.tool_service.enable_tool('read_aloud', bool(getattr(self, "read_aloud_tool_enabled", False)))
            self.controller.tool_service.enable_tool('search', bool(getattr(self, "search_tool_enabled", False)))
            # Persist all settings, including the updated tool flags.
            save_object_settings(self)
        dialog.destroy()



    def apply_css(self, widget, css_string):
        """Apply the provided CSS string to a widget."""
        style_provider = Gtk.CssProvider()
        style_provider.load_from_data(css_string.encode("utf-8"))
        Gtk.StyleContext.add_provider(
            widget.get_style_context(),
            style_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_USER
        )

    def show_error_dialog(self, message: str):
        """Display a simple modal error dialog."""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Error",
        )
        dialog.format_secondary_text(str(message))
        dialog.run()
        dialog.destroy()

    def _show_large_file_warning(self, size_info: str) -> bool:
        """Show warning about large file uploads. Returns True if user wants to continue."""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Large File Warning",
        )
        dialog.format_secondary_text(
            f"{size_info}. Large file uploads can use a lot of tokens. Continue?"
        )
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.YES

    def display_error(self, message: str):
        """Backward-compatible alias used by legacy call sites."""
        self.show_error_dialog(message)

    def on_stream_content_received(self, content: str):
        """Handle realtime text events from the websocket provider."""
        if not content:
            return
        # Treat each callback as a distinct assistant message for now.
        msg_index = len(self.conversation_history)
        assistant_msg = create_assistant_message(content)
        self.conversation_history.append(assistant_msg)
        formatted = format_response(content)
        GLib.idle_add(lambda idx=msg_index, msg=formatted: self.append_message('ai', msg, idx))
        GLib.idle_add(self.save_current_chat)

    def _on_realtime_user_transcript(self, transcript: str):
        """Handle user speech transcript from realtime conversation."""
        if not transcript:
            return
        msg_index = len(self.conversation_history)
        user_msg = create_user_message(transcript)
        self.conversation_history.append(user_msg)
        formatted = format_response(transcript)
        GLib.idle_add(lambda idx=msg_index, msg=formatted: self.append_message('user', msg, idx))
        GLib.idle_add(self.save_current_chat)

    def _on_realtime_assistant_transcript(self, transcript: str):
        """Handle assistant response transcript from realtime conversation."""
        if not transcript:
            return
        msg_index = len(self.conversation_history)
        assistant_msg = create_assistant_message(transcript)
        self.conversation_history.append(assistant_msg)
        formatted = format_response(transcript)
        GLib.idle_add(lambda idx=msg_index, msg=formatted: self.append_message('ai', msg, idx))
        GLib.idle_add(self.save_current_chat)

    def append_message(self, sender, message_text, message_index: int = None):
        if message_index is None:
            if sender == 'ai':
                message_index = max(len(self.conversation_history) - 1, 0)
            else:
                message_index = len(self.conversation_history)

        # Update renderer's chat_id in case it changed
        if hasattr(self, 'message_renderer'):
            self.message_renderer.update_chat_id(self.current_chat_id)
            self.message_renderer.append_message(sender, message_text, message_index)
        else:
            # Fallback to local methods if renderer not initialized yet
            if sender == 'user':
                self.append_user_message(message_text, message_index)
            else:
                self.append_ai_message(message_text, message_index)

    def on_submit(self, widget, event=None):
        question = self.entry_question.get_text().strip()
        if not question and not getattr(self, 'attached_file_path', None):
            return

        selected_model = self._get_model_id_from_combo()
        if not selected_model:
            self.show_error_dialog("Please select a model before sending a message")
            return False

        quick_image_request = question.lower().startswith("img:")
        if quick_image_request:
            question = question[4:].strip()
            # Use the preferred image model when the user explicitly requests an
            # image with the img: prefix, falling back to dall-e-3.
            target_model = getattr(self, "image_model", None) or "dall-e-3"
            provider_name = self.get_provider_name_for_model(target_model)
            self.model_provider_map.setdefault(target_model, provider_name)
        else:
            target_model = selected_model
            provider_name = self.get_provider_name_for_model(target_model)

        if provider_name == 'gemini':
            env_var = 'GEMINI_API_KEY'
            provider_label = "Gemini"
        elif provider_name == 'grok':
            env_var = 'GROK_API_KEY'
            provider_label = "Grok"
        elif provider_name == 'claude':
            env_var = 'CLAUDE_API_KEY'
            provider_label = "Claude"
        elif provider_name == 'perplexity':
            env_var = 'PERPLEXITY_API_KEY'
            provider_label = "Perplexity"
        else:
            env_var = 'OPENAI_API_KEY'
            provider_label = "OpenAI"

        api_key = os.environ.get(env_var, self.api_keys.get(provider_name, '')).strip()
        if not api_key:
            self.show_error_dialog(f"Please enter your {provider_label} API key")
            return False

        os.environ[env_var] = api_key
        provider = self.initialize_provider(provider_name, api_key)
        if not provider:
            self.show_error_dialog(f"Unable to initialize the {provider_label} provider")
            return False
        
        model_temperature = self._get_temperature_for_model(target_model)

        if quick_image_request:
            msg_index = len(self.conversation_history)
            self.append_message('user', question, msg_index)
            self.conversation_history.append(create_user_message(question))
            self.entry_question.set_text("")
            self.emit_thinking_started(target_model)
            threading.Thread(
                target=self.call_ai_api,
                args=(target_model,),
                daemon=True
            ).start()
            return

        # Check if we're in realtime mode
        if "realtime" in target_model.lower():
            if not hasattr(self, 'ws_provider'):
                self.ws_provider = OpenAIWebSocketProvider(callback_scheduler=GLib.idle_add)
                self.ws_provider.on_user_transcript = self._on_realtime_user_transcript
                self.ws_provider.on_assistant_transcript = self._on_realtime_assistant_transcript
                # Connect to WebSocket server
                success = self.ws_provider.connect(
                    model=target_model,
                    system_message=self.system_message,
                    temperature=model_temperature,
                    voice=self.realtime_voice,
                    mute_mic_during_playback=bool(getattr(self, "mute_mic_during_playback", True)),
                    realtime_prompt=self._get_realtime_prompt(),
                    api_key=api_key
                )
                if not success:
                    self.display_error("Failed to connect to WebSocket server")
                    return
                
            self.ws_provider.send_text(question, self.on_stream_content_received)
            msg_index = len(self.conversation_history)
            self.append_message('user', question, msg_index)
            self.conversation_history.append(create_user_message(question))
            self.entry_question.set_text("")
            return
        
        # ... existing non-realtime code ...
        # Use new method to append user message
        
        # Handle attachment - distinguish images from documents
        images = []
        files = []
        display_text = question
        
        # Add pending edit image if selected
        if getattr(self, 'pending_edit_image', None):
            try:
                # Store path instead of data - data will be loaded when sending to API
                images.append({
                    "path": self.pending_edit_image,
                    "mime_type": "image/png",
                    "is_edit_source": True,
                })
                display_text = f"[Editing image]\n{question}" if question else "[Editing image]"
            except Exception as e:
                print(f"Error loading edit image: {e}")
            finally:
                # Clear the pending edit image after use
                self._clear_pending_edit_image()
        
        if getattr(self, 'attached_file_path', None):
            try:
                mime_type, _ = mimetypes.guess_type(self.attached_file_path)
                if not mime_type:
                    mime_type = "application/octet-stream"
                
                filename = os.path.basename(self.attached_file_path)
                original_question = question  # Save for display (don't show file content)
                
                # Determine if this is an image or a document based on MIME type
                is_image = mime_type.startswith("image/")
                
                if is_image:
                    # Handle images: base64 encode and store in images list
                    with open(self.attached_file_path, "rb") as f:
                        file_data = f.read()
                        encoded = base64.b64encode(file_data).decode('utf-8')
                        images.append({
                            "data": encoded,
                            "mime_type": mime_type
                        })
                else:
                    # Handle documents (PDF, text, etc.)
                    # Validate file size (max 512 MB per OpenAI docs)
                    max_file_size = 512 * 1024 * 1024  # 512 MB
                    file_size = os.path.getsize(self.attached_file_path)
                    
                    if file_size > max_file_size:
                        size_mb = file_size / (1024 * 1024)
                        self.show_error_dialog(
                            f"File too large: {size_mb:.1f} MB exceeds maximum of 512 MB"
                        )
                        self.attached_file_path = None
                        self.btn_attach.set_label("Attach File")
                        return
                    
                    # For PDFs, pass the file through to the provider via the Responses API.
                    if mime_type == "application/pdf":
                        # Warn about large PDFs (>1MB)
                        if file_size > 1024 * 1024:
                            size_mb = file_size / (1024 * 1024)
                            if not self._show_large_file_warning(f"PDF file is {size_mb:.1f} MB"):
                                self.attached_file_path = None
                                self.btn_attach.set_label("Attach File")
                                return
                        files.append({
                            "path": self.attached_file_path,
                            "mime_type": mime_type,
                            "display_name": filename,
                        })
                    else:
                        # For other text-like documents (e.g. .txt, .md), inline the
                        # content into the user message instead of uploading a file.
                        # Warn about large text files (>100KB)
                        if file_size > 100 * 1024:
                            size_kb = file_size / 1024
                            if not self._show_large_file_warning(f"Text file is {size_kb:.0f} KB"):
                                self.attached_file_path = None
                                self.btn_attach.set_label("Attach File")
                                return
                        
                        try:
                            with open(self.attached_file_path, "r", encoding="utf-8", errors="ignore") as f:
                                file_text = f.read()
                        except Exception as read_err:
                            print(f"Error reading text document: {read_err}")
                            self.show_error_dialog(f"Error reading file: {filename}")
                            self.attached_file_path = None
                            self.btn_attach.set_label("Attach File")
                            return

                        # Optionally truncate very large text files to avoid extremely
                        # long prompts. Here we cap at ~100k characters.
                        max_chars = 100_000
                        if len(file_text) > max_chars:
                            file_text = file_text[:max_chars] + "\n\n[File content truncated]"

                        header = f"[File content from {filename}]\n"
                        if question:
                            question = question + "\n\n" + header + file_text
                        else:
                            question = header + file_text
                    
                # Show attachment marker in display (without file content)
                display_text = (original_question + f"\n[Attached: {filename}]") if original_question else f"[Attached: {filename}]"
                
                # Reset attachment
                self.attached_file_path = None
                self.btn_attach.set_label("Attach File")
                
            except Exception as e:
                print(f"Error processing file: {e}")
                display_text = question + f"\n[Error attaching file]"

        msg_index = len(self.conversation_history)
        
        # Apply formatting (Markdown preprocessing like code blocks/tables) to the user message
        # just like we do for AI responses, so that code blocks render correctly.
        formatted_display_text = format_response(display_text)
        
        self.append_message('user', formatted_display_text, msg_index)
        
        # Store user message in the chat history
        user_msg = create_user_message(
            question,
            images=images if images else None,
            files=files if files else None,
        )
            
        self.conversation_history.append(user_msg)
        
        # Assign a chat ID if none exists
        if self.current_chat_id is None:
            # New chat - generate name and save
            chat_name = generate_chat_name(self.conversation_history[1]['content'])
            self.current_chat_id = chat_name

        # Clear the question input
        self.entry_question.set_text("")
        
        # Show thinking animation before API call
        self.emit_thinking_started(target_model)
        
        # Call provider API in a separate thread
        threading.Thread(
            target=self.call_ai_api,
            args=(target_model,),
            daemon=True
        ).start()

    def call_ai_api(self, model):
        try:
            # Check if cancelled at start
            if hasattr(self, 'request_cancelled') and self.request_cancelled:
                return
            
            # Ensure we have a valid model
            if not model:
                model = "gpt-3.5-turbo"  # Default fallback
                print(f"No model selected, falling back to {model}")
            provider_name = self.get_provider_name_for_model(model)
            provider = None
            
            # Check if cancelled after initial setup
            if hasattr(self, 'request_cancelled') and self.request_cancelled:
                return

            if provider_name == "custom":
                # Custom providers are keyed per model ID
                provider = self.custom_providers.get(model)
                if not provider:
                    config = (self.custom_models or {}).get(model, {})
                    if not config:
                        raise ValueError(f"Custom model '{model}' is not configured")
                    provider = get_ai_provider("custom")
                    from utils import resolve_api_key
                    provider.initialize(
                        api_key=resolve_api_key(config.get("api_key", "")).strip(),
                        endpoint=config.get("endpoint"),
                        model_name=config.get("model_name") or model,
                        api_type=config.get("api_type") or "chat.completions",
                        voice=config.get("voice"),
                    )
                    self.custom_providers[model] = provider
            else:
                # Get provider via controller
                provider = self.controller.get_provider(provider_name)
                if not provider:
                    raise ValueError(f"{provider_name.title()} provider is not initialized")
            
            model_temperature = self._get_temperature_for_model(model)
            
            # This will hold any provider-specific metadata for the assistant message
            assistant_provider_meta = None

            last_msg = self.conversation_history[-1]
            prompt = last_msg.get("content", "")
            has_attached_images = "images" in last_msg and last_msg["images"]
            has_attached_files = "files" in last_msg and last_msg["files"]

            # Check if files are attached to a non-OpenAI provider
            if has_attached_files and provider_name != 'openai':
                # Show a warning that document analysis requires OpenAI
                warning_msg = (
                    f"Document attachments are currently only supported with OpenAI models. "
                    f"The attached document(s) will be ignored when using {provider_name.title()} models."
                )
                print(f"[ChatGTK] Warning: {warning_msg}")
                # We continue with the request but without the files

            # Route image models through a shared helper so that both manual model
            # selection and tool-based invocations use the same behavior.
            if self._is_image_model_for_provider(model, provider_name):
                answer = self.generate_image_for_model(
                    model=model,
                    prompt=prompt,
                    last_msg=last_msg,
                    chat_id=self.current_chat_id or "temp",
                    provider_name=provider_name,
                    has_attached_images=has_attached_images,
                )
            elif provider_name == 'openai':
                # Check if this is a realtime model via card
                card = get_card(model, self.custom_models)
                is_realtime = card.api_family == "realtime" if card else False
                if is_realtime:
                    # Realtime models are handled elsewhere (WebSocket provider).
                    return
                
                messages_to_send = self._messages_for_model(model)

                # Provide handlers so OpenAI models can call tools (image/music/read_aloud)
                # autonomously when they decide it is helpful.
                last_user_msg = last_msg

                image_tool_handler = None
                music_tool_handler = None
                read_aloud_tool_handler = None
                search_tool_handler = None

                if self._supports_image_tools(model):
                    def image_tool_handler(prompt_arg, image_path=None):
                        return self.generate_image_via_preferred_model(prompt_arg, last_user_msg, image_path)

                if self._supports_music_tools(model):
                    def music_tool_handler(action, keyword=None, volume=None):
                        return self.control_music_via_beets(action, keyword=keyword, volume=volume)

                if self._supports_read_aloud_tools(model):
                    def read_aloud_tool_handler(text):
                        return self._handle_read_aloud_tool(text)

                if self._supports_search_tools(model):
                    def search_tool_handler(keyword, source=None):
                        return self._handle_search_memory_tool(keyword, source)
                    print(f"[ChatGTK] Search tool handler created for model {model}")

                kwargs = {
                    "messages": messages_to_send,
                    "model": model,
                    "temperature": model_temperature,
                    "max_tokens": self.max_tokens if self.max_tokens > 0 else None,
                    "chat_id": self.current_chat_id,
                    "web_search_enabled": bool(getattr(self, "web_search_enabled", False)),
                }
                if image_tool_handler is not None:
                    kwargs["image_tool_handler"] = image_tool_handler
                if music_tool_handler is not None:
                    kwargs["music_tool_handler"] = music_tool_handler
                if read_aloud_tool_handler is not None:
                    kwargs["read_aloud_tool_handler"] = read_aloud_tool_handler
                if search_tool_handler is not None:
                    kwargs["search_tool_handler"] = search_tool_handler
                print(f"[ChatGTK] Tool handlers in kwargs: {[k for k in kwargs if 'handler' in k]}")

                answer = provider.generate_chat_completion(**kwargs)
            elif provider_name == 'custom':
                messages_to_send = self._messages_for_model(model)

                last_user_msg = last_msg

                image_tool_handler = None
                music_tool_handler = None
                read_aloud_tool_handler = None
                search_tool_handler = None

                if self._supports_image_tools(model):
                    def image_tool_handler(prompt_arg, image_path=None):
                        return self.generate_image_via_preferred_model(prompt_arg, last_user_msg, image_path)

                if self._supports_music_tools(model):
                    def music_tool_handler(action, keyword=None, volume=None):
                        return self.control_music_via_beets(action, keyword=keyword, volume=volume)

                if self._supports_read_aloud_tools(model):
                    def read_aloud_tool_handler(text):
                        return self._handle_read_aloud_tool(text)

                if self._supports_search_tools(model):
                    def search_tool_handler(keyword, source=None):
                        return self._handle_search_memory_tool(keyword, source)

                kwargs = {
                    "messages": messages_to_send,
                    "model": model,
                    "temperature": model_temperature,
                    "max_tokens": self.max_tokens if self.max_tokens > 0 else None,
                    "chat_id": self.current_chat_id,
                    "web_search_enabled": bool(getattr(self, "web_search_enabled", False)),
                }
                if image_tool_handler is not None:
                    kwargs["image_tool_handler"] = image_tool_handler
                if music_tool_handler is not None:
                    kwargs["music_tool_handler"] = music_tool_handler
                if read_aloud_tool_handler is not None:
                    kwargs["read_aloud_tool_handler"] = read_aloud_tool_handler
                if search_tool_handler is not None:
                    kwargs["search_tool_handler"] = search_tool_handler

                answer = provider.generate_chat_completion(**kwargs)
            elif provider_name == 'gemini':
                # Chat completion (possibly with image input or tool-based image generation)
                messages_to_send = self._messages_for_model(model)
                response_meta = {}

                last_user_msg = last_msg

                image_tool_handler = None
                music_tool_handler = None
                read_aloud_tool_handler = None
                search_tool_handler = None

                if self._supports_image_tools(model):
                    def image_tool_handler(prompt_arg, image_path=None):
                        return self.generate_image_via_preferred_model(prompt_arg, last_user_msg, image_path)

                if self._supports_music_tools(model):
                    def music_tool_handler(action, keyword=None, volume=None):
                        return self.control_music_via_beets(action, keyword=keyword, volume=volume)

                if self._supports_read_aloud_tools(model):
                    def read_aloud_tool_handler(text):
                        return self._handle_read_aloud_tool(text)

                if self._supports_search_tools(model):
                    def search_tool_handler(keyword, source=None):
                        return self._handle_search_memory_tool(keyword, source)

                kwargs = {
                    "messages": messages_to_send,
                    "model": model,
                    "temperature": model_temperature,
                    "max_tokens": self.max_tokens if self.max_tokens > 0 else None,
                    "chat_id": self.current_chat_id,
                    "response_meta": response_meta,
                    "web_search_enabled": bool(getattr(self, "web_search_enabled", False)),
                }
                if image_tool_handler is not None:
                    kwargs["image_tool_handler"] = image_tool_handler
                if music_tool_handler is not None:
                    kwargs["music_tool_handler"] = music_tool_handler
                if read_aloud_tool_handler is not None:
                    kwargs["read_aloud_tool_handler"] = read_aloud_tool_handler
                if search_tool_handler is not None:
                    kwargs["search_tool_handler"] = search_tool_handler

                answer = provider.generate_chat_completion(**kwargs)

                assistant_provider_meta = response_meta or None
            elif provider_name == 'grok':
                # Standard chat completion for Grok, optionally with tools.
                messages_to_send = self._messages_for_model(model)

                last_user_msg = last_msg

                image_tool_handler = None
                music_tool_handler = None
                read_aloud_tool_handler = None
                search_tool_handler = None

                if self._supports_image_tools(model):
                    def image_tool_handler(prompt_arg, image_path=None):
                        return self.generate_image_via_preferred_model(prompt_arg, last_user_msg, image_path)

                if self._supports_music_tools(model):
                    def music_tool_handler(action, keyword=None, volume=None):
                        return self.control_music_via_beets(action, keyword=keyword, volume=volume)

                if self._supports_read_aloud_tools(model):
                    def read_aloud_tool_handler(text):
                        return self._handle_read_aloud_tool(text)

                if self._supports_search_tools(model):
                    def search_tool_handler(keyword, source=None):
                        return self._handle_search_memory_tool(keyword, source)

                kwargs = {
                    "messages": messages_to_send,
                    "model": model,
                    "temperature": model_temperature,
                    "max_tokens": self.max_tokens if self.max_tokens > 0 else None,
                    "chat_id": self.current_chat_id,
                    "web_search_enabled": bool(getattr(self, "web_search_enabled", False)),
                }
                if image_tool_handler is not None:
                    kwargs["image_tool_handler"] = image_tool_handler
                if music_tool_handler is not None:
                    kwargs["music_tool_handler"] = music_tool_handler
                if read_aloud_tool_handler is not None:
                    kwargs["read_aloud_tool_handler"] = read_aloud_tool_handler
                if search_tool_handler is not None:
                    kwargs["search_tool_handler"] = search_tool_handler

                answer = provider.generate_chat_completion(**kwargs)
            elif provider_name == 'claude':
                # Standard chat completion for Claude, optionally with tools,
                # using the OpenAI SDK compatibility layer:
                # `https://platform.claude.com/docs/en/api/openai-sdk`
                messages_to_send = self._messages_for_model(model)

                last_user_msg = last_msg

                image_tool_handler = None
                music_tool_handler = None
                read_aloud_tool_handler = None
                search_tool_handler = None

                if self._supports_image_tools(model):
                    def image_tool_handler(prompt_arg, image_path=None):
                        return self.generate_image_via_preferred_model(prompt_arg, last_user_msg, image_path)

                if self._supports_music_tools(model):
                    def music_tool_handler(action, keyword=None, volume=None):
                        return self.control_music_via_beets(action, keyword=keyword, volume=volume)

                if self._supports_read_aloud_tools(model):
                    def read_aloud_tool_handler(text):
                        return self._handle_read_aloud_tool(text)

                if self._supports_search_tools(model):
                    def search_tool_handler(keyword, source=None):
                        return self._handle_search_memory_tool(keyword, source)

                kwargs = {
                    "messages": messages_to_send,
                    "model": model,
                    "temperature": model_temperature,
                    "max_tokens": self.max_tokens if self.max_tokens > 0 else None,
                    "chat_id": self.current_chat_id,
                    "response_meta": assistant_provider_meta,
                    "web_search_enabled": bool(getattr(self, "web_search_enabled", False)),
                }
                if image_tool_handler is not None:
                    kwargs["image_tool_handler"] = image_tool_handler
                if music_tool_handler is not None:
                    kwargs["music_tool_handler"] = music_tool_handler
                if read_aloud_tool_handler is not None:
                    kwargs["read_aloud_tool_handler"] = read_aloud_tool_handler
                if search_tool_handler is not None:
                    kwargs["search_tool_handler"] = search_tool_handler

                answer = provider.generate_chat_completion(**kwargs)
            elif provider_name == 'perplexity':
                # Chat completion for Perplexity Sonar models.
                # Perplexity models have built-in web search and don't support
                # function tools in the same way as other providers.
                # See https://docs.perplexity.ai/guides/chat-completions-guide
                messages_to_send = self._messages_for_model(model)

                # This will collect provider-specific metadata such as web
                # search results so we can persist them with the message.
                response_meta = {}

                # Perplexity requires strict alternation between user and assistant
                # messages after the system message. Clean the messages to ensure
                # proper format.
                messages_to_send = self._clean_messages_for_perplexity(messages_to_send)

                kwargs = {
                    "messages": messages_to_send,
                    "model": model,
                    "temperature": model_temperature,
                    "max_tokens": self.max_tokens if self.max_tokens > 0 else None,
                    "chat_id": self.current_chat_id,
                    "response_meta": response_meta,
                }

                answer = provider.generate_chat_completion(**kwargs)
                assistant_provider_meta = response_meta or None

                # If Perplexity returned web search results, append a human-readable
                # "Sources" section to the answer so users can see and click them.
                perplexity_meta = (response_meta or {}).get("perplexity", {})
                search_results = perplexity_meta.get("search_results") if isinstance(perplexity_meta, dict) else None
                if search_results:
                    lines = []
                    for idx, res in enumerate(search_results, start=1):
                        title = res.get("title") or "Source"
                        url = res.get("url") or ""
                        date = res.get("date") or ""

                        line = f"{idx}. {title}"
                        if date:
                            line += f" ({date})"
                        if url:
                            line += f" — {url}"
                        lines.append(line)

                    if lines:
                        suffix = "Sources:\n" + "\n".join(lines)
                        # Keep a blank line between the model answer and the sources block.
                        answer = (answer.rstrip() + "\n\n" + suffix).rstrip()
            else:
                raise ValueError(f"Unsupported provider: {provider_name}")

            # Check if cancelled before processing result
            if hasattr(self, 'request_cancelled') and self.request_cancelled:
                return
            
            # Normalize any raw <img ...> tags so the UI can render them
            # consistently without showing stray HTML.
            answer = self._normalize_image_tags(answer)

            assistant_message = create_assistant_message(answer, provider_meta=assistant_provider_meta)
            message_index = len(self.conversation_history)
            self.conversation_history.append(assistant_message)

            # Update UI in main thread
            formatted_answer = format_response(answer)
            GLib.idle_add(self.emit_thinking_stopped)
            GLib.idle_add(lambda idx=message_index, msg=formatted_answer: self.append_message('ai', msg, idx))
            GLib.idle_add(self.save_current_chat)
            
            # Read aloud the response if enabled (runs in background thread)
            # Skip for audio models since they already play audio directly
            card = get_card(model, self.custom_models)
            is_audio_model = card.capabilities.audio_out if card else False
            if not is_audio_model:
                self.read_aloud_text(formatted_answer, chat_id=self.current_chat_id)
            
        except Exception as error:
            # Only show error if not cancelled
            if not (hasattr(self, 'request_cancelled') and self.request_cancelled):
                print(f"\nAPI Call Error: {error}")
                GLib.idle_add(self.emit_thinking_stopped)
                error_message = f"** Error: {str(error)} **"
                message_index = len(self.conversation_history)
                self.conversation_history.append(create_assistant_message(error_message))
                GLib.idle_add(lambda idx=message_index, msg=error_message: self.append_message('ai', msg, idx))
            
        finally:
            GLib.idle_add(self.emit_thinking_stopped)

    def audio_transcription(self, widget):
        """Handle audio transcription."""
        print("Audio transcription...")
        stt_model = getattr(self, "speech_to_text_model", "") or "whisper-1"
        stt_base_url = None
        stt_api_key = None
        try:
            card = get_card(stt_model, self.custom_models)
            if card:
                stt_base_url = card.base_url or None
                # Try to resolve a key for custom models
                if card.provider == "custom":
                    cfg = (self.custom_models or {}).get(stt_model, {})
                    if cfg:
                        from utils import resolve_api_key
                        stt_api_key = resolve_api_key(cfg.get("api_key", ""))
                elif card.key_name:
                    stt_api_key = self.api_keys.get(card.key_name) or stt_api_key
        except Exception as e:
            print(f"[Audio STT] Error reading card for {stt_model}: {e}")
        
        # Get OpenAI provider via controller
        openai_provider = self.controller.get_provider('openai')
        if not openai_provider:
            self.show_error_dialog("Audio transcription requires an OpenAI API key")
            return
        
        if not self.recording:
            try:
                # Create an Event for controlling recording
                self.recording_event = threading.Event()
                self.recording_event.set()  # Start recording
                self.recording = True
                self.btn_voice.set_label("Recording... Click to Stop")
                print("Recording started")
                
                def record_thread():
                    try:
                        # Record audio using AudioService
                        audio_service = self.controller.audio_service
                        recording, sample_rate = audio_service.record_audio(
                            self.microphone, self.recording_event
                        )
                        
                        if recording is not None and sample_rate is not None:
                            try:
                                # Save recording
                                temp_file = audio_service.save_recording(recording, sample_rate)
                                
                                # Transcribe with selected model (fallback to whisper-1)
                                transcript = None
                                models_to_try = [stt_model]
                                if "whisper-1" not in models_to_try:
                                    models_to_try.append("whisper-1")

                                for model in models_to_try:
                                    transcript = audio_service.transcribe(
                                        temp_file, openai_provider,
                                        model=model,
                                        base_url=stt_base_url,
                                        api_key=stt_api_key,
                                    )
                                    if transcript:
                                        print(f"[Audio STT] Transcribed with model: {model}")
                                        break
                                    print(f"[Audio STT] Model {model} failed")

                                if transcript:
                                    GLib.idle_add(self.entry_question.set_text, transcript)
                                else:
                                    print("[Audio STT] No transcript produced; keeping input unchanged.")
                            
                            finally:
                                # Clean up temp file
                                temp_file.unlink(missing_ok=True)
                        else:
                            print("[Audio STT] Error: Failed to record audio")
                    
                    except Exception as e:
                        print(f"[Audio STT] Error in recording thread: {e}")
                    
                    finally:
                        # Reset button state
                        GLib.idle_add(self.btn_voice.set_label, "Start Voice Input")
                        self.recording = False
                
                # Start recording in separate thread
                threading.Thread(target=record_thread, daemon=True).start()
                
            except Exception as e:
                err_text = f"Error initializing audio system: {str(e)}"
                msg_index = len(self.conversation_history)
                self.conversation_history.append(create_assistant_message(err_text))
                self.append_message('ai', err_text, msg_index)
                self.btn_voice.set_label("Start Voice Input")
                self.recording = False
        else:
            # Stop recording
            if hasattr(self, 'recording_event'):
                self.recording_event.clear()  # Signal recording to stop
            self.recording = False
            self.btn_voice.set_label("Start Voice Input")

    def _audio_transcription_to_textview(self, textview):
        """Handle audio transcription and insert result into a textview at cursor position."""
        stt_model = getattr(self, "speech_to_text_model", "") or "whisper-1"
        stt_base_url = None
        stt_api_key = None
        try:
            card = get_card(stt_model, self.custom_models)
            if card:
                stt_base_url = card.base_url or None
                if card.provider == "custom":
                    cfg = (self.custom_models or {}).get(stt_model, {})
                    if cfg:
                        from utils import resolve_api_key
                        stt_api_key = resolve_api_key(cfg.get("api_key", ""))
                elif card.key_name:
                    stt_api_key = self.api_keys.get(card.key_name) or stt_api_key
        except Exception as e:
            print(f"[Audio STT] Error reading card for {stt_model}: {e}")

        # Get OpenAI provider via controller
        openai_provider = self.controller.get_provider('openai')
        if not openai_provider:
            self.show_error_dialog("Audio transcription requires an OpenAI API key")
            return

        # Get the dialog to update recording state
        dialog = textview.get_toplevel()

        if not self.recording:
            try:
                self.recording_event = threading.Event()
                self.recording_event.set()
                self.recording = True
                if hasattr(dialog, 'set_recording_state'):
                    dialog.set_recording_state(True)
                print("Recording started for prompt editor")

                def record_thread():
                    try:
                        # Record audio using AudioService
                        audio_service = self.controller.audio_service
                        recording, sample_rate = audio_service.record_audio(
                            self.microphone, self.recording_event
                        )

                        if recording is not None and sample_rate is not None:
                            try:
                                temp_file = audio_service.save_recording(recording, sample_rate)

                                transcript = None
                                models_to_try = [stt_model]
                                if "whisper-1" not in models_to_try:
                                    models_to_try.append("whisper-1")

                                for model in models_to_try:
                                    transcript = audio_service.transcribe(
                                        temp_file, openai_provider,
                                        model=model,
                                        base_url=stt_base_url,
                                        api_key=stt_api_key,
                                    )
                                    if transcript:
                                        print(f"[Audio STT] Transcribed with model: {model}")
                                        break
                                    print(f"[Audio STT] Model {model} failed")

                                if transcript:
                                    def insert_transcript():
                                        buf = textview.get_buffer()
                                        buf.insert_at_cursor(transcript)
                                    GLib.idle_add(insert_transcript)
                                else:
                                    print("[Audio STT] No transcript produced.")
                            finally:
                                temp_file.unlink(missing_ok=True)
                        else:
                            print("[Audio STT] Error: Failed to record audio")
                    except Exception as e:
                        print(f"[Audio STT] Error in recording thread: {e}")
                    finally:
                        def reset_state():
                            if hasattr(dialog, 'set_recording_state'):
                                dialog.set_recording_state(False)
                        GLib.idle_add(reset_state)
                        self.recording = False

                threading.Thread(target=record_thread, daemon=True).start()

            except Exception as e:
                print(f"Error initializing audio for prompt editor: {e}")
                self.show_error_dialog(f"Error initializing audio: {str(e)}")
                if hasattr(dialog, 'set_recording_state'):
                    dialog.set_recording_state(False)
                self.recording = False
        else:
            # Stop recording
            if hasattr(self, 'recording_event'):
                self.recording_event.clear()
            self.recording = False
            if hasattr(dialog, 'set_recording_state'):
                dialog.set_recording_state(False)

    def on_attach_file(self, widget):
        """Handle file attachment."""
        dialog = Gtk.FileChooserDialog(
            title="Please choose a file",
            parent=self,
            action=Gtk.FileChooserAction.OPEN
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN, Gtk.ResponseType.OK
        )

        # Add filters - order: All files, Documents (new feature), Images
        filter_any = Gtk.FileFilter()
        filter_any.set_name("All supported files")
        filter_any.add_pattern("*")
        dialog.add_filter(filter_any)

        # Add filter for documents (text, PDF, markdown, etc.)
        filter_docs = Gtk.FileFilter()
        filter_docs.set_name("Documents (PDF, TXT, MD, CSV, JSON)")
        filter_docs.add_mime_type("application/pdf")
        filter_docs.add_mime_type("text/plain")
        filter_docs.add_mime_type("text/markdown")
        filter_docs.add_mime_type("text/x-markdown")
        filter_docs.add_mime_type("text/csv")
        filter_docs.add_mime_type("application/json")
        filter_docs.add_mime_type("text/html")
        filter_docs.add_mime_type("application/xml")
        filter_docs.add_mime_type("text/xml")
        filter_docs.add_pattern("*.txt")
        filter_docs.add_pattern("*.md")
        filter_docs.add_pattern("*.pdf")
        filter_docs.add_pattern("*.csv")
        filter_docs.add_pattern("*.json")
        filter_docs.add_pattern("*.html")
        filter_docs.add_pattern("*.xml")
        dialog.add_filter(filter_docs)
        
        filter_image = Gtk.FileFilter()
        filter_image.set_name("Images")
        filter_image.add_mime_type("image/*")
        dialog.add_filter(filter_image)

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            filepath = dialog.get_filename()
            dialog.destroy()
            
            # Check file size and warn for large files
            try:
                size = os.path.getsize(filepath)
                mime_type, _ = mimetypes.guess_type(filepath)
                is_pdf = mime_type == "application/pdf"
                
                # Warn for PDFs > 1MB or text files > 100KB
                if (is_pdf and size > 1_000_000) or (not is_pdf and size > 100_000):
                    size_str = f"{size / 1_000_000:.1f}MB" if size > 1_000_000 else f"{size / 1000:.0f}KB"
                    if not self._show_large_file_warning(f"File is {size_str}"):
                        return
            except OSError:
                pass
            
            self.attached_file_path = filepath
            filename = os.path.basename(filepath)
            self.btn_attach.set_label(f"Attached: {filename}")
            print(f"File selected: {self.attached_file_path}")
            return
        
        dialog.destroy()

    def on_voice_input(self, widget):
        current_model = self._get_model_id_from_combo()

        if current_model is None or current_model == "":
            self.show_error_dialog("Please select a model before using voice input")
            return False
        
        model_temperature = self._get_temperature_for_model(current_model)

        if "realtime" not in current_model.lower():
            # Call function for normal transcription
            self.audio_transcription(widget)

        else:
            # Start real-time audio streaming
            print("Starting real-time audio streaming...\n")
            
            if not self.recording:
                try:
                    # Check if audio system is available
                    sd.check_output_settings()
                    
                    # Initialize WebSocket provider if needed
                    if not hasattr(self, 'ws_provider'):
                        self.ws_provider = OpenAIWebSocketProvider(callback_scheduler=GLib.idle_add)
                        self.ws_provider.microphone = self.microphone  # Pass selected microphone
                        self.ws_provider.on_user_transcript = self._on_realtime_user_transcript
                        self.ws_provider.on_assistant_transcript = self._on_realtime_assistant_transcript
                
                    # Connect to WebSocket before starting stream
                    api_key = os.environ.get('OPENAI_API_KEY', self.api_keys.get('openai', '')).strip()
                    if not api_key:
                        self.show_error_dialog("Please enter your OpenAI API key")
                        return False
                    os.environ['OPENAI_API_KEY'] = api_key
                    self.initialize_provider('openai', api_key)

                    # Connect with the current model
                    if not self.ws_provider.connect(
                        model=current_model,
                        system_message=self.system_message,
                        temperature=model_temperature,
                        voice=self.realtime_voice,
                        mute_mic_during_playback=bool(getattr(self, "mute_mic_during_playback", True)),
                        realtime_prompt=self._get_realtime_prompt(),
                        api_key=api_key
                    ):
                        self.show_error_dialog("Failed to connect to OpenAI realtime service")
                        return False

                    # Start recording
                    self.recording = True
                    self.btn_voice.set_label("Recording... Click to Stop")
                    
                    self.ws_provider.start_streaming(
                        callback=self.on_stream_content_received,
                        microphone=self.microphone,
                        system_message=self.system_message,
                        temperature=model_temperature,
                        mute_mic_during_playback=bool(getattr(self, "mute_mic_during_playback", True)),
                        realtime_prompt=self._get_realtime_prompt(),
                        api_key=api_key
                    )
                    
                except Exception as e:
                    print(f"Real-time streaming error: {e}")
                    err_text = f"Error starting real-time streaming: {str(e)}"
                    msg_index = len(self.conversation_history)
                    self.conversation_history.append(create_assistant_message(err_text))
                    self.append_message('ai', err_text, msg_index)
                    self.btn_voice.set_label("Start Voice Input")
                    self.recording = False
            else:
                # Stop recording
                print("Stopping real-time streaming...")
                if hasattr(self, 'ws_provider'):
                    self.ws_provider.stop_streaming()
                    delattr(self, 'ws_provider')  # Clean up the provider
                self.recording = False
                self.btn_voice.set_label("Start Voice Input")
                return False  # Prevent signal propagation

    def on_delete_chat(self, widget, history_row):
        """Delete the selected chat history."""
        filename = history_row.filename
        
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Delete Chat",
        )
        dialog.format_secondary_text("Are you sure you want to delete this chat history?")
        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.YES:
            # If we are deleting the currently active chat, clear the display first
            if self.current_chat_id == filename:
                # Clear the display
                for child in self.conversation_box.get_children():
                    child.destroy()
                self.message_widgets.clear()
                
                # Reset conversation state
                self.conversation_history = [create_system_message(self.system_message)]
                self.current_chat_id = None

            # Delete the chat history via controller
            self.controller.delete_chat(filename)
            
            # Refresh the history list
            self.refresh_history_list()


    def on_sidebar_toggle(self, button):
        """Toggle sidebar visibility."""
        if self.sidebar_visible:
            self.sidebar.hide()
            arrow = Gtk.Arrow(arrow_type=Gtk.ArrowType.RIGHT, shadow_type=Gtk.ShadowType.NONE)
        else:
            self.sidebar.show()
            # Restore the paned position to the saved sidebar width
            self.paned.set_position(self.current_sidebar_width)
            # Reload the current conversation to force reflow with new width
            # Use idle_add to ensure this happens after the paned has allocated space
            GLib.idle_add(self._reload_current_conversation)
            arrow = Gtk.Arrow(arrow_type=Gtk.ArrowType.LEFT, shadow_type=Gtk.ShadowType.NONE)
        
        # Update button arrow
        old_arrow = button.get_child()
        button.remove(old_arrow)
        button.add(arrow)
        button.show_all()
        
        self.sidebar_visible = not self.sidebar_visible
    
    def _reload_current_conversation(self):
        """Reload the current conversation to force widgets to recalculate with new width."""
        if not self.conversation_history or len(self.conversation_history) <= 1:
            # No conversation to reload (only system message)
            return False
        
        # Save current scroll position
        scrolled_window = None
        widget = self.conversation_box
        while widget and not isinstance(widget, Gtk.ScrolledWindow):
            widget = widget.get_parent()
        if widget:
            scrolled_window = widget
            adj = scrolled_window.get_vadjustment()
            scroll_position = adj.get_value() if adj else 0
        else:
            scroll_position = 0
        
        # Clear the conversation display
        for child in self.conversation_box.get_children():
            child.destroy()
        self.message_widgets.clear()
        
        # Rebuild conversation display with formatting
        for idx, message in enumerate(self.conversation_history):
            if message['role'] != 'system':  # Skip system message
                message_index = idx
                if message['role'] == 'user':
                    self.append_message('user', message['content'], message_index)
                elif message['role'] == 'assistant':
                    formatted_content = format_response(message['content'])
                    self.append_message('ai', formatted_content, message_index)
        
        # Restore scroll position
        if scrolled_window and scroll_position > 0:
            def restore_scroll():
                adj = scrolled_window.get_vadjustment()
                if adj:
                    adj.set_value(scroll_position)
                return False
            GLib.idle_add(restore_scroll)
        
        return False

    def on_new_chat_clicked(self, button):
        """Start a new chat conversation."""
        # Clear conversation history
        self.conversation_history = [create_system_message(self.system_message)]
        
        # Reset chat ID to indicate this is a new chat
        self.current_chat_id = None
        self.history_list.unselect_all()
        
        # Clear pending edit image
        self._clear_pending_edit_image()
        self._edit_buttons.clear()
        
        # Clear the conversation display
        for child in self.conversation_box.get_children():
            child.destroy()
        self.message_widgets.clear()
        
        # Refresh the history list
        self.refresh_history_list()

    def refresh_history_list(self):
        """Refresh the list of chat histories in the sidebar."""
        if hasattr(self, '_history_sidebar'):
            self._history_sidebar.refresh()
        
    def _on_sidebar_context_menu(self, row, event):
        """Handle sidebar context menu request."""
        self.create_history_context_menu(row)

    def get_chat_timestamp(self, filename):
        """Get a formatted timestamp from the filename."""
        try:
            match = re.search(r'_(\d{8}_\d{6})\.json$', filename)
            if match:
                timestamp_str = match.group(1)
                dt = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                return dt.strftime("%Y-%m-%d %H:%M")
        except Exception as e:
            print(f"Error getting timestamp: {e}")
        return "Unknown date"

    def load_chat_by_filename(self, filename, save_current=True):
        """Load a chat history by filename.
        
        Args:
            filename: The chat filename (with or without .json extension)
            save_current: If True, save the current chat before loading (default: True)
        """
        # Save current chat if it's new and has messages
        if save_current and self.current_chat_id is None and len(self.conversation_history) > 1:
            self.save_current_chat()
        
        # Load via controller
        chat_id = filename.replace('.json', '') if filename.endswith('.json') else filename
        if self.controller.load_chat(chat_id):
            # Sync from controller
            history = self.controller.conversation_history
            self.conversation_history = history
            self.current_chat_id = self.controller.current_chat_id
            
            # Save the last active chat to settings
            self.last_active_chat = chat_id
            save_object_settings(self)
            
            # Set the model if it was saved with the chat
            if history and len(history) > 0 and "model" in history[0]:
                saved_model = history[0]["model"]
                model_store = self.combo_model.get_model()
                
                # Find the matching row by comparing resolved model_ids (handles custom display names)
                match_index = None
                for i in range(len(model_store)):
                    display_text = model_store[i][0]
                    model_id = self._display_to_model_id.get(display_text, display_text) if hasattr(self, "_display_to_model_id") else display_text
                    if model_id == saved_model:
                        match_index = i
                        break
                
                if match_index is None:
                    # Conversation references a model not currently in the list (e.g., custom); add it so selection stays in sync
                    display_text = get_model_display_name(saved_model, self.custom_models) or saved_model
                    if not hasattr(self, "_display_to_model_id"):
                        self._display_to_model_id = {}
                    self._display_to_model_id[display_text] = saved_model
                    match_index = len(model_store)
                    self.combo_model.append_text(display_text)
                
                if match_index is not None:
                    self.combo_model.set_active(match_index)
            
            # Sync system prompt selector with the loaded chat's system message
            if history and history[0].get("role") == "system":
                loaded_system_content = history[0].get("content", "")
                self.system_message = loaded_system_content
                # Try to find a matching prompt by content
                matched_id = None
                for p in getattr(self, "system_prompts", []):
                    if p["content"] == loaded_system_content:
                        matched_id = p["id"]
                        break
                if matched_id:
                    self.active_system_prompt_id = matched_id
                    # Update combo without triggering the change handler
                    self.combo_system_prompt.handler_block_by_func(self.on_system_prompt_changed)
                    self.combo_system_prompt.set_active_id(matched_id)
                    self.combo_system_prompt.handler_unblock_by_func(self.on_system_prompt_changed)
            
            # Clear and reload chat display
            for child in self.conversation_box.get_children():
                child.destroy()
            self.message_widgets.clear()
            
            # Clear pending edit image state
            self._clear_pending_edit_image()
            self._edit_buttons.clear()
            
            # Rebuild conversation display with formatting
            for idx, message in enumerate(history):
                if message['role'] != 'system':  # Skip system message
                    message_index = idx
                    if message['role'] == 'user':
                        formatted_content = format_response(message['content'])
                        self.append_message('user', formatted_content, message_index)
                    elif message['role'] == 'assistant':
                        formatted_content = format_response(message['content'])
                        self.append_message('ai', formatted_content, message_index)
            
            # Scroll to the beginning of the conversation
            def scroll_to_top():
                # Find the ScrolledWindow by traversing up the widget hierarchy
                widget = self.conversation_box
                while widget and not isinstance(widget, Gtk.ScrolledWindow):
                    widget = widget.get_parent()
                
                if widget:  # We found the ScrolledWindow
                    adj = widget.get_vadjustment()
                    adj.set_value(0)  # Scroll to the top
                return False  # Don't repeat
            
            # Schedule scroll after the conversation is rebuilt
            GLib.idle_add(scroll_to_top)
            
            # Update history list selection to highlight the loaded chat
            for row in self.history_list.get_children():
                if getattr(row, "filename", None) == filename:
                    self.history_list.select_row(row)
                    break

    def on_history_selected(self, listbox, row):
        """Handle selection of a chat history."""
        self.load_chat_by_filename(row.filename)

    def save_current_chat(self):
        """Save the current chat history via controller."""
        if len(self.conversation_history) > 1:  # More than just the system message
            # Track model in system message
            current_model = self._get_model_id_from_combo()
            has_existing_model = len(self.conversation_history) > 0 and "model" in self.conversation_history[0]
            is_excluded = "dall-e" in current_model.lower() or "tts" in current_model.lower() or "audio" in current_model.lower()
            if not has_existing_model or not is_excluded:
                self.conversation_history[0]["model"] = current_model

            # Sync conversation to controller and save
            self.controller.conversation_history = self.conversation_history
            chat_id = self.controller.save_current_chat()
            
            if chat_id:
                self.current_chat_id = chat_id
                self.last_active_chat = chat_id.replace('.json', '') if chat_id.endswith('.json') else chat_id
                save_object_settings(self)

    def show_thinking_animation(self):
        """Show an animated thinking indicator with loader and cancel button."""
        # Remove any existing thinking animation first
        if hasattr(self, 'thinking_container') and self.thinking_container:
            self.thinking_container.destroy()
            self.thinking_container = None
        
        # Create main container with consistent styling (matching append_ai_message)
        self.thinking_container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        
        # Apply styling similar to message containers
        css_container = f"""
            box {{
                background-color: @theme_base_color;
                padding: 12px;
                border-radius: 12px;
            }}
        """
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(css_container.encode())
        self.thinking_container.get_style_context().add_provider(
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        
        # Create loader widget (animated pulsing dot)
        loader_box = Gtk.Box()
        loader_box.set_size_request(16, 16)
        loader_box.set_valign(Gtk.Align.CENTER)
        
        # Create the loader dot
        self.loader_dot = Gtk.Box()
        self.loader_dot.set_size_request(16, 16)
        hex_color = rgb_to_hex(self.ai_color)
        
        # Initial loader CSS - will be animated (using hex color)
        css_loader = f"""
            box {{
                border-radius: 50%;
                background-color: {hex_color};
                min-width: 16px;
                min-height: 16px;
            }}
        """
        loader_css_provider = Gtk.CssProvider()
        loader_css_provider.load_from_data(css_loader.encode())
        self.loader_dot.get_style_context().add_provider(
            loader_css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        
        loader_box.pack_start(self.loader_dot, False, False, 0)
        self.thinking_container.pack_start(loader_box, False, False, 0)
        
        # Create thinking text label
        self.thinking_label = Gtk.Label()
        self.thinking_label.set_markup(f"<span color='{hex_color}'>{self.ai_name} is thinking</span>")
        self.thinking_label.set_xalign(0)
        self.thinking_container.pack_start(self.thinking_label, True, True, 0)
        
        # Create cancel button using theme colors
        cancel_button = Gtk.Button()
        cancel_button.set_relief(Gtk.ReliefStyle.NONE)
        cancel_button.set_tooltip_text("Cancel request")
        
        # Style cancel button with theme colors
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
            button:active {
                background-color: alpha(@theme_fg_color, 0.2);
            }
        """
        cancel_css_provider = Gtk.CssProvider()
        cancel_css_provider.load_from_data(cancel_css.encode())
        cancel_button.get_style_context().add_provider(
            cancel_css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        
        # Add cancel icon (× symbol)
        cancel_label = Gtk.Label()
        cancel_label.set_markup("<span size='large' weight='bold'>×</span>")
        cancel_button.add(cancel_label)
        
        # Connect cancel button
        self.request_cancelled = False
        def on_cancel_clicked(button):
            self.request_cancelled = True
            self.hide_thinking_animation()
            cancel_text = "** Request cancelled by user **"
            message_index = len(self.conversation_history)
            self.conversation_history.append(create_assistant_message(cancel_text))
            GLib.idle_add(lambda idx=message_index: self.append_message('ai', cancel_text, idx))
        
        cancel_button.connect("clicked", on_cancel_clicked)
        self.thinking_container.pack_start(cancel_button, False, False, 0)
        
        self.conversation_box.pack_start(self.thinking_container, False, False, 0)
        self.conversation_box.show_all()
        
        def scroll_to_bottom():
            # Find the ScrolledWindow by traversing up the widget hierarchy
            widget = self.conversation_box
            while widget and not isinstance(widget, Gtk.ScrolledWindow):
                widget = widget.get_parent()
            
            if widget:  # We found the ScrolledWindow
                adj = widget.get_vadjustment()
                adj.set_value(adj.get_upper() - adj.get_page_size())
            return False  # Don't repeat
        
        # Schedule scroll after the thinking label is shown
        GLib.idle_add(scroll_to_bottom)
        
        # Animation state
        self.thinking_dots = 0
        self.loader_animation_state = 0  # 0, 1, 2 for the three animation states
        self.loader_opacity = [1.0, 0.4, 1.0]  # Opacity values for pulsing effect
        
        def update_animation():
            if not hasattr(self, 'thinking_container') or not self.thinking_container:
                return False
            
            # Update loader animation (pulsing opacity effect)
            # Cycle through opacity states to create a pulsing effect
            opacity = self.loader_opacity[self.loader_animation_state]
            # Use GTK's opacity property directly (more reliable than CSS rgba)
            if hasattr(self, 'loader_dot') and self.loader_dot:
                self.loader_dot.set_opacity(opacity)
            
            self.loader_animation_state = (self.loader_animation_state + 1) % 3
            
            # Update dots in text
            if hasattr(self, 'thinking_label') and self.thinking_label:
                self.thinking_dots = (self.thinking_dots + 1) % 4
                dots = "." * self.thinking_dots
                self.thinking_label.set_markup(
                    f"<span color='{hex_color}'>{self.ai_name} is thinking{dots}</span>"
                )
            
            return True  # Continue animation
        
        # Update every ~667ms (2s / 3 states) for smooth animation
        self.thinking_timer = GLib.timeout_add(667, update_animation)

    def hide_thinking_animation(self):
        """Remove the thinking animation."""
        # Reset cancellation flag
        if hasattr(self, 'request_cancelled'):
            self.request_cancelled = False
        
        # Remove timer if it exists
        if hasattr(self, 'thinking_timer') and self.thinking_timer is not None:
            try:
                GLib.source_remove(self.thinking_timer)
            except:
                pass
        self.thinking_timer = None
        
        # Remove the container (which includes label, loader, and cancel button)
        if hasattr(self, 'thinking_container') and self.thinking_container:
            self.thinking_container.destroy()
            self.thinking_container = None
        
        # Clean up individual components (for safety)
        if hasattr(self, 'thinking_label') and self.thinking_label:
            self.thinking_label = None
        if hasattr(self, 'loader_dot') and self.loader_dot:
            self.loader_dot = None

    def create_message_context_menu(self, widget, message_index, event=None):
        """Create a context menu for an individual message."""
        menu = Gtk.Menu()

        delete_item = Gtk.MenuItem(label="Delete Message")
        delete_item.connect("activate", self.on_delete_message, message_index)
        menu.append(delete_item)

        menu.show_all()
        if event:
            menu.popup_at_pointer(event)
        else:
            menu.popup_at_pointer(None)

    def delete_message(self, message_index: int):
        """Delete a message from UI and history (excluding system message)."""
        if message_index <= 0 or message_index >= len(self.conversation_history):
            return

        widget_idx = message_index - 1  # message_widgets excludes system message
        if widget_idx < 0 or widget_idx >= len(self.message_widgets):
            return

        widget = self.message_widgets.pop(widget_idx)
        try:
            widget.destroy()
        except Exception:
            pass

        try:
            del self.conversation_history[message_index]
        except Exception:
            return

        # Reassign message_index for remaining widgets
        for idx, child in enumerate(self.message_widgets[widget_idx:], start=widget_idx):
            try:
                child.message_index = idx + 1  # offset for system message
            except Exception:
                pass

        if self.current_chat_id is not None:
            self.save_current_chat()

    def on_delete_message(self, _menu_item, message_index: int):
        """Menu callback to delete a message."""
        self.delete_message(message_index)

    def create_history_context_menu(self, history_row):
        """Create a context menu for chat history items."""
        menu = Gtk.Menu()
        
        # Rename option
        rename_item = Gtk.MenuItem(label="Rename Chat")
        rename_item.connect("activate", self.on_rename_chat, history_row)
        menu.append(rename_item)
        
        # Export to PDF option
        export_item = Gtk.MenuItem(label="Export to PDF")
        export_item.connect("activate", self.on_export_chat, history_row)
        menu.append(export_item)
        
        # Delete option
        delete_item = Gtk.MenuItem(label="Delete Chat")
        delete_item.connect("activate", self.on_delete_chat, history_row)
        menu.append(delete_item)
        
        menu.show_all()
        menu.popup_at_pointer(None)

    def on_rename_chat(self, widget, history_row):
        """Handle rename chat action."""
        dialog = Gtk.Dialog(title="Rename Chat", parent=self, flags=0)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Rename", Gtk.ResponseType.OK)
        
        # Add entry for new name
        box = dialog.get_content_area()
        box.set_spacing(6)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        
        entry = Gtk.Entry()
        entry.set_text(history_row.get_children()[0].get_children()[0].get_text().replace("You: ", ""))
        entry.set_activates_default(True)
        box.add(entry)
        
        # Make the OK button the default
        dialog.set_default_response(Gtk.ResponseType.OK)
        
        dialog.show_all()
        response = dialog.run()
        
        if response == Gtk.ResponseType.OK:
            new_name = entry.get_text().strip()
            if new_name:
                # Set the custom title via utils function
                from utils import set_chat_title
                chat_id = history_row.filename.replace('.json', '') if history_row.filename.endswith('.json') else history_row.filename
                set_chat_title(chat_id, new_name)
                # Refresh sidebar to show new title
                self.refresh_history_list()
        
        dialog.destroy()

    def on_export_chat(self, widget, history_row):
        """Handle export to PDF action."""
        # Prefer the system-native file chooser when available, fall back to Gtk.FileChooserDialog.
        if hasattr(Gtk, "FileChooserNative"):
            dialog = Gtk.FileChooserNative(
                title="Export Chat to PDF",
                transient_for=self,
                action=Gtk.FileChooserAction.SAVE,
                accept_label="Save",
                cancel_label="Cancel",
            )
        else:
            dialog = Gtk.FileChooserDialog(
                title="Export Chat to PDF",
                parent=self,
                action=Gtk.FileChooserAction.SAVE,
            )
            dialog.add_buttons(
                "Cancel", Gtk.ResponseType.CANCEL,
                "Save", Gtk.ResponseType.OK,
            )
        
        try:
            # Add PDF file filter
            pdf_filter = Gtk.FileFilter()
            pdf_filter.set_name("PDF files")
            pdf_filter.add_pattern("*.pdf")
            dialog.add_filter(pdf_filter)
            
            # Set default filename from the chat history
            default_name = f"chat_{history_row.filename.replace('.json', '.pdf')}"
            dialog.set_current_name(default_name)
            
            # Show the dialog
            response = dialog.run()
            
            # Gtk.FileChooserNative returns ACCEPT, Gtk.FileChooserDialog returns OK
            if response in (Gtk.ResponseType.OK, Gtk.ResponseType.ACCEPT):
                filename = dialog.get_filename()
                if not filename.endswith('.pdf'):
                    filename += '.pdf'
                    
                # Load the chat history via chat service
                chat_id = history_row.filename.replace('.json', '') if history_row.filename.endswith('.json') else history_row.filename
                conv = self.controller.chat_service.load_chat(chat_id)
                history = conv.to_list() if conv and hasattr(conv, 'to_list') else conv
                if history:
                    # Use the sidebar chat title and present it with capitalized words
                    chat_title = get_chat_title(history_row.filename)
                    formatted_title = " ".join(
                        word[:1].upper() + word[1:] if word else ""
                        for word in chat_title.split()
                    )
                    
                    # Get the chat ID from the filename
                    chat_id = history_row.filename
                    
                    try:
                        result = export_chat_to_pdf(history, filename, formatted_title, chat_id)
                        # Handle both old (bool) and new (tuple) return formats for compatibility
                        if isinstance(result, tuple):
                            success, engine_name = result
                        else:
                            success = result
                            engine_name = None
                        
                        if success:
                            info_dialog = Gtk.MessageDialog(
                                transient_for=self,
                                flags=0,
                                message_type=Gtk.MessageType.INFO,
                                buttons=Gtk.ButtonsType.OK,
                                text="Export Successful"
                            )
                            info_dialog.format_secondary_text(f"Chat exported to {filename}")
                            info_dialog.run()
                            info_dialog.destroy()
                        else:
                            error_dialog = Gtk.MessageDialog(
                                transient_for=self,
                                flags=0,
                                message_type=Gtk.MessageType.ERROR,
                                buttons=Gtk.ButtonsType.OK,
                                text="Export Failed"
                            )
                            error_dialog.format_secondary_text("Failed to export chat to PDF. Please check the logs.")
                            error_dialog.run()
                            error_dialog.destroy()
                    except Exception as e:
                        error_dialog = Gtk.MessageDialog(
                            transient_for=self,
                            flags=0,
                            message_type=Gtk.MessageType.ERROR,
                            buttons=Gtk.ButtonsType.OK,
                            text="Export Error"
                        )
                        error_dialog.format_secondary_text(f"Error during export: {str(e)}")
                        error_dialog.run()
                        error_dialog.destroy()
        finally:
            dialog.destroy()

    def save_image_to_file(self, img_path):
        """Show file chooser dialog and save image to selected location."""
        import shutil
        
        # Prefer the system-native file chooser when available
        if hasattr(Gtk, "FileChooserNative"):
            dialog = Gtk.FileChooserNative(
                title="Save Image",
                transient_for=self,
                action=Gtk.FileChooserAction.SAVE,
                accept_label="Save",
                cancel_label="Cancel",
            )
        else:
            dialog = Gtk.FileChooserDialog(
                title="Save Image",
                parent=self,
                action=Gtk.FileChooserAction.SAVE,
            )
            dialog.add_buttons(
                "Cancel", Gtk.ResponseType.CANCEL,
                "Save", Gtk.ResponseType.OK,
            )
        
        try:
            # Get the original filename
            original_filename = Path(img_path).name
            # Extract extension if present
            if '.' in original_filename:
                base_name = original_filename.rsplit('.', 1)[0]
                extension = '.' + original_filename.rsplit('.', 1)[1]
            else:
                base_name = original_filename
                extension = '.png'  # Default to PNG
            
            # Add image file filters
            image_filter = Gtk.FileFilter()
            image_filter.set_name("Image files")
            image_filter.add_pattern("*.png")
            image_filter.add_pattern("*.jpg")
            image_filter.add_pattern("*.jpeg")
            image_filter.add_pattern("*.gif")
            image_filter.add_pattern("*.bmp")
            image_filter.add_pattern("*.webp")
            dialog.add_filter(image_filter)
            
            # Add all files filter
            all_filter = Gtk.FileFilter()
            all_filter.set_name("All files")
            all_filter.add_pattern("*")
            dialog.add_filter(all_filter)
            
            # Set default filename
            dialog.set_current_name(base_name + extension)
            
            # Show the dialog
            response = dialog.run()
            
            # Gtk.FileChooserNative returns ACCEPT, Gtk.FileChooserDialog returns OK
            if response in (Gtk.ResponseType.OK, Gtk.ResponseType.ACCEPT):
                filename = dialog.get_filename()
                if filename:
                    try:
                        # Copy the image file to the selected location
                        shutil.copy2(img_path, filename)
                        
                        # Show success message
                        info_dialog = Gtk.MessageDialog(
                            transient_for=self,
                            flags=0,
                            message_type=Gtk.MessageType.INFO,
                            buttons=Gtk.ButtonsType.OK,
                            text="Image Saved"
                        )
                        info_dialog.format_secondary_text(f"Image saved to {filename}")
                        info_dialog.run()
                        info_dialog.destroy()
                    except Exception as e:
                        error_dialog = Gtk.MessageDialog(
                            transient_for=self,
                            flags=0,
                            message_type=Gtk.MessageType.ERROR,
                            buttons=Gtk.ButtonsType.OK,
                            text="Save Error"
                        )
                        error_dialog.format_secondary_text(f"Error saving image: {str(e)}")
                        error_dialog.run()
                        error_dialog.destroy()
        finally:
            dialog.destroy()

    def on_history_button_press(self, widget, event):
        """Handle right-click on history items."""
        if event.button == 3:  # Right click
            # Get the row at the clicked position
            row = widget.get_row_at_y(int(event.y))
            if row is not None:
                self.create_history_context_menu(row)
            return True
        return False

    def apply_sidebar_styles(self):
        """Apply CSS styling to the sidebar."""
        css_provider = Gtk.CssProvider()
        css = """
            .navigation-sidebar row {
                padding: 8px 6px;
                margin: 0px;
                border-radius: 0px;
                border: none;
            }
            .title {
                margin-bottom: 4px;
                font-size: 1.1em;
            }
            .timestamp {
                font-size: 0.8em;
                opacity: 0.7;
            }
            scrolledwindow {
                border-top: none;
                border-bottom: none;
            }
            scrolledwindow undershoot.top,
            scrolledwindow undershoot.bottom,
            scrolledwindow overshoot.top,
            scrolledwindow overshoot.bottom {
                background: none;
            }
            scrolledwindow junction {
                background: none;
                border: none;
            }
            /* Note: do not override scrollbar width/height so that
             * scrollbars follow the system theme and remain easy to grab.
             */
        """
        try:
            css_provider.load_from_data(css.encode())
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(),
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        except Exception as e:
            print(f"Error applying CSS: {e}")

    def create_speech_button(self, full_text):
        """
        Create a play/stop button for TTS playback or audio file replay.
        
        Uses the same TTS cache as automatic read-aloud, so if a response was
        already read aloud, clicking the play button will replay the cached audio.
        """
        btn_speak = Gtk.Button()
        button_size = self.font_size * 2
        btn_speak.set_size_request(button_size, button_size)
        
        icon_play = Gtk.Image.new_from_icon_name("media-playback-start", Gtk.IconSize.SMALL_TOOLBAR)
        icon_stop = Gtk.Image.new_from_icon_name("media-playback-stop", Gtk.IconSize.SMALL_TOOLBAR)
        btn_speak.set_image(icon_play)
        btn_speak.set_tooltip_text("Play response")
        
        is_playing = False
        stop_event = None
        
        # Convert list to string if necessary
        if isinstance(full_text, list):
            text_content = " ".join(full_text)
        else:
            text_content = str(full_text)
        
        # Check if this is a stored audio response from an audio model
        audio_file_match = re.search(r'<audio_file>(.*?)</audio_file>', text_content)
        initial_audio_path = audio_file_match.group(1) if audio_file_match else None
        
        def on_speak_clicked(widget):
            nonlocal is_playing, stop_event
            if not is_playing:
                is_playing = True
                stop_event = threading.Event()
                btn_speak.set_image(icon_stop)
                btn_speak.set_tooltip_text("Stop playback")
                
                def speak_thread():
                    nonlocal is_playing
                    try:
                        # Check for existing audio file from "audio model"
                        if initial_audio_path and Path(initial_audio_path).exists():
                            # Play existing audio file (from audio model)
                            self.current_playback_process = subprocess.Popen(['paplay', str(initial_audio_path)])
                            self.current_playback_process.wait()
                            return
                        
                        # Check for cached TTS audio using the shared cache path helper
                        cached_file = self._get_tts_cache_path(text_content, self.current_chat_id)
                        if cached_file and cached_file.exists():
                            # Play cached audio (may have been generated by auto read-aloud)
                            self.current_playback_process = subprocess.Popen(['paplay', str(cached_file)])
                            self.current_playback_process.wait()
                            return
                        
                        # No cached file, use TTS synthesis based on current provider
                        provider = getattr(self, 'tts_voice_provider', 'openai') or 'openai'
                        
                        # Check if this is a custom TTS model
                        custom_models = getattr(self, 'custom_models', {}) or {}
                        is_custom_tts = provider in custom_models and (custom_models[provider].get('api_type') or '').lower() == 'tts'
                        
                        if provider == 'openai':
                            self._synthesize_and_play_tts(
                                text_content,
                                chat_id=self.current_chat_id,
                                stop_event=stop_event
                            )
                        elif provider == 'gemini':
                            self._synthesize_and_play_gemini_tts(
                                text_content,
                                chat_id=self.current_chat_id,
                                stop_event=stop_event
                            )
                        elif provider in ('gpt-4o-audio-preview', 'gpt-4o-mini-audio-preview'):
                            self._synthesize_and_play_audio_preview(
                                text_content,
                                chat_id=self.current_chat_id,
                                model_id=provider,
                                stop_event=stop_event
                            )
                        elif is_custom_tts:
                            self._synthesize_and_play_custom_tts(
                                text_content,
                                chat_id=self.current_chat_id,
                                model_id=provider,
                                stop_event=stop_event
                            )
                    
                    except Exception as e:
                        GLib.idle_add(self.append_message, 'ai', f"Error playing audio: {str(e)}")
                    finally:
                        GLib.idle_add(btn_speak.set_image, icon_play)
                        GLib.idle_add(btn_speak.set_tooltip_text, "Play response")
                        is_playing = False
                
                threading.Thread(target=speak_thread, daemon=True).start()
            else:
                # Stop playback
                is_playing = False
                if stop_event:
                    stop_event.set()
                if hasattr(self, 'current_playback_process') and self.current_playback_process:
                    try:
                        self.current_playback_process.terminate()
                    except Exception:
                        pass
                btn_speak.set_image(icon_play)
                btn_speak.set_tooltip_text("Play response")
        
        btn_speak.connect("clicked", on_speak_clicked)
        return btn_speak

    def create_edit_button(self, image_path: str, message_index: int):
        """
        Create an edit button for generated images.
        
        When clicked, the button stays depressed and the image will be sent
        with the next question for editing.
        """
        btn_edit = Gtk.ToggleButton()
        button_size = self.font_size * 2
        btn_edit.set_size_request(button_size, button_size)
        
        icon_edit = Gtk.Image.new_from_icon_name("document-edit-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        btn_edit.set_image(icon_edit)
        btn_edit.set_tooltip_text("Edit this image with your next message")
        
        def on_edit_toggled(widget):
            if widget.get_active():
                # Check if current model supports image editing
                model = self._get_model_id_from_combo()
                from model_cards import get_card
                card = get_card(model, getattr(self, 'custom_models', {}))
                supports_edit = card and card.capabilities.image_edit if card else False
                
                if not supports_edit:
                    widget.set_active(False)
                    dialog = Gtk.MessageDialog(
                        transient_for=self,
                        modal=True,
                        message_type=Gtk.MessageType.WARNING,
                        buttons=Gtk.ButtonsType.OK,
                        text="Model does not support image editing",
                    )
                    dialog.format_secondary_text(
                        f"The current model '{model}' does not support image editing.\n\n"
                        "Either switch to a model that supports editing (e.g., gpt-image-1), "
                        "or enable 'Image Edit' for this model in Settings → Model Whitelist."
                    )
                    dialog.run()
                    dialog.destroy()
                    return
                
                # Deactivate any other edit buttons
                self._clear_pending_edit_image(except_path=image_path)
                self.pending_edit_image = image_path
                self.pending_edit_message_index = message_index
                widget.set_tooltip_text("Image selected for editing (click to deselect)")
            else:
                if getattr(self, 'pending_edit_image', None) == image_path:
                    self.pending_edit_image = None
                    self.pending_edit_message_index = None
                widget.set_tooltip_text("Edit this image with your next message")
        
        btn_edit.connect("toggled", on_edit_toggled)
        
        # Store reference for clearing
        btn_edit.image_path = image_path
        if not hasattr(self, '_edit_buttons'):
            self._edit_buttons = []
        self._edit_buttons.append(btn_edit)
        
        return btn_edit

    def _clear_pending_edit_image(self, except_path: str = None):
        """Clear pending edit image and deactivate all edit buttons except the specified one."""
        if hasattr(self, '_edit_buttons'):
            for btn in self._edit_buttons:
                if btn.get_active() and getattr(btn, 'image_path', None) != except_path:
                    btn.set_active(False)
        if except_path is None:
            self.pending_edit_image = None
            self.pending_edit_message_index = None

    # -----------------------------------------------------------------------
    # TTS Helpers – synthesize and play text via TTS or audio-preview
    # -----------------------------------------------------------------------

    def _get_tts_cache_path(self, text: str, chat_id: str) -> Path:
        """
        Get the cache file path for TTS audio based on current settings.
        
        This method computes a consistent cache path that can be used by both
        the play button and automatic read-aloud to share cached audio files.
        
        The cache key includes:
        - The text (cleaned of audio file tags)
        - The TTS provider
        - The TTS voice
        - The TTS HD mode (for OpenAI)
        - The prompt template hash (for Gemini and audio-preview models)
        
        Returns the Path to the cache file, or None if no chat_id is provided.
        """
        import hashlib
        
        if not chat_id:
            return None
        
        # Clean the text of any audio file tags
        clean_text = re.sub(r'<audio_file>.*?</audio_file>', '', text).strip()
        if not clean_text:
            return None
        
        # Get current TTS settings
        provider = getattr(self, 'tts_voice_provider', 'openai') or 'openai'
        voice = getattr(self, 'tts_voice', None) or 'alloy'
        hd_mode = self.tts_hd if provider == 'openai' else False
        template = getattr(self, 'tts_prompt_template', '') or ''
        
        # Build cache key components
        if provider == 'openai':
            mode = "ttshd" if hd_mode else "tts"
            cache_key = f"{clean_text}"
            prefix = f"openai_{mode}_{voice}"
        elif provider == 'gemini':
            # Include template in cache key for Gemini since it affects output
            if template and '{text}' in template:
                prompt_text = template.replace('{text}', clean_text)
            else:
                prompt_text = clean_text
            cache_key = f"{prompt_text}_{voice}"
            prefix = f"gemini_{voice}"
        else:
            # audio-preview models - include template and model in cache
            if template and '{text}' in template:
                prompt_text = template.replace('{text}', clean_text)
            else:
                prompt_text = f'Please say the following verbatim: "{clean_text}"'
            cache_key = f"{prompt_text}_{voice}_{provider}"
            prefix = f"{provider}_{voice}"
        
        # Generate hash
        text_hash = hashlib.md5(cache_key.encode()).hexdigest()[:8]
        
        # Get audio directory
        audio_dir = get_chat_dir(chat_id) / 'audio'
        audio_dir.mkdir(parents=True, exist_ok=True)
        
        return audio_dir / f"{prefix}_{text_hash}.wav"

    def _synthesize_and_play_tts(self, text: str, *, chat_id: str, stop_event: threading.Event = None) -> bool:
        """
        Synthesize text using OpenAI TTS and play it.
        
        Uses the unified tts_voice setting and caches audio files per chat.
        Returns True if playback completed successfully, False otherwise.
        """
        # Get the OpenAI provider for TTS via controller
        openai_provider = self.controller.get_provider('openai')
        
        if not openai_provider:
            print("TTS: OpenAI provider not available")
            return False
        
        try:
            # Clean the text of any audio file tags
            clean_text = re.sub(r'<audio_file>.*?</audio_file>', '', text).strip()
            if not clean_text:
                return True  # Nothing to say
            
            # Get the unified TTS voice setting
            voice = getattr(self, 'tts_voice', None) or 'alloy'
            
            # Use shared cache path helper
            audio_file = self._get_tts_cache_path(text, chat_id)
            if audio_file:
                # Check for cached file
                if audio_file.exists():
                    self.current_read_aloud_process = subprocess.Popen(['paplay', str(audio_file)])
                    self.current_read_aloud_process.wait()
                    return True
            else:
                # No chat_id, use a temp file
                import tempfile
                import hashlib
                text_hash = hashlib.md5(clean_text.encode()).hexdigest()[:8]
                audio_file = Path(tempfile.gettempdir()) / f"tts_openai_{text_hash}.wav"
            
            # Generate TTS audio
            with openai_provider.audio.speech.with_streaming_response.create(
                model="tts-1-hd" if self.tts_hd else "tts-1",
                voice=voice,
                input=clean_text
            ) as response:
                with open(audio_file, 'wb') as f:
                    for chunk in response.iter_bytes():
                        if stop_event and stop_event.is_set():
                            # User requested stop
                            audio_file.unlink(missing_ok=True)
                            return False
                        f.write(chunk)
            
            if stop_event and stop_event.is_set():
                audio_file.unlink(missing_ok=True)
                return False
            
            # Play the generated audio
            self.current_read_aloud_process = subprocess.Popen(['paplay', str(audio_file)])
            self.current_read_aloud_process.wait()
            return True
            
        except Exception as e:
            print(f"Read Aloud TTS error: {e}")
            return False

    def _synthesize_and_play_audio_preview(self, text: str, *, chat_id: str, model_id: str, stop_event: threading.Event = None) -> bool:
        """
        Synthesize text using gpt-4o-audio-preview or gpt-4o-mini-audio-preview.
        
        Builds a prompt using the configured template and sends it to the audio model.
        Returns True if playback completed successfully, False otherwise.
        """
        # Get the OpenAI provider via controller
        openai_provider = self.controller.get_provider('openai')
        
        if not openai_provider:
            print("TTS: OpenAI provider not available for audio-preview")
            return False
        
        try:
            # Clean the text of any audio file tags
            clean_text = re.sub(r'<audio_file>.*?</audio_file>', '', text).strip()
            if not clean_text:
                return True  # Nothing to say
            
            # Build the prompt using the unified TTS prompt template
            template = getattr(self, 'tts_prompt_template', '') or 'Please say the following verbatim: "{text}"'
            prompt = template.replace('{text}', clean_text)
            
            # Get the unified TTS voice setting
            voice = getattr(self, 'tts_voice', None) or 'alloy'
            
            # Use shared cache path helper
            audio_file = self._get_tts_cache_path(text, chat_id)
            if audio_file:
                # Check for cached file
                if audio_file.exists():
                    self.current_read_aloud_process = subprocess.Popen(['paplay', str(audio_file)])
                    self.current_read_aloud_process.wait()
                    return True
            else:
                # No chat_id, use a temp file
                import tempfile
                import hashlib
                text_hash = hashlib.md5(f"{prompt}_{voice}_{model_id}".encode()).hexdigest()[:8]
                audio_file = Path(tempfile.gettempdir()) / f"tts_audio_preview_{text_hash}.wav"
            
            # Call the audio-preview model
            response = openai_provider.client.chat.completions.create(
                model=model_id,
                modalities=["text", "audio"],
                audio={"voice": voice, "format": "wav"},
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            if stop_event and stop_event.is_set():
                return False
            
            # Extract and play the audio
            if hasattr(response.choices[0].message, 'audio') and response.choices[0].message.audio:
                audio_data = response.choices[0].message.audio.data
                audio_bytes = base64.b64decode(audio_data)
                
                with open(audio_file, 'wb') as f:
                    f.write(audio_bytes)
                
                if stop_event and stop_event.is_set():
                    audio_file.unlink(missing_ok=True)
                    return False
                
                # Play the audio
                self.current_read_aloud_process = subprocess.Popen(['paplay', str(audio_file)])
                self.current_read_aloud_process.wait()
                return True
            else:
                print("TTS: No audio in response from audio-preview model")
                return False
                
        except Exception as e:
            print(f"TTS audio-preview error: {e}")
            return False

    def _synthesize_and_play_gemini_tts(self, text: str, *, chat_id: str, stop_event: threading.Event = None) -> bool:
        """
        Synthesize text using Gemini TTS with controllable speech.
        
        Builds a prompt using the configured template for controllable speech styles.
        Uses the unified tts_voice setting and caches audio files per chat.
        Returns True if playback completed successfully, False otherwise.
        """
        # Get the Gemini provider via controller
        gemini_provider = self.controller.get_provider('gemini')
        
        if not gemini_provider:
            print("TTS: Gemini provider not available")
            return False
        
        try:
            # Clean the text of any audio file tags
            clean_text = re.sub(r'<audio_file>.*?</audio_file>', '', text).strip()
            if not clean_text:
                return True  # Nothing to say
            
            # Build the prompt using the unified TTS prompt template for controllable speech
            # Gemini TTS supports prompt-based style control (e.g., "Say cheerfully:", "Read slowly:")
            template = getattr(self, 'tts_prompt_template', '') or ''
            if template and '{text}' in template:
                prompt_text = template.replace('{text}', clean_text)
            else:
                # No template or invalid template, just use the text directly
                prompt_text = clean_text
            
            # Get the unified TTS voice setting (should be a Gemini voice when provider is gemini)
            voice = getattr(self, 'tts_voice', None) or 'Kore'
            
            # Use shared cache path helper
            audio_file = self._get_tts_cache_path(text, chat_id)
            if audio_file:
                # Check for cached file
                if audio_file.exists():
                    self.current_read_aloud_process = subprocess.Popen(['paplay', str(audio_file)])
                    self.current_read_aloud_process.wait()
                    return True
            else:
                # No chat_id, use a temp file
                import tempfile
                import hashlib
                cache_key = f"{prompt_text}_{voice}"
                text_hash = hashlib.md5(cache_key.encode()).hexdigest()[:8]
                audio_file = Path(tempfile.gettempdir()) / f"tts_gemini_{text_hash}.wav"
            
            if stop_event and stop_event.is_set():
                return False
            
            # Generate TTS audio using Gemini
            audio_bytes = gemini_provider.generate_speech(prompt_text, voice)
            
            if stop_event and stop_event.is_set():
                return False
            
            # Save the audio file
            with open(audio_file, 'wb') as f:
                f.write(audio_bytes)
            
            if stop_event and stop_event.is_set():
                audio_file.unlink(missing_ok=True)
                return False
            
            # Play the generated audio
            self.current_read_aloud_process = subprocess.Popen(['paplay', str(audio_file)])
            self.current_read_aloud_process.wait()
            return True
            
        except Exception as e:
            print(f"TTS Gemini error: {e}")
            return False

    def _synthesize_and_play_custom_tts(self, text: str, *, chat_id: str, model_id: str, stop_event: threading.Event = None) -> bool:
        """
        Synthesize text using a custom TTS model defined in custom_models.json.
        
        Uses the CustomProvider to call the model's TTS endpoint with the voice
        configured in the model definition.
        Returns True if playback completed successfully, False otherwise.
        """
        from ai_providers import CustomProvider
        
        # Get the custom model configuration
        custom_models = getattr(self, 'custom_models', {}) or {}
        cfg = custom_models.get(model_id)
        if not cfg:
            print(f"TTS: Custom model '{model_id}' not found")
            return False
        
        try:
            # Clean the text of any audio file tags
            clean_text = re.sub(r'<audio_file>.*?</audio_file>', '', text).strip()
            if not clean_text:
                return True  # Nothing to say
            
            # Determine which voice to use: user selection -> model voice -> first in list -> default
            selected_voice = getattr(self, 'tts_voice', None) or ''
            cfg_voice = (cfg.get('voice') or '').strip()
            cfg_voices = []
            if isinstance(cfg.get('voices'), list):
                cfg_voices = [v.strip() for v in cfg.get('voices') if isinstance(v, str) and v.strip()]
            voice = selected_voice.strip() or cfg_voice or (cfg_voices[0] if cfg_voices else "default")
            
            # Create and initialize the custom provider
            from utils import resolve_api_key
            provider = CustomProvider()
            provider.initialize(
                api_key=resolve_api_key(cfg.get('api_key', '')),
                endpoint=cfg.get('endpoint', ''),
                model_name=cfg.get('model_name') or cfg.get('model_id') or model_id,
                api_type='tts',
                voice=voice
            )
            
            # Generate cache file path
            import hashlib
            import tempfile
            cache_key = f"{clean_text}_{model_id}_{voice}"
            text_hash = hashlib.md5(cache_key.encode()).hexdigest()[:8]
            
            if chat_id:
                audio_dir = get_chat_dir(chat_id) / 'audio'
                audio_dir.mkdir(parents=True, exist_ok=True)
                safe_model = "".join(c if c.isalnum() else "_" for c in model_id)
                audio_file = audio_dir / f"custom_{safe_model}_{voice}_{text_hash}.wav"
                
                # Check for cached file
                if audio_file.exists():
                    self.current_read_aloud_process = subprocess.Popen(['paplay', str(audio_file)])
                    self.current_read_aloud_process.wait()
                    return True
            else:
                audio_file = Path(tempfile.gettempdir()) / f"tts_custom_{text_hash}.wav"
            
            if stop_event and stop_event.is_set():
                return False
            
            # Generate TTS audio using the custom provider
            audio_bytes = provider.generate_speech(clean_text, voice)
            
            if stop_event and stop_event.is_set():
                return False
            
            # Save the audio file
            with open(audio_file, 'wb') as f:
                f.write(audio_bytes)
            
            if stop_event and stop_event.is_set():
                audio_file.unlink(missing_ok=True)
                return False
            
            # Play the generated audio
            self.current_read_aloud_process = subprocess.Popen(['paplay', str(audio_file)])
            self.current_read_aloud_process.wait()
            return True
            
        except Exception as e:
            print(f"TTS Custom model error: {e}")
            return False

    def read_aloud_text(self, text: str, *, chat_id: str = None):
        """
        Read the given text aloud using the unified TTS settings.
        
        This is the main entry point for the Read Aloud feature. It checks
        if read aloud is enabled and dispatches to the appropriate synthesis
        method based on the configured TTS provider (tts_voice_provider).
        
        Runs in a background thread to avoid blocking the UI.
        """
        # Check if read aloud is enabled
        if not getattr(self, 'read_aloud_enabled', False):
            return
        
        # Use current chat_id if not specified
        if chat_id is None:
            chat_id = self.current_chat_id
        
        # Stop any existing read-aloud playback
        self.stop_read_aloud()
        
        # Create a stop event for this playback
        self.read_aloud_stop_event = threading.Event()
        
        def read_aloud_thread():
            # Use unified TTS settings (tts_voice_provider)
            provider = getattr(self, 'tts_voice_provider', 'openai') or 'openai'
            
            # Check if this is a custom TTS model
            custom_models = getattr(self, 'custom_models', {}) or {}
            is_custom_tts = provider in custom_models and (custom_models[provider].get('api_type') or '').lower() == 'tts'
            
            try:
                if provider == 'openai':
                    self._synthesize_and_play_tts(
                        text,
                        chat_id=chat_id,
                        stop_event=self.read_aloud_stop_event
                    )
                elif provider == 'gemini':
                    self._synthesize_and_play_gemini_tts(
                        text,
                        chat_id=chat_id,
                        stop_event=self.read_aloud_stop_event
                    )
                elif provider in ('gpt-4o-audio-preview', 'gpt-4o-mini-audio-preview'):
                    self._synthesize_and_play_audio_preview(
                        text,
                        chat_id=chat_id,
                        model_id=provider,
                        stop_event=self.read_aloud_stop_event
                    )
                elif is_custom_tts:
                    self._synthesize_and_play_custom_tts(
                        text,
                        chat_id=chat_id,
                        model_id=provider,
                        stop_event=self.read_aloud_stop_event
                    )
                else:
                    print(f"Read Aloud: Unknown TTS provider '{provider}'")
            except Exception as e:
                print(f"Read Aloud error: {e}")
            finally:
                self.read_aloud_stop_event = None
        
        threading.Thread(target=read_aloud_thread, daemon=True).start()

    def stop_read_aloud(self):
        """Stop any ongoing read-aloud playback."""
        # Signal the read-aloud thread to stop
        if hasattr(self, 'read_aloud_stop_event') and self.read_aloud_stop_event:
            self.read_aloud_stop_event.set()
        
        # Terminate any playing audio process
        if hasattr(self, 'current_read_aloud_process') and self.current_read_aloud_process:
            try:
                self.current_read_aloud_process.terminate()
            except Exception:
                pass

    def _split_table_row(self, line):
        """Split a markdown table row into cells."""
        if not line:
            return []
        stripped = line.strip()
        if stripped.startswith('|'):
            stripped = stripped[1:]
        if stripped.endswith('|'):
            stripped = stripped[:-1]
        return [cell.strip() for cell in stripped.split('|')]

    def _get_table_alignments(self, separator_line, column_count):
        """Determine alignment for each column from the separator line."""
        raw_cells = self._split_table_row(separator_line)
        alignments = []
        for cell in raw_cells:
            cell = cell.strip()
            left = cell.startswith(':')
            right = cell.endswith(':')
            if left and right:
                alignments.append(0.5)
            elif right:
                alignments.append(1.0)
            else:
                alignments.append(0.0)
        # Pad or trim to match expected column count
        if len(alignments) < column_count:
            alignments.extend([0.0] * (column_count - len(alignments)))
        elif len(alignments) > column_count:
            alignments = alignments[:column_count]
        return alignments

    def _get_widget_alignment(self, value):
        """Map numeric alignment to Gtk.Align."""
        if value >= 0.9:
            return Gtk.Align.END
        if value >= 0.4:
            return Gtk.Align.CENTER
        return Gtk.Align.START

    def _get_justification(self, value):
        """Map numeric alignment to Gtk.Justification."""
        if value >= 0.9:
            return Gtk.Justification.RIGHT
        if value >= 0.4:
            return Gtk.Justification.CENTER
        return Gtk.Justification.LEFT

    def _get_realtime_prompt(self):
        """Return the realtime prompt with the AI name substituted."""
        template = getattr(self, "realtime_prompt", "") or "Your name is {name}, speak quickly and professionally"
        ai_name = getattr(self, "ai_name", "") or "Assistant"
        return template.replace("{name}", ai_name)

    def _is_latex_math_image(self, img_path: str) -> bool:
        """
        Return True if the given image path looks like a LaTeX-generated
        math image. These are always small and should not be affected by
        responsive resizing logic for model-generated images.
        """
        try:
            name = os.path.basename(str(img_path))
        except Exception:
            return False

        return name.startswith("math_inline_") or name.startswith("math_display_")

def main():
    win = OpenAIGTKClient()
    win.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()
