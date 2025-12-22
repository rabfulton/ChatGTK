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
            on_new_chat=lambda: self.on_new_chat_clicked(None),
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
        self._sidebar_initialized = False

        # Update memory value without saving to file
        def on_paned_position_changed(paned, param):
            if self._sidebar_initialized and not self.is_maximized():
                self.current_sidebar_width = paned.get_position()
                self.sidebar_width = self.current_sidebar_width

        self.paned.connect('notify::position', on_paned_position_changed)
        
        # Set paned position after window is realized
        def set_initial_position(widget):
            self.paned.set_position(self.current_sidebar_width)
            self._sidebar_initialized = True
        self.connect('realize', set_initial_position)

        # Toolbar component
        from ui import Toolbar
        self._toolbar = Toolbar(
            event_bus=self.controller.event_bus,
            on_sidebar_toggle=lambda: self.on_sidebar_toggle(None),
            on_settings=lambda: self.on_open_settings(None),
            on_tools=lambda: self.on_open_tools(None),
            sidebar_visible=getattr(self, 'sidebar_visible', True),
        )
        self.sidebar_button = self._toolbar.sidebar_button
        
        # Model selector component
        from ui import ModelSelector
        self._model_selector = ModelSelector(
            event_bus=self.controller.event_bus,
            on_model_changed=self._handle_model_changed,
        )
        self._toolbar.widget.pack_start(self._model_selector.widget, False, False, 0)
        self._toolbar.widget.reorder_child(self._model_selector.widget, 1)
        # Expose combo_model for backward compatibility
        self.combo_model = self._model_selector.widget
        self._display_to_model_id = self._model_selector._display_to_model_id
        self._model_id_to_display = self._model_selector._model_id_to_display
        
        # Provider initialization
        if self.providers or self.custom_models:
            self.fetch_models_async()
        else:
            default_models = self.controller.get_default_models_for_provider('openai')
            self.model_provider_map = {model: 'openai' for model in default_models}
            self.controller.model_provider_map = self.model_provider_map
            self.update_model_list(default_models, self.default_model)

        # System prompt selector
        self.combo_system_prompt = Gtk.ComboBoxText()
        self.combo_system_prompt.connect("changed", self.on_system_prompt_changed)
        self._refresh_system_prompt_combo()
        self._toolbar.widget.pack_start(self.combo_system_prompt, False, False, 0)
        self._toolbar.widget.reorder_child(self.combo_system_prompt, 2)
        
        # Initialize tool indicators
        self._update_tool_indicators()

        vbox_main.pack_start(self._toolbar.widget, False, False, 0)

        # Chat view component for message display
        from ui import ChatView
        self._chat_view = ChatView(
            event_bus=self.controller.event_bus,
            window=self,
            ai_name=self.ai_name,
            ai_color=self.ai_color,
            on_cancel=self._on_thinking_cancelled,
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
            self.controller.settings_manager.set(key, value, emit_event=False)
        # Persist to disk
        self.controller.settings_manager.save()
        
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
        # Use ModelSelector if available
        if hasattr(self, '_model_selector'):
            model_id = self._model_selector.get_selected_model_id()
            if model_id:
                return model_id
        
        # Fallback to direct combo access
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
            create_save_button=self.create_save_button,
            create_copy_button=self.create_copy_button,
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
        
        # Chat events - CHAT_LOADED/SAVED/DELETED handled by HistorySidebar
        bus.subscribe(EventType.CHAT_CREATED, self._on_chat_created_event)
        
        # Settings events
        bus.subscribe(EventType.SETTINGS_CHANGED, self._on_settings_changed_event)
        
        # Error events
        bus.subscribe(EventType.ERROR_OCCURRED, self._on_error_event)
        
        # Note: THINKING_STARTED/STOPPED handled by ChatView component
        
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

    def _on_thinking_cancelled(self):
        """Handle cancel button click from ChatView."""
        self.request_cancelled = True
        cancel_text = "** Request cancelled by user **"
        message_index = self.controller.add_notification(cancel_text, 'cancel')
        GLib.idle_add(lambda idx=message_index: self.append_message('ai', cancel_text, idx))

    def emit_thinking_started(self, model: str = None):
        """Emit THINKING_STARTED event and show animation."""
        self.request_cancelled = False
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
            # Track last active chat when chat ID is assigned (first user message)
            if self.current_chat_id and self.last_active_chat != self.current_chat_id:
                self.last_active_chat = self.current_chat_id
                save_object_settings(self)

    def _on_message_received_event(self, event):
        """Handle MESSAGE_RECEIVED event - display assistant message in UI."""
        content = event.data.get('content', '')
        formatted = event.data.get('formatted_content', '') or format_response(content)
        index = event.data.get('index', 0)
        model = event.data.get('model', '')
        
        # Only handle if source is controller
        if event.source == 'controller':
            GLib.idle_add(lambda: self.append_message('ai', formatted, index))
            
            # Read aloud if enabled (skip audio models)
            card = get_card(model, self.custom_models)
            if not (card and card.capabilities.audio_out):
                self.read_aloud_text(formatted, chat_id=self.current_chat_id)

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
    # Toolbar helpers
    # -----------------------------------------------------------------------

    def _update_tool_indicators(self):
        """Update the toolbar tool indicators based on current settings."""
        if hasattr(self, '_toolbar'):
            self._toolbar.update_tool_indicators(
                image=bool(getattr(self, "image_tool_enabled", False)),
                music=bool(getattr(self, "music_tool_enabled", False)),
                web_search=bool(getattr(self, "web_search_enabled", False)),
                read_aloud=bool(getattr(self, "read_aloud_tool_enabled", False)),
                search=bool(getattr(self, "search_tool_enabled", False)),
            )

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
        self.controller.update_system_message(prompt["content"])
        
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

    def _build_tool_handlers(self, model: str, last_msg: dict) -> dict:
        """Build tool handler kwargs for a model."""
        handlers = {}
        ts = self.controller.tool_service
        
        if ts.supports_image_tools(model, self.model_provider_map, self.custom_models):
            handlers["image_tool_handler"] = lambda prompt_arg, image_path=None: \
                self.controller.handle_image_tool(prompt_arg, image_path)
        
        if ts.supports_music_tools(model, self.model_provider_map, self.custom_models):
            handlers["music_tool_handler"] = lambda action, keyword=None, volume=None: \
                self.controller.handle_music_tool(action, keyword=keyword, volume=volume)
        
        if ts.supports_read_aloud_tools(model, self.model_provider_map, self.custom_models):
            handlers["read_aloud_tool_handler"] = lambda text: self._handle_read_aloud_tool(text)
        
        if ts.supports_search_tools(model, self.model_provider_map, self.custom_models):
            handlers["search_tool_handler"] = lambda keyword, source=None: \
                self.controller.handle_search_tool(keyword, source)
        
        return handlers

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
            # Reload settings manager cache so controller sees updated values
            self.controller.settings_manager.reload()

            # Update message renderer settings and refresh existing message colors
            self._update_message_renderer_settings()
            if hasattr(self, 'message_renderer'):
                self.message_renderer.update_existing_message_colors()

            # Re-initialize system prompts from updated settings and refresh the combo
            self._init_system_prompts_from_settings()
            self._refresh_system_prompt_combo()
            
            # Update the system message in the current conversation if it exists
            self.controller.update_system_message(self.system_message)

            # Keep tools in sync via service
            self.controller.tool_service.enable_tool('image', bool(getattr(self, "image_tool_enabled", True)))
            self.controller.tool_service.enable_tool('music', bool(getattr(self, "music_tool_enabled", False)))
            self.controller.tool_service.enable_tool('read_aloud', bool(getattr(self, "read_aloud_tool_enabled", False)))
            self.controller.tool_service.enable_tool('search', bool(getattr(self, "search_tool_enabled", False)))
            
            # Update toolbar indicators
            self._update_tool_indicators()

            # Handle API keys from the dialog
            new_keys = dialog.get_api_keys()
            self._apply_api_keys(new_keys)

            # Update custom models from dialog (already persisted on disk)
            if hasattr(dialog, "get_custom_models"):
                self.custom_models = dialog.get_custom_models()
                self.controller.custom_models = self.custom_models  # Sync to controller
                # Drop any cached custom providers to avoid stale configs
                self.custom_providers = {}

            # Re-initialize memory service AFTER custom_models is updated
            self.controller.update_tool_manager()

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
                               tool_use_supported=tool_use_supported,
                               current_model=current_model)
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
            # Reload settings manager cache so controller sees updated values
            self.controller.settings_manager.reload()
            # Update toolbar indicators
            self._update_tool_indicators()
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
        """Display a simple modal error dialog with selectable text."""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Error",
        )
        # Use a selectable label instead of format_secondary_text
        label = Gtk.Label(label=str(message))
        label.set_selectable(True)
        label.set_line_wrap(True)
        label.set_max_width_chars(60)
        label.show()
        dialog.get_message_area().pack_start(label, False, False, 0)
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
        """Display an error dialog. Alias for show_error_dialog."""
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

        target_model = selected_model
        provider_name = self.get_provider_name_for_model(target_model)

        if provider_name == 'custom':
            # Custom models: resolve API key (supports $ENV_VAR syntax)
            from utils import resolve_api_key
            custom_config = (self.custom_models or {}).get(target_model, {})
            display_name = custom_config.get('display_name', target_model)
            api_key = resolve_api_key(custom_config.get('api_key', '')).strip()
            if not api_key:
                self.show_error_dialog(f"Please enter an API key for custom model: {display_name}")
                return False
        elif provider_name == 'gemini':
            env_var = 'GEMINI_API_KEY'
            provider_label = "Gemini"
            api_key = os.environ.get(env_var, self.api_keys.get(provider_name, '')).strip()
            if not api_key:
                self.show_error_dialog(f"Please enter your {provider_label} API key")
                return False
            os.environ[env_var] = api_key
        elif provider_name == 'grok':
            env_var = 'GROK_API_KEY'
            provider_label = "Grok"
            api_key = os.environ.get(env_var, self.api_keys.get(provider_name, '')).strip()
            if not api_key:
                self.show_error_dialog(f"Please enter your {provider_label} API key")
                return False
            os.environ[env_var] = api_key
        elif provider_name == 'claude':
            env_var = 'CLAUDE_API_KEY'
            provider_label = "Claude"
            api_key = os.environ.get(env_var, self.api_keys.get(provider_name, '')).strip()
            if not api_key:
                self.show_error_dialog(f"Please enter your {provider_label} API key")
                return False
            os.environ[env_var] = api_key
        elif provider_name == 'perplexity':
            env_var = 'PERPLEXITY_API_KEY'
            provider_label = "Perplexity"
            api_key = os.environ.get(env_var, self.api_keys.get(provider_name, '')).strip()
            if not api_key:
                self.show_error_dialog(f"Please enter your {provider_label} API key")
                return False
            os.environ[env_var] = api_key
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
            label = display_name if provider_name == 'custom' else provider_label
            self.show_error_dialog(f"Unable to initialize the {label} provider")
            return False
        
        model_temperature = self._get_temperature_for_model(target_model)

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
                # Include path in message so model can pass it to generate_image tool
                edit_instruction = f"[Edit the image at: {self.pending_edit_image}]"
                display_text = f"[Editing image]\n{question}" if question else "[Editing image]"
                question = f"{edit_instruction}\n{question}" if question else edit_instruction
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

        # Apply formatting (Markdown preprocessing like code blocks/tables) to the user message
        # just like we do for AI responses, so that code blocks render correctly.
        formatted_display_text = format_response(display_text)
        
        # Add message via controller (handles history, memory, chat ID assignment)
        # The MESSAGE_SENT event will trigger append_message via _on_message_sent_event
        self.controller.add_user_message(
            question,
            images=images if images else None,
            files=files if files else None,
            display_content=display_text if display_text != question else None,
        )

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
        """Call AI API - delegates to controller.send_message()."""
        # Build tool handlers (these reference UI methods)
        last_msg = self.conversation_history[-1]
        tool_handlers = self._build_tool_handlers(model, last_msg)
        
        # Delegate to controller
        self.controller.send_message(
            model=model,
            tool_handlers=tool_handlers,
            cancel_check=lambda: getattr(self, 'request_cancelled', False),
        )

    def audio_transcription(self, widget):
        """Handle audio transcription."""
        print("Audio transcription...")
        stt_model = getattr(self, "speech_to_text_model", "") or "whisper-1"
        stt_provider = None
        stt_base_url = None
        stt_api_key = None
        
        # Check if this is a custom STT model
        cfg = (self.custom_models or {}).get(stt_model, {})
        is_custom_stt = (cfg.get("api_type") or "").lower() == "stt"
        
        if is_custom_stt:
            # Use CustomProvider for custom STT models
            from ai_providers import CustomProvider
            from utils import resolve_api_key
            stt_provider = CustomProvider()
            stt_provider.initialize(
                api_key=resolve_api_key(cfg.get("api_key", "")),
                endpoint=cfg.get("endpoint", ""),
                model_id=stt_model,
                api_type="stt",
            )
        else:
            try:
                card = get_card(stt_model, self.custom_models)
                if card:
                    stt_base_url = card.base_url or None
                    # Try to resolve a key for custom models
                    if card.provider == "custom":
                        if cfg:
                            from utils import resolve_api_key
                            stt_api_key = resolve_api_key(cfg.get("api_key", ""))
                    elif card.key_name:
                        stt_api_key = self.api_keys.get(card.key_name) or stt_api_key
            except Exception as e:
                print(f"[Audio STT] Error reading card for {stt_model}: {e}")
            
            # Get OpenAI provider via controller
            stt_provider = self.controller.get_provider('openai')
        
        if not stt_provider:
            self.show_error_dialog("Audio transcription requires an API key")
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
                                
                                # Transcribe with selected model (fallback to whisper-1 for non-custom)
                                transcript = None
                                models_to_try = [stt_model]
                                if not is_custom_stt and "whisper-1" not in models_to_try:
                                    models_to_try.append("whisper-1")

                                for model in models_to_try:
                                    transcript = audio_service.transcribe(
                                        temp_file, stt_provider,
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
                msg_index = self.controller.add_notification(err_text, 'error')
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
        stt_provider = None
        stt_base_url = None
        stt_api_key = None
        
        # Check if this is a custom STT model
        cfg = (self.custom_models or {}).get(stt_model, {})
        is_custom_stt = (cfg.get("api_type") or "").lower() == "stt"
        
        if is_custom_stt:
            # Use CustomProvider for custom STT models
            from ai_providers import CustomProvider
            from utils import resolve_api_key
            stt_provider = CustomProvider()
            stt_provider.initialize(
                api_key=resolve_api_key(cfg.get("api_key", "")),
                endpoint=cfg.get("endpoint", ""),
                model_id=stt_model,
                api_type="stt",
            )
        else:
            try:
                card = get_card(stt_model, self.custom_models)
                if card:
                    stt_base_url = card.base_url or None
                    if card.provider == "custom":
                        if cfg:
                            from utils import resolve_api_key
                            stt_api_key = resolve_api_key(cfg.get("api_key", ""))
                    elif card.key_name:
                        stt_api_key = self.api_keys.get(card.key_name) or stt_api_key
            except Exception as e:
                print(f"[Audio STT] Error reading card for {stt_model}: {e}")

            # Get OpenAI provider via controller
            stt_provider = self.controller.get_provider('openai')
        
        if not stt_provider:
            self.show_error_dialog("Audio transcription requires an API key")
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
                                if not is_custom_stt and "whisper-1" not in models_to_try:
                                    models_to_try.append("whisper-1")

                                for model in models_to_try:
                                    transcript = audio_service.transcribe(
                                        temp_file, stt_provider,
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
                        api_key=api_key,
                        vad_threshold=float(getattr(self, "realtime_vad_threshold", 0.1))
                    )
                    
                except Exception as e:
                    print(f"Real-time streaming error: {e}")
                    err_text = f"Error starting real-time streaming: {str(e)}"
                    msg_index = self.controller.add_notification(err_text, 'error')
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
        filename = history_row.chat_id
        
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
                self.controller.new_chat(self.system_message)

            # Delete the chat history via controller
            self.controller.delete_chat(filename)
            
            # Refresh the history list
            self.refresh_history_list()


    def on_sidebar_toggle(self, button=None):
        """Toggle sidebar visibility."""
        if self.sidebar_visible:
            self.sidebar.hide()
        else:
            self.sidebar.show()
            # Restore the paned position to the saved sidebar width
            self.paned.set_position(self.current_sidebar_width)
            # Reload the current conversation to force reflow with new width
            GLib.idle_add(self._reload_current_conversation)
        
        self.sidebar_visible = not self.sidebar_visible
        
        # Update toolbar button if using component
        if hasattr(self, '_toolbar'):
            self._toolbar.set_sidebar_visible(self.sidebar_visible)
    
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
        self.controller.new_chat(self.system_message)
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
        if save_current and self.current_chat_id is None and self.controller.get_message_count() > 1:
            self.save_current_chat()
        
        # Load via controller
        chat_id = filename.replace('.json', '') if filename.endswith('.json') else filename
        if self.controller.load_chat(chat_id):
            # Controller now owns the state
            history = self.conversation_history  # Read from controller
            
            # Save the last active chat to settings
            self.last_active_chat = chat_id
            save_object_settings(self)
            
            # Set the model if it was saved with the chat
            if history and len(history) > 0 and "model" in history[0]:
                saved_model = history[0]["model"]
                # Prefer using the ModelSelector API so its internal mappings stay in sync.
                display_text = (
                    getattr(self, "_model_id_to_display", {}).get(saved_model)
                    or get_model_display_name(saved_model, self.custom_models)
                    or saved_model
                )

                # Ensure the selector knows about this model (handles missing/custom models).
                if hasattr(self, "_model_selector"):
                    if saved_model not in self._model_selector._model_id_to_display:
                        self._model_selector._model_id_to_display[saved_model] = display_text
                        self._model_selector._display_to_model_id[display_text] = saved_model
                        self.combo_model.append_text(display_text)
                    self._model_selector.select_model(saved_model)
            
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
                    # Use display_content if available, otherwise fall back to content
                    content = message.get('display_content') or message['content']
                    if message['role'] == 'user':
                        formatted_content = format_response(content)
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
            
            # Schedule scroll after the conversation is rebuilt (with delay for rendering)
            GLib.timeout_add(100, scroll_to_top)
            
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
        if self.controller.get_message_count() > 1:  # More than just the system message
            # Track model in system message
            current_model = self._get_model_id_from_combo()
            if current_model:
                # Don't overwrite with image/tts models
                is_excluded = "dall-e" in current_model.lower() or "tts" in current_model.lower() or "audio" in current_model.lower()
                has_existing_model = "model" in self.conversation_history[0]
                if not is_excluded or not has_existing_model:
                    self.conversation_history[0]["model"] = current_model

            chat_id = self.controller.save_current_chat()
            
            if chat_id:
                self.current_chat_id = chat_id
                self.last_active_chat = chat_id.replace('.json', '') if chat_id.endswith('.json') else chat_id
                save_object_settings(self)

    def show_thinking_animation(self):
        """Show thinking animation - delegated to ChatView component."""
        if hasattr(self, '_chat_view'):
            self._chat_view.set_ai_style(self.ai_name, self.ai_color)
            self._chat_view.show_thinking()

    def hide_thinking_animation(self):
        """Hide thinking animation - delegated to ChatView component."""
        if hasattr(self, '_chat_view'):
            self._chat_view.hide_thinking()

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
        if message_index <= 0 or message_index >= self.controller.get_message_count():
            return

        widget_idx = message_index - 1  # message_widgets excludes system message
        if widget_idx < 0 or widget_idx >= len(self.message_widgets):
            return

        widget = self.message_widgets.pop(widget_idx)
        try:
            widget.destroy()
        except Exception:
            pass

        self.controller.delete_message(message_index)

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
                chat_id = history_row.chat_id
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
            chat_id = history_row.chat_id
            default_name = f"chat_{chat_id}.pdf"
            dialog.set_current_name(default_name)
            
            # Show the dialog
            response = dialog.run()
            
            # Gtk.FileChooserNative returns ACCEPT, Gtk.FileChooserDialog returns OK
            if response in (Gtk.ResponseType.OK, Gtk.ResponseType.ACCEPT):
                filename = dialog.get_filename()
                if not filename.endswith('.pdf'):
                    filename += '.pdf'
                    
                # Load the chat history via chat service
                conv = self.controller.chat_service.load_chat(chat_id)
                history = conv.to_list() if conv and hasattr(conv, 'to_list') else conv
                if history:
                    # Use the sidebar chat title and present it with capitalized words
                    chat_title = get_chat_title(chat_id)
                    # Remove timestamp suffix (e.g., _20250211_203903) and convert underscores to spaces
                    clean_title = re.sub(r'_\d{8}_\d{6}$', '', chat_title)
                    clean_title = clean_title.replace('_', ' ')
                    formatted_title = " ".join(
                        word[:1].upper() + word[1:] if word else ""
                        for word in clean_title.split()
                    )
                    
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
                from model_cards import get_card
                
                # Check if either the chat model OR the image model supports editing
                chat_model = self._get_model_id_from_combo()
                chat_card = get_card(chat_model, getattr(self, 'custom_models', {}))
                chat_supports_edit = chat_card and chat_card.capabilities.image_edit if chat_card else False
                
                image_model = self.controller.get_setting('IMAGE_MODEL', 'dall-e-3')
                image_card = get_card(image_model, getattr(self, 'custom_models', {})) if image_model else None
                image_supports_edit = image_card and image_card.capabilities.image_edit if image_card else False
                
                if not chat_supports_edit and not image_supports_edit:
                    widget.set_active(False)
                    msg = (f"Neither the chat model '{chat_model}' nor the image model '{image_model}' supports image editing.\n\n"
                           "Switch to a model that supports editing (e.g., gpt-image-1), "
                           "or enable 'Image Edit' in Settings → Model Whitelist.")
                    self.show_error_dialog(msg)
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

    def create_save_button(self, image_path: str):
        """Create a save button for generated images."""
        btn_save = Gtk.Button()
        button_size = self.font_size * 2
        btn_save.set_size_request(button_size, button_size)
        
        icon_save = Gtk.Image.new_from_icon_name("document-save-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        btn_save.set_image(icon_save)
        btn_save.set_tooltip_text("Save image to file")
        btn_save.connect("clicked", lambda w: self.save_image_to_file(image_path))
        
        return btn_save

    def create_copy_button(self, message_index: int):
        """Create a copy button to copy message text to clipboard."""
        btn_copy = Gtk.Button()
        button_size = self.font_size * 2
        btn_copy.set_size_request(button_size, button_size)
        
        icon_copy = Gtk.Image.new_from_icon_name("edit-copy-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        btn_copy.set_image(icon_copy)
        btn_copy.set_tooltip_text("Copy message to clipboard")
        
        def on_copy_clicked(widget):
            if message_index < len(self.conversation_history):
                text = self.conversation_history[message_index].get('content', '')
                clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
                clipboard.set_text(text, -1)
        
        btn_copy.connect("clicked", on_copy_clicked)
        return btn_copy

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
        """Get cache path - delegated to AudioService."""
        provider = getattr(self, 'tts_voice_provider', 'openai') or 'openai'
        voice = getattr(self, 'tts_voice', None) or 'alloy'
        model = "tts-1-hd" if provider == 'openai' and self.tts_hd else "tts-1"
        return self.controller.audio_service._get_cache_path(
            self.controller.audio_service._clean_tts_text(text),
            chat_id, f"{provider}_{model}", voice
        )

    def _synthesize_and_play_tts(self, text: str, *, chat_id: str, stop_event: threading.Event = None) -> bool:
        """Synthesize text using OpenAI TTS and play it."""
        provider = self.controller.get_provider('openai')
        if not provider:
            print("TTS: OpenAI provider not available")
            return False
        
        result = self.controller.audio_service.synthesize_and_play(
            text=text,
            provider_type='openai',
            provider=provider,
            stop_event=stop_event,
            chat_id=chat_id,
            voice=getattr(self, 'tts_voice', 'alloy'),
            model='tts-1-hd' if self.tts_hd else 'tts-1',
        )
        return result

    def _synthesize_and_play_audio_preview(self, text: str, *, chat_id: str, model_id: str, stop_event: threading.Event = None) -> bool:
        """Synthesize text using audio-preview models."""
        provider = self.controller.get_provider('openai')
        if not provider:
            print("TTS: OpenAI provider not available for audio-preview")
            return False
        
        return self.controller.audio_service.synthesize_and_play(
            text=text,
            provider_type='audio_preview',
            provider=provider,
            stop_event=stop_event,
            chat_id=chat_id,
            model_id=model_id,
            voice=getattr(self, 'tts_voice', 'alloy'),
            prompt_template=getattr(self, 'tts_prompt_template', '') or 'Please say the following verbatim: "{text}"',
        )

    def _synthesize_and_play_gemini_tts(self, text: str, *, chat_id: str, stop_event: threading.Event = None) -> bool:
        """Synthesize text using Gemini TTS."""
        provider = self.controller.get_provider('gemini')
        if not provider:
            print("TTS: Gemini provider not available")
            return False
        
        return self.controller.audio_service.synthesize_and_play(
            text=text,
            provider_type='gemini',
            provider=provider,
            stop_event=stop_event,
            chat_id=chat_id,
            voice=getattr(self, 'tts_voice', 'Kore'),
            prompt_template=getattr(self, 'tts_prompt_template', ''),
        )

    def _synthesize_and_play_custom_tts(self, text: str, *, chat_id: str, model_id: str, stop_event: threading.Event = None) -> bool:
        """Synthesize text using custom TTS provider."""
        from ai_providers import CustomProvider
        from utils import resolve_api_key
        
        custom_models = getattr(self, 'custom_models', {}) or {}
        cfg = custom_models.get(model_id)
        if not cfg:
            print(f"TTS: Custom model '{model_id}' not found")
            return False
        
        # Determine voice
        selected_voice = getattr(self, 'tts_voice', None) or ''
        cfg_voice = (cfg.get('voice') or '').strip()
        cfg_voices = cfg.get('voices', [])
        if isinstance(cfg_voices, list):
            cfg_voices = [v.strip() for v in cfg_voices if isinstance(v, str) and v.strip()]
        voice = selected_voice.strip() or cfg_voice or (cfg_voices[0] if cfg_voices else "default")
        
        # Create provider
        provider = CustomProvider()
        provider.initialize(
            api_key=resolve_api_key(cfg.get('api_key', '')),
            endpoint=cfg.get('endpoint', ''),
            model_id=cfg.get('model_name') or cfg.get('model_id') or model_id,
            api_type='tts',
            voice=voice
        )
        
        return self.controller.audio_service.synthesize_and_play(
            text=text,
            provider_type='custom',
            provider=provider,
            stop_event=stop_event,
            chat_id=chat_id,
            voice=voice,
            model_id=model_id,
        )

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
