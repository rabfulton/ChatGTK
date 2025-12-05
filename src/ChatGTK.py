#!/usr/bin/env python3
import os
os.environ['AUDIODEV'] = 'pulse'  # Force use of PulseAudio
import gi
import json
import re
import threading
import os  # Import os to read/write environment variables and settings
import sounddevice as sd  # For recording audio
import soundfile as sf    # For saving audio files
import numpy as np       # For audio processing
import tempfile         # For temporary files
from pathlib import Path # For path handling
import subprocess
import mimetypes
import base64
import time
from latex_utils import (
    tex_to_png, 
    process_tex_markup, 
    insert_tex_image, 
    cleanup_temp_files, 
    is_latex_installed,
    export_chat_to_pdf
)
from utils import (
    load_settings, 
    save_settings, 
    generate_chat_name, 
    save_chat_history, 
    load_chat_history,
    list_chat_histories,
    get_chat_metadata,
    get_chat_title,
    get_chat_dir,
    delete_chat_history,
    parse_color_to_rgba,
    rgb_to_hex,
    insert_resized_image,
    apply_settings,
    get_object_settings,
    convert_settings_for_save
)
from ai_providers import get_ai_provider, OpenAIProvider, OpenAIWebSocketProvider
from markup_utils import (
    format_response,
    process_inline_markup,
    escape_for_pango_markup,
    process_text_formatting
)
from gi.repository import Gdk
from datetime import datetime
from config import BASE_DIR, PARENT_DIR, SETTINGS_CONFIG
from audio import record_audio
from tools import (
    ToolManager,
    is_chat_completion_model,
    append_tool_guidance,
    CHAT_COMPLETION_EXCLUDE_TERMS,
    SYSTEM_PROMPT_APPENDIX,
    IMAGE_TOOL_PROMPT_APPENDIX,
    MUSIC_TOOL_PROMPT_APPENDIX,
)
from dialogs import SettingsDialog, ToolsDialog, PromptEditorDialog
from conversation import (
    create_system_message,
    create_user_message,
    create_assistant_message,
    get_first_user_content,
)
# Initialize provider as None
ai_provider = None

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

        # Load settings
        loaded = load_settings()
        
        # Apply all settings as attributes
        apply_settings(self, loaded)
        
        # Initialize system prompts from settings (before conversation_history)
        self._init_system_prompts_from_settings()
        
        # Initialize window
        self.set_default_size(self.window_width, self.window_height)

        # Tray icon / indicator (created lazily when needed)
        self.tray_icon = None
        self.tray_menu = None
        # Flag to prevent minimize events during restoration
        self._restoring_from_tray = False

        # Initialize chat state
        self.current_chat_id = None  # None means this is a new, unsaved chat
        # Each message can carry optional provider-specific metadata in provider_meta.
        self.conversation_history = [create_system_message(self.system_message)]
        self.providers = {}
        self.model_provider_map = {}
        self.api_keys = {'openai': '', 'gemini': '', 'grok': '', 'claude': ''}
        
        # Initialize ToolManager with current settings
        self.tool_manager = ToolManager(
            image_tool_enabled=bool(getattr(self, "image_tool_enabled", True)),
            music_tool_enabled=bool(getattr(self, "music_tool_enabled", False)),
            read_aloud_tool_enabled=bool(getattr(self, "read_aloud_tool_enabled", False)),
        )

        # Remember the current geometry if not maximized
        self.current_geometry = (self.window_width, self.window_height)

        # Create main container
        main_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.add(main_hbox)

        # Create paned container
        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        
        main_hbox.pack_start(self.paned, True, True, 0)
        # Create sidebar
        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.sidebar.set_size_request(200, -1)
        self.sidebar.set_margin_top(10)
        self.sidebar.set_margin_bottom(10)
        self.sidebar.set_margin_start(10)
        self.sidebar.set_margin_end(10)

        # Add "New Chat" button at the top of sidebar
        new_chat_button = Gtk.Button(label="New Chat")
        new_chat_button.connect("clicked", self.on_new_chat_clicked)
        self.sidebar.pack_start(new_chat_button, False, False, 0)

        # Add scrolled window for history list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.sidebar.pack_start(scrolled, True, True, 0)
        
        # Create list box for chat histories
        self.history_list = Gtk.ListBox()
        self.history_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.history_list.connect('row-activated', self.on_history_selected)
        self.history_list.connect('button-press-event', self.on_history_button_press)
        
        # Add navigation-sidebar style class
        self.history_list.get_style_context().add_class('navigation-sidebar')
        
        scrolled.add(self.history_list)

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
        self.sidebar_button.set_relief(Gtk.ReliefStyle.NONE)
        arrow = Gtk.Arrow(arrow_type=Gtk.ArrowType.RIGHT, shadow_type=Gtk.ShadowType.NONE)
        self.sidebar_button.add(arrow)
        self.sidebar_button.connect("clicked", self.on_sidebar_toggle)
        hbox_top.pack_start(self.sidebar_button, False, False, 0)

        # Initialize model combo before trying to use it
        self.combo_model = Gtk.ComboBoxText()
        self.combo_model.connect('changed', self.on_model_changed)
        
        # Check for API keys in environment variables and initialize providers if they exist
        env_openai_key = os.environ.get('OPENAI_API_KEY', '').strip()
        env_gemini_key = os.environ.get('GEMINI_API_KEY', '').strip()
        env_grok_key = os.environ.get('GROK_API_KEY', '').strip()
        # Support both CLAUDE_API_KEY (app-specific) and ANTHROPIC_API_KEY (per docs
        # at `https://platform.claude.com/docs/en/api/openai-sdk`) for Claude.
        env_claude_key = (
            os.environ.get('CLAUDE_API_KEY', '').strip()
            or os.environ.get('ANTHROPIC_API_KEY', '').strip()
        )
        if env_openai_key:
            self.api_keys['openai'] = env_openai_key
            self.initialize_provider('openai', env_openai_key)
        if env_gemini_key:
            self.api_keys['gemini'] = env_gemini_key
            self.initialize_provider('gemini', env_gemini_key)
        if env_grok_key:
            self.api_keys['grok'] = env_grok_key
            self.initialize_provider('grok', env_grok_key)
        if env_claude_key:
            self.api_keys['claude'] = env_claude_key
            # Ensure both environment variables are set for consistency.
            os.environ['CLAUDE_API_KEY'] = env_claude_key
            os.environ['ANTHROPIC_API_KEY'] = env_claude_key
            self.initialize_provider('claude', env_claude_key)
        
        if self.providers:
            self.fetch_models_async()
        else:
            default_models = self._default_models_for_provider('openai')
            self.model_provider_map = {model: 'openai' for model in default_models}
            self.update_model_list(default_models, self.default_model)

        hbox_top.pack_start(self.combo_model, False, False, 0)

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

        # Scrolled window for conversation
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_vexpand(True)
        vbox_main.pack_start(scrolled_window, True, True, 0)

        # Conversation box – we will add each message as a separate widget
        self.conversation_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.conversation_box.set_margin_start(5)
        self.conversation_box.set_margin_end(5)
        self.conversation_box.set_margin_top(5)
        self.conversation_box.set_margin_bottom(5)
        scrolled_window.add(self.conversation_box)

        # Question input, prompt editor button, and send button
        hbox_input = Gtk.Box(spacing=6)

        self.entry_question = Gtk.Entry()
        self.entry_question.set_placeholder_text("Enter your question here...")
        self.entry_question.connect("activate", self.on_submit)

        # Button to open a larger prompt editor dialog
        btn_edit_prompt = Gtk.Button()
        btn_edit_prompt.set_tooltip_text("Open prompt editor")
        edit_icon = Gtk.Image.new_from_icon_name("document-edit-symbolic", Gtk.IconSize.BUTTON)
        btn_edit_prompt.add(edit_icon)
        btn_edit_prompt.set_relief(Gtk.ReliefStyle.NONE)
        btn_edit_prompt.connect("clicked", self.on_open_prompt_editor)

        btn_send = Gtk.Button(label="Send")
        btn_send.connect("clicked", self.on_submit)

        hbox_input.pack_start(self.entry_question, True, True, 0)
        hbox_input.pack_start(btn_edit_prompt, False, False, 0)
        hbox_input.pack_start(btn_send, False, False, 0)
        vbox_main.pack_start(hbox_input, False, False, 0)

        # Create horizontal box for buttons
        button_box = Gtk.Box(spacing=6)

        # Voice input button with recording state
        self.recording = False
        self.attached_file_path = None
        self.btn_voice = Gtk.Button(label="Start Voice Input")
        self.btn_voice.connect("clicked", self.on_voice_input)
        
        # Add voice button to horizontal box
        button_box.pack_start(self.btn_voice, True, True, 0)

        # Attach File button
        self.btn_attach = Gtk.Button(label="Attach File")
        self.btn_attach.connect("clicked", self.on_attach_file)
        button_box.pack_start(self.btn_attach, True, True, 0)

        vbox_main.pack_start(button_box, False, False, 0)

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

        # Connect window event handlers
        self.connect("configure-event", self.on_configure_event)
        self.connect("delete-event", self.on_delete_event)
        self.connect("window-state-event", self.on_window_state_event)
        self.connect("destroy", self.on_destroy)

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
            
        # Save all settings including sidebar width
        to_save = get_object_settings(self)
        to_save['WINDOW_WIDTH'] = self.current_geometry[0]
        to_save['WINDOW_HEIGHT'] = self.current_geometry[1]
        to_save['SIDEBAR_WIDTH'] = self.current_sidebar_width
        save_settings(convert_settings_for_save(to_save))
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

    def update_model_list(self, models, current_model=None):
        """Update the model combo box with fetched models."""
        if not models:
            models = self._default_models_for_provider('openai')
            self.model_provider_map = {model: 'openai' for model in models}
        
        active_model = current_model or self.combo_model.get_active_text()
        if not active_model or active_model not in models:
            preferred_default = self.default_model if self.default_model in models else None
            active_model = preferred_default or models[0]
        
        self._updating_model = True
        try:
            self.combo_model.remove_all()
            if active_model in models:
                self.combo_model.append_text(active_model)
            other_models = sorted([m for m in models if m != active_model])
            for model in other_models:
                self.combo_model.append_text(model)
            self.combo_model.set_active(0)
        finally:
            self._updating_model = False
        return False

    def on_model_changed(self, combo):
        """Handle model selection changes."""
        # Check if we're already updating to avoid recursive calls.
        if getattr(self, '_updating_model', False):
            return
        self._updating_model = True
        try:
            # Get newly selected model
            selected_model = combo.get_active_text()
            if not selected_model:
                return

            # Get all models directly from the combo box
            model_store = combo.get_model()
            models = []
            iter = model_store.get_iter_first()
            while iter:
                models.append(model_store.get_value(iter, 0))
                iter = model_store.iter_next(iter)

            # Update the list with new order
            combo.remove_all()

            # Add the selected model first
            combo.append_text(selected_model)

            # Add other models alphabetically, excluding the selected model
            other_models = sorted(m for m in models if m != selected_model)
            for model in other_models:
                combo.append_text(model)

            # Set active to the first item (the selected model)
            combo.set_active(0)
        finally:
            self._updating_model = False

    # -----------------------------------------------------------------------
    # System prompts management
    # -----------------------------------------------------------------------

    def _init_system_prompts_from_settings(self):
        """
        Initialize system prompts from settings.
        
        Parses SYSTEM_PROMPTS_JSON and sets up self.system_prompts (list of dicts)
        and self.active_system_prompt_id. Also updates self.system_message to
        the active prompt's content for backward compatibility.
        """
        prompts = []
        raw = getattr(self, "system_prompts_json", "") or ""
        if raw.strip():
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    for p in parsed:
                        if isinstance(p, dict) and "id" in p and "name" in p and "content" in p:
                            prompts.append(p)
            except json.JSONDecodeError:
                pass
        
        # Fallback: synthesize a single prompt from system_message
        if not prompts:
            prompts = [{
                "id": "default",
                "name": "Default",
                "content": getattr(self, "system_message", "You are a helpful assistant.")
            }]
        
        self.system_prompts = prompts
        
        # Determine active prompt ID
        active_id = getattr(self, "active_system_prompt_id", "") or ""
        valid_ids = {p["id"] for p in self.system_prompts}
        if active_id not in valid_ids:
            active_id = self.system_prompts[0]["id"] if self.system_prompts else ""
        self.active_system_prompt_id = active_id
        
        # Update system_message to the active prompt's content
        active_prompt = self._get_system_prompt_by_id(active_id)
        if active_prompt:
            self.system_message = active_prompt["content"]

    def _get_system_prompt_by_id(self, prompt_id):
        """Return the system prompt dict with the given ID, or None."""
        for p in getattr(self, "system_prompts", []):
            if p["id"] == prompt_id:
                return p
        return None

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
        save_settings(convert_settings_for_save(get_object_settings(self)))

    def fetch_models_async(self):
        """Fetch available models asynchronously."""
        # Check if filtering should be disabled via environment variable
        env_val = os.getenv('DISABLE_MODEL_FILTER', '')
        disable_filter = env_val.strip().lower() in ('true', '1', 'yes')

        # Gather whitelist sets from settings (parsed from comma-separated strings)
        whitelists = {}
        for provider_key in ('openai', 'gemini', 'grok', 'claude'):
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

            if not collected_models:
                collected_models = self._default_models_for_provider('openai')
                mapping = {model: 'openai' for model in collected_models}

            unique_models = sorted(dict.fromkeys(collected_models))
            GLib.idle_add(self.apply_model_fetch_results, unique_models, mapping)

        # Start fetch in background
        threading.Thread(target=fetch_thread, daemon=True).start()

    def _default_models_for_provider(self, provider_name):
        if provider_name == 'gemini':
            return ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-3-pro-preview"]
        if provider_name == 'grok':
            # Basic Grok chat and image models
            return ["grok-2", "grok-2-mini", "grok-2-image-1212"]
        if provider_name == 'claude':
            # Basic Claude chat models via the OpenAI SDK compatibility layer.
            # See `https://platform.claude.com/docs/en/api/openai-sdk`.
            return ["claude-sonnet-4-5", "claude-3-5-sonnet-latest"]
        return ["gpt-3.5-turbo", "gpt-4", "gpt-4o-mini"]

    def initialize_provider(self, provider_name, api_key):
        """Initialize and cache providers when keys change.

        This reuses existing provider instances so that any internal caches
        (such as uploaded file IDs) are preserved across calls, and only
        reinitializes when the API key actually changes.
        """
        global ai_provider
        api_key = (api_key or "").strip()
        self.api_keys[provider_name] = api_key

        # If the key was cleared, drop the provider.
        if not api_key:
            self.providers.pop(provider_name, None)
            if provider_name == 'openai':
                ai_provider = None
            return None

        # Reuse an existing provider instance when available so caches survive.
        provider = self.providers.get(provider_name)
        if provider is None:
            provider = get_ai_provider(provider_name)

        # Let the provider decide how to handle key changes (e.g., clear caches).
        provider.initialize(api_key)
        self.providers[provider_name] = provider

        if provider_name == 'openai':
            ai_provider = provider
        return provider

    def _get_conversation_buffer_limit(self):
        """
        Return the configured conversation buffer length as an integer.

        Returns:
            None: send the full conversation history (ALL).
            0:    send only the latest non-system message.
            N>0:  send the last N non-system messages.
        """
        raw = getattr(self, "conversation_buffer_length", None)
        if raw is None:
            return None

        # Accept both numeric and string values for robustness.
        if isinstance(raw, (int, float)):
            value = int(raw)
            return max(value, 0)

        text = str(raw).strip()
        if not text:
            return None

        if text.upper() == "ALL":
            return None

        try:
            value = int(text)
            return max(value, 0)
        except ValueError:
            print(f"Invalid CONVERSATION_BUFFER_LENGTH value '{raw}', defaulting to ALL.")
            return None

    def _apply_conversation_buffer_limit(self, history):
        """
        Apply the configured conversation buffer length to the given history.

        The system message (first entry) is always preserved when present.
        """
        if not history:
            return history

        limit = self._get_conversation_buffer_limit()
        if limit is None or len(history) <= 1:
            # No limit configured, or only system + one message.
            return history

        first = history[0]
        non_system = history[1:]
        if not non_system:
            return history

        if limit == 0:
            trimmed = [non_system[-1]]
        else:
            trimmed = non_system[-limit:]

        return [first] + trimmed

    def _messages_for_model(self, model_name):
        """
        Return the conversation history, appending additional system guidance for
        certain models:
        - SYSTEM_PROMPT_APPENDIX for standard chat completion models.
        - Tool-specific guidance when tools are available.
        """
        if not self.conversation_history:
            return []

        # For non-chat-completion models, we still respect the buffer limit but
        # skip any extra system guidance.
        if not is_chat_completion_model(model_name):
            return self._apply_conversation_buffer_limit(self.conversation_history)

        first_message = self.conversation_history[0]
        if first_message.get("role") != "system":
            return self._apply_conversation_buffer_limit(self.conversation_history)

        current_prompt = first_message.get("content", "") or ""

        # Get enabled tools for this model and append guidance using the tools module.
        try:
            enabled_tools = self.tool_manager.get_enabled_tools_for_model(
                model_name, self.model_provider_map
            )
            new_prompt = append_tool_guidance(current_prompt, enabled_tools, include_math=True)
        except Exception as e:
            print(f"Error while appending tool guidance: {e}")
            new_prompt = current_prompt

        # Start from the current conversation history and apply the buffer limit.
        limited_history = self._apply_conversation_buffer_limit(self.conversation_history)

        # If nothing changed in the prompt, just return the (possibly trimmed) history.
        if new_prompt == current_prompt:
            return limited_history

        messages = [msg.copy() for msg in limited_history]
        messages[0]["content"] = new_prompt
        return messages

    def get_provider_name_for_model(self, model_name):
        if not model_name:
            return 'openai'
        # If we have an explicit mapping from model fetch, use it.
        provider = self.model_provider_map.get(model_name)
        if provider:
            return provider

        # Fall back to simple heuristics for well-known image and chat models,
        # so image-only models can be routed correctly even if they are not
        # present in the main model list.
        lower = model_name.lower()
        if lower.startswith("gemini-"):
            return "gemini"
        if lower.startswith("grok-"):
            return "grok"
        if lower.startswith("claude-"):
            return "claude"

        return 'openai'

    def _is_image_model_for_provider(self, model_name, provider_name):
        """
        Return True if the given model for the specified provider should be
        treated as an image-generation model.
        """
        return self.tool_manager.is_image_model_for_provider(model_name, provider_name)

    def _supports_image_tools(self, model_name):
        """
        Return True if the given model should be offered the image-generation
        tool. Delegates to ToolManager.
        """
        return self.tool_manager.supports_image_tools(model_name, self.model_provider_map)

    def _supports_music_tools(self, model_name):
        """
        Return True if the given model should be offered the music-control tool.
        Delegates to ToolManager.
        """
        return self.tool_manager.supports_music_tools(model_name, self.model_provider_map)

    def _supports_read_aloud_tools(self, model_name):
        """
        Return True if the given model should be offered the read-aloud tool.
        Delegates to ToolManager.
        """
        return self.tool_manager.supports_read_aloud_tools(model_name, self.model_provider_map)

    def _normalize_image_tags(self, text):
        """
        Normalize any <img ...> tags emitted by models into the self-closing
        <img src="..."/> form that the UI expects, stripping any extra
        attributes like alt= so they are not shown as raw markup. If the same
        image src appears multiple times, keep only the first occurrence to
        avoid displaying duplicate images.
        """
        if not text:
            return text
        import re
        pattern = re.compile(r'<img\s+src="([^"]+)"[^>]*>', re.IGNORECASE)

        result_parts = []
        last_end = 0
        seen_src = set()

        for match in pattern.finditer(text):
            # Add any text before this tag unchanged.
            result_parts.append(text[last_end:match.start()])
            src = match.group(1)

            if src in seen_src:
                # Skip duplicate image tags for the same src.
                replacement = ""
            else:
                seen_src.add(src)
                replacement = f'<img src="{src}"/>'

            result_parts.append(replacement)
            last_end = match.end()

        # Add any remaining text after the last tag.
        result_parts.append(text[last_end:])
        return "".join(result_parts)

    def generate_image_for_model(self, model, prompt, last_msg, chat_id, provider_name, has_attached_images):
        """
        Central helper to generate an image for any supported provider/model
        combination, reusing the underlying provider-specific generate_image
        implementations and attachment semantics.
        """
        provider = self.providers.get(provider_name)
        if not provider:
            api_key = os.environ.get(f"{provider_name.upper()}_API_KEY", self.api_keys.get(provider_name, "")).strip()
            provider = self.initialize_provider(provider_name, api_key)
            if not provider:
                raise ValueError(f"{provider_name.title()} provider is not initialized")

        # OpenAI image models.
        if provider_name == 'openai':
            image_data = None
            if model in ("gpt-image-1", "gpt-image-1-mini") and has_attached_images:
                image_data = last_msg["images"][0]["data"]
            return provider.generate_image(prompt, chat_id, model, image_data)

        # Gemini image models support both text→image and image→image.
        if provider_name == 'gemini':
            if model in ["gemini-3-pro-image-preview", "gemini-2.5-flash-image"] and has_attached_images:
                img = last_msg["images"][0]
                return provider.generate_image(
                    prompt,
                    chat_id,
                    model,
                    image_data=img["data"],
                    mime_type=img.get("mime_type")
                )
            return provider.generate_image(prompt, chat_id, model)

        # Grok image models are currently text → image only.
        if provider_name == 'grok':
            return provider.generate_image(prompt, chat_id, model)

        raise ValueError(f"Image generation not supported for provider: {provider_name}")

    def generate_image_via_preferred_model(self, prompt, last_msg):
        """
        Generate an image using the user-configured preferred image model,
        falling back to a safe OpenAI default if necessary.
        """
        preferred_model = getattr(self, "image_model", None) or "dall-e-3"
        provider_name = self.get_provider_name_for_model(preferred_model)

        # Ensure the preferred model is recognized as an image model; otherwise
        # fall back to a known-safe default.
        if not self._is_image_model_for_provider(preferred_model, provider_name):
            preferred_model = "dall-e-3"
            provider_name = "openai"

        try:
            return self.generate_image_for_model(
                model=preferred_model,
                prompt=prompt or last_msg.get("content", "") or "",
                last_msg=last_msg,
                chat_id=self.current_chat_id or "temp",
                provider_name=provider_name,
                has_attached_images="images" in last_msg and last_msg["images"],
            )
        except Exception as e:
            # If the preferred provider/model fails (e.g., missing key), fall
            # back to OpenAI dall-e-3 as a last resort.
            print(f"Preferred image model failed ({preferred_model} via {provider_name}): {e}")
            fallback_model = "dall-e-3"
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
        # Try to use playerctl if available, targeting the configured player
        player_name = os.path.basename(player_path)
        
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
        to the user. It uses the same read_aloud_text method but blocks until
        playback is complete so the tool returns a proper status.
        """
        if not text:
            return "No text provided to read aloud."
        
        try:
            # Get the provider setting
            provider = getattr(self, 'read_aloud_provider', 'tts') or 'tts'
            
            if provider == 'tts':
                success = self._synthesize_and_play_tts(
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
            else:
                return f"Unknown read aloud provider: {provider}"
            
            if success:
                return "Text was read aloud successfully."
            else:
                return "Failed to read text aloud."
        except Exception as e:
            return f"Error reading aloud: {e}"

    def apply_model_fetch_results(self, models, mapping):
        if mapping:
            self.model_provider_map = mapping
        current_model = self.combo_model.get_active_text() or self.default_model
        self.update_model_list(models, current_model)

        # Also ensure the Image Model dropdown includes any image-capable models
        # that were discovered dynamically from providers.
        try:
            # Only update if combo_image_model exists (i.e., when settings dialog is open)
            if hasattr(self, 'combo_image_model') and self.combo_image_model is not None:
                image_like_models = []
                for model_id in models or []:
                    lower = model_id.lower()
                    if any(term in lower for term in ("dall-e", "gpt-image", "image-")):
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
        current_api_keys = {
            'openai': os.environ.get('OPENAI_API_KEY', self.api_keys.get('openai', '')),
            'gemini': os.environ.get('GEMINI_API_KEY', self.api_keys.get('gemini', '')),
            'grok': os.environ.get('GROK_API_KEY', self.api_keys.get('grok', '')),
            'claude': os.environ.get('CLAUDE_API_KEY', self.api_keys.get('claude', '')),
        }

        # Pass ai_provider, providers dict, and api_keys to the settings dialog
        dialog = SettingsDialog(
            self,
            ai_provider=ai_provider,
            providers=self.providers,
            api_keys=current_api_keys,
            **{k.lower(): getattr(self, k.lower()) for k in SETTINGS_CONFIG.keys()}
        )
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            new_settings = dialog.get_settings()
            apply_settings(self, new_settings)
            save_settings(convert_settings_for_save(get_object_settings(self)))

            # Re-initialize system prompts from updated settings and refresh the combo
            self._init_system_prompts_from_settings()
            self._refresh_system_prompt_combo()
            
            # Update the system message in the current conversation if it exists
            if self.conversation_history and self.conversation_history[0].get("role") == "system":
                self.conversation_history[0]["content"] = self.system_message

            # Keep the ToolManager in sync with any updated tool options.
            self.tool_manager.image_tool_enabled = bool(getattr(self, "image_tool_enabled", True))
            self.tool_manager.music_tool_enabled = bool(getattr(self, "music_tool_enabled", False))
            self.tool_manager.read_aloud_tool_enabled = bool(getattr(self, "read_aloud_tool_enabled", False))

            # Handle API keys from the dialog
            new_keys = dialog.get_api_keys()
            self._apply_api_keys(new_keys)

            self.fetch_models_async()
        dialog.destroy()

    def on_open_prompt_editor(self, widget):
        """Open a larger dialog for composing a more complex prompt."""
        initial_text = self.entry_question.get_text()

        dialog = PromptEditorDialog(self, initial_text=initial_text)
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            text = dialog.get_text().strip()
            self.entry_question.set_text(text)

        dialog.destroy()

    def _apply_api_keys(self, new_keys):
        """Apply API key changes: update stored keys, environment, and providers."""
        # Update stored keys
        self.api_keys['openai'] = new_keys['openai']
        self.api_keys['gemini'] = new_keys['gemini']
        self.api_keys['grok'] = new_keys['grok']
        self.api_keys['claude'] = new_keys['claude']

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

    def on_open_tools(self, widget):
        # Open the tools dialog for configuring image/music tools.
        dialog = ToolsDialog(self, **{k.lower(): getattr(self, k.lower())
                               for k in SETTINGS_CONFIG.keys()})
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            tool_settings = dialog.get_tool_settings()
            # Apply the updated tool settings to the main window object.
            for key, value in tool_settings.items():
                setattr(self, key, value)
            # Enforce mutual exclusivity: if read_aloud_tool is enabled, disable auto-read
            if getattr(self, "read_aloud_tool_enabled", False) and getattr(self, "read_aloud_enabled", False):
                self.read_aloud_enabled = False
            # Update the ToolManager with the new settings.
            self.tool_manager.image_tool_enabled = bool(getattr(self, "image_tool_enabled", True))
            self.tool_manager.music_tool_enabled = bool(getattr(self, "music_tool_enabled", False))
            self.tool_manager.read_aloud_tool_enabled = bool(getattr(self, "read_aloud_tool_enabled", False))
            # Persist all settings, including the updated tool flags.
            save_settings(convert_settings_for_save(get_object_settings(self)))
        dialog.destroy()

    def append_user_message(self, text):
        """Add a user message as a label with user style."""
        lbl = Gtk.Label()
        lbl.set_selectable(True)
        lbl.set_line_wrap(True)
        lbl.set_line_wrap_mode(Gtk.WrapMode.WORD)
        lbl.set_xalign(0)  # left align
        # Set margins
        lbl.set_margin_start(0)
        lbl.set_margin_end(0)
        lbl.set_margin_top(5)
        lbl.set_margin_bottom(5)
        # Set font color and padding
        css = f"label {{ color: {self.user_color}; font-family: {self.font_family}; font-size: {self.font_size}pt; background-color: @theme_base_color; border-radius: 12px; padding: 10px; }}"
        self.apply_css(lbl, css)

        lbl.set_text(f"You: {text}")
        self.conversation_box.pack_start(lbl, False, False, 0)
        self.conversation_box.show_all()

    def append_ai_message(self, message_text):
        # Container for the entire AI response (including play/stop button)
        response_container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        
        # Container for the text content
        content_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
         
        # Style the container to the same color as the background
        css_container = f"""
            box {{
                background-color: @theme_base_color;
                padding: 12px;
                border-radius: 12px;
            }}
        """
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(css_container.encode())
        content_container.get_style_context().add_provider(
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        # First, show a label with the AI name.
        lbl_name = Gtk.Label()
        lbl_name.set_selectable(True)
        lbl_name.set_line_wrap(True)
        lbl_name.set_line_wrap_mode(Gtk.WrapMode.WORD)
        lbl_name.set_xalign(0)
        css_ai = f"label {{ color: {self.ai_color}; font-family: {self.font_family}; font-size: {self.font_size}pt; background-color: @theme_base_color;}}"
        self.apply_css(lbl_name, css_ai)
        lbl_name.set_text(f"{self.ai_name}:")
        content_container.pack_start(lbl_name, False, False, 0)
        
        # Process message_text to add formatted text and (if needed) code blocks.
        full_text = []
        
        pattern = r'(--- Code Block Start \(.*?\) ---\n.*?\n--- Code Block End ---|--- Table Start ---\n.*?\n--- Table End ---|---HORIZONTAL-LINE---)'
        segments = re.split(pattern, message_text, flags=re.DOTALL)
        for seg in segments:
            if seg.startswith('--- Code Block Start ('):
                lang_match = re.search(r'^--- Code Block Start \((.*?)\) ---', seg)
                code_lang = lang_match.group(1) if lang_match else "plaintext"
                code_content = re.sub(r'^--- Code Block Start \(.*?\) ---', '', seg)
                code_content = re.sub(r'--- Code Block End ---$', '', code_content).strip('\n')
                source_view = create_source_view(code_content, code_lang, self.font_size, self.source_theme)
                frame = Gtk.Frame()
                frame.add(source_view)
                content_container.pack_start(frame, False, False, 5)
                full_text.append("Code block follows.")
            elif seg.startswith('--- Table Start ---'):
                table_content = re.sub(r'^--- Table Start ---\n?', '', seg)
                table_content = re.sub(r'\n?--- Table End ---$', '', table_content).strip()
                table_widget = self.create_table_widget(table_content)
                if table_widget:
                    content_container.pack_start(table_widget, False, False, 0)
                else:
                    fallback_label = Gtk.Label()
                    fallback_label.set_selectable(True)
                    fallback_label.set_line_wrap(True)
                    fallback_label.set_line_wrap_mode(Gtk.WrapMode.WORD)
                    fallback_label.set_xalign(0)
                    self.apply_css(fallback_label, css_ai)
                    fallback_label.set_text(table_content)
                    content_container.pack_start(fallback_label, False, False, 0)
                full_text.append(table_content)
            elif seg.strip() == '---HORIZONTAL-LINE---':
                # Create a horizontal separator widget and style it to match text color
                separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
                # CSS to set separator color to match the text color (self.ai_color)
                separator_css = f"""
                    separator {{
                        background-color: {self.ai_color};
                        color: {self.ai_color};
                        min-height: 2px;
                        margin-top: 8px;
                        margin-bottom: 8px;
                    }}
                """
                css_provider = Gtk.CssProvider()
                css_provider.load_from_data(separator_css.encode())
                separator.get_style_context().add_provider(
                    css_provider, 
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )
                content_container.pack_start(separator, False, False, 10)  # Add some margin
                full_text.append("Horizontal line.")
            else:
                 # For text segments that follow a code block
                if seg.startswith('\n'):
                    seg = seg[1:]
                # For text segments that precede a code block    
                if seg.endswith('\n'):
                    seg = seg[:-1]
                    
                if seg.strip():
                    processed = process_tex_markup(seg, self.latex_color, self.current_chat_id, self.source_theme, self.latex_dpi)
                    
                    if "<img" in processed:
                        text_view = Gtk.TextView()
                        text_view.set_wrap_mode(Gtk.WrapMode.WORD)
                        text_view.set_editable(False)
                        text_view.set_cursor_visible(False)
                        text_view.set_hexpand(True)  # Make it expand horizontally
                        #text_view.set_vexpand(True)
                        text_view.set_size_request(100, -1)  # Set minimum width to 10px, natural height
                        css_provider = Gtk.CssProvider()
                        css = f"""
                            textview {{
                                font-family: {self.font_family};
                                font-size: {self.font_size}pt;
                            }}
                            textview text {{
                                color: {self.ai_color};
                            }}
                        """
                        css_provider.load_from_data(css.encode())
                        text_view.get_style_context().add_provider(
                            css_provider,
                            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                        )
                        buffer = text_view.get_buffer()
                        parts = re.split(r'(<img src="[^"]+"/>)', processed)
                        iter = buffer.get_start_iter()
                        for part in parts:
                            if part.startswith('<img src="'):
                                img_path = re.search(r'src="([^"]+)"', part).group(1)
                                # LaTeX math images stay at their natural (small) size
                                if self._is_latex_math_image(img_path):
                                    insert_tex_image(buffer, iter, img_path)
                                else:
                                    # Model-generated or other non-math images resize with chat width
                                    insert_resized_image(buffer, iter, img_path, text_view)
                            else:
                                text = process_text_formatting(part, self.font_size)
                                buffer.insert_markup(iter, text, -1)
                        content_container.pack_start(text_view, False, False, 0)
                    else:
                        processed = process_inline_markup(processed, self.font_size)
                        lbl_ai_text = Gtk.Label()
                        lbl_ai_text.set_selectable(True)
                        lbl_ai_text.set_line_wrap(True)
                        lbl_ai_text.set_line_wrap_mode(Gtk.WrapMode.WORD)
                        lbl_ai_text.set_xalign(0)
                        self.apply_css(lbl_ai_text, css_ai)
                        lbl_ai_text.set_use_markup(True)
                        lbl_ai_text.set_markup(processed)
                        content_container.pack_start(lbl_ai_text, False, False, 0)
                    full_text.append(seg)
                    
        # Create the play/stop button using the new refactored method.
        speech_btn = self.create_speech_button(full_text)
        
        # Pack the content and the speech button into the response container.
        response_container.pack_start(content_container, True, True, 0)
        response_container.pack_end(speech_btn, False, False, 0)
        self.conversation_box.pack_start(response_container, False, False, 0)
        self.conversation_box.show_all()
        
        # Schedule scroll to the AI response after it's shown
        def scroll_to_response():
            # Find the ScrolledWindow by traversing up the widget hierarchy
            widget = self.conversation_box
            while widget and not isinstance(widget, Gtk.ScrolledWindow):
                widget = widget.get_parent()
            
            if widget:  # We found the ScrolledWindow
                adj = widget.get_vadjustment()
                # Get the position of the response container
                alloc = response_container.get_allocation()
                # Scroll to show the start of the response
                adj.set_value(alloc.y)
            return False
        
        GLib.idle_add(scroll_to_response)

    def apply_css(self, widget, css_string):
        """Apply the provided CSS string to a widget."""
        style_provider = Gtk.CssProvider()
        style_provider.load_from_data(css_string.encode("utf-8"))
        Gtk.StyleContext.add_provider(
            widget.get_style_context(),
            style_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_USER
        )

    def append_message(self, sender, message_text):
        if sender == 'user':
            self.append_user_message(message_text)
        else:
            self.append_ai_message(message_text)

    def on_submit(self, widget, event=None):
        question = self.entry_question.get_text().strip()
        if not question and not getattr(self, 'attached_file_path', None):
            return

        selected_model = self.combo_model.get_active_text()
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

        if quick_image_request:
            self.append_message('user', question)
            self.conversation_history.append(create_user_message(question))
            self.entry_question.set_text("")
            self.show_thinking_animation()
            threading.Thread(
                target=self.call_ai_api,
                args=(target_model,),
                daemon=True
            ).start()
            return

        # Check if we're in realtime mode
        if "realtime" in target_model.lower():
            if not hasattr(self, 'ws_provider'):
                self.ws_provider = OpenAIWebSocketProvider()
                # Connect to WebSocket server
                success = self.ws_provider.connect(
                    model=target_model,
                    system_message=self.system_message,
                    temperature=self.temperament,
                    voice=self.realtime_voice
                )
                if not success:
                    self.display_error("Failed to connect to WebSocket server")
                    return
                
            self.ws_provider.send_text(question, self.on_stream_content_received)
            self.append_message('user', question)
            self.entry_question.set_text("")
            return
        
        # ... existing non-realtime code ...
        # Use new method to append user message
        
        # Handle attachment - distinguish images from documents
        images = []
        files = []
        display_text = question
        
        if getattr(self, 'attached_file_path', None):
            try:
                mime_type, _ = mimetypes.guess_type(self.attached_file_path)
                if not mime_type:
                    mime_type = "application/octet-stream"
                
                filename = os.path.basename(self.attached_file_path)
                
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
                        files.append({
                            "path": self.attached_file_path,
                            "mime_type": mime_type,
                            "display_name": filename,
                        })
                    else:
                        # For other text-like documents (e.g. .txt, .md), inline the
                        # content into the user message instead of uploading a file.
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
                        # long prompts. Here we cap at ~32k characters.
                        max_chars = 32_000
                        if len(file_text) > max_chars:
                            file_text = file_text[:max_chars] + "\n\n[File content truncated]"

                        header = f"[File content from {filename}]\n"
                        if question:
                            question = question + "\n\n" + header + file_text
                        else:
                            question = header + file_text
                        display_text = question
                    
                # If this was a real attachment (PDF or image), show a simple marker.
                if not display_text or display_text == question:
                    # Only add an attachment marker when we didn't already inline content.
                    display_text = (question + f"\n[Attached: {filename}]") if question else f"[Attached: {filename}]"
                
                # Reset attachment
                self.attached_file_path = None
                self.btn_attach.set_label("Attach File")
                
            except Exception as e:
                print(f"Error processing file: {e}")
                display_text = question + f"\n[Error attaching file]"

        self.append_message('user', display_text)
        
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
        self.show_thinking_animation()
        
        # Call provider API in a separate thread
        threading.Thread(
            target=self.call_ai_api,
            args=(target_model,),
            daemon=True
        ).start()

    def call_ai_api(self, model):
        try:
            # Ensure we have a valid model
            if not model:
                model = "gpt-3.5-turbo"  # Default fallback
                print(f"No model selected, falling back to {model}")
            provider_name = self.get_provider_name_for_model(model)
            provider = self.providers.get(provider_name)
            if not provider:
                api_key = os.environ.get(f"{provider_name.upper()}_API_KEY", self.api_keys.get(provider_name, "")).strip()
                provider = self.initialize_provider(provider_name, api_key)
                if not provider:
                    raise ValueError(f"{provider_name.title()} provider is not initialized")
            
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
            elif provider_name == 'openai' and "realtime" in model.lower():
                # Realtime models are handled elsewhere (WebSocket provider).
                return
            elif provider_name == 'openai':
                messages_to_send = self._messages_for_model(model)

                # Provide handlers so OpenAI models can call tools (image/music/read_aloud)
                # autonomously when they decide it is helpful.
                last_user_msg = last_msg

                image_tool_handler = None
                music_tool_handler = None
                read_aloud_tool_handler = None

                if self._supports_image_tools(model):
                    def image_tool_handler(prompt_arg):
                        return self.generate_image_via_preferred_model(prompt_arg, last_user_msg)

                if self._supports_music_tools(model):
                    def music_tool_handler(action, keyword=None, volume=None):
                        return self.control_music_via_beets(action, keyword=keyword, volume=volume)

                if self._supports_read_aloud_tools(model):
                    def read_aloud_tool_handler(text):
                        return self._handle_read_aloud_tool(text)

                kwargs = {
                    "messages": messages_to_send,
                    "model": model,
                    "temperature": float(self.temperament),
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

                answer = provider.generate_chat_completion(**kwargs)
            elif provider_name == 'gemini':
                # Chat completion (possibly with image input or tool-based image generation)
                messages_to_send = self._messages_for_model(model)
                response_meta = {}

                last_user_msg = last_msg

                image_tool_handler = None
                music_tool_handler = None
                read_aloud_tool_handler = None

                if self._supports_image_tools(model):
                    def image_tool_handler(prompt_arg):
                        return self.generate_image_via_preferred_model(prompt_arg, last_user_msg)

                if self._supports_music_tools(model):
                    def music_tool_handler(action, keyword=None, volume=None):
                        return self.control_music_via_beets(action, keyword=keyword, volume=volume)

                if self._supports_read_aloud_tools(model):
                    def read_aloud_tool_handler(text):
                        return self._handle_read_aloud_tool(text)

                kwargs = {
                    "messages": messages_to_send,
                    "model": model,
                    "temperature": float(self.temperament),
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

                answer = provider.generate_chat_completion(**kwargs)

                assistant_provider_meta = response_meta or None
            elif provider_name == 'grok':
                # Standard chat completion for Grok, optionally with tools.
                messages_to_send = self._messages_for_model(model)

                last_user_msg = last_msg

                image_tool_handler = None
                music_tool_handler = None
                read_aloud_tool_handler = None

                if self._supports_image_tools(model):
                    def image_tool_handler(prompt_arg):
                        return self.generate_image_via_preferred_model(prompt_arg, last_user_msg)

                if self._supports_music_tools(model):
                    def music_tool_handler(action, keyword=None, volume=None):
                        return self.control_music_via_beets(action, keyword=keyword, volume=volume)

                if self._supports_read_aloud_tools(model):
                    def read_aloud_tool_handler(text):
                        return self._handle_read_aloud_tool(text)

                kwargs = {
                    "messages": messages_to_send,
                    "model": model,
                    "temperature": float(self.temperament),
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

                if self._supports_image_tools(model):
                    def image_tool_handler(prompt_arg):
                        return self.generate_image_via_preferred_model(prompt_arg, last_user_msg)

                if self._supports_music_tools(model):
                    def music_tool_handler(action, keyword=None, volume=None):
                        return self.control_music_via_beets(action, keyword=keyword, volume=volume)

                if self._supports_read_aloud_tools(model):
                    def read_aloud_tool_handler(text):
                        return self._handle_read_aloud_tool(text)

                kwargs = {
                    "messages": messages_to_send,
                    "model": model,
                    "temperature": float(self.temperament),
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

                answer = provider.generate_chat_completion(**kwargs)
            else:
                raise ValueError(f"Unsupported provider: {provider_name}")

            # Normalize any raw <img ...> tags so the UI can render them
            # consistently without showing stray HTML.
            answer = self._normalize_image_tags(answer)

            assistant_message = create_assistant_message(answer, provider_meta=assistant_provider_meta)

            self.conversation_history.append(assistant_message)

            # Update UI in main thread
            formatted_answer = format_response(answer)
            GLib.idle_add(self.hide_thinking_animation)
            GLib.idle_add(lambda: self.append_message('ai', formatted_answer))
            GLib.idle_add(self.save_current_chat)
            
            # Read aloud the response if enabled (runs in background thread)
            # Skip for audio models since they already play audio directly
            is_audio_model = "audio" in model.lower() and "preview" in model.lower()
            if not is_audio_model:
                self.read_aloud_text(formatted_answer, chat_id=self.current_chat_id)
            
        except Exception as error:
            print(f"\nAPI Call Error: {error}")
            GLib.idle_add(self.hide_thinking_animation)
            error_message = f"** Error: {str(error)} **"
            GLib.idle_add(lambda msg=error_message: self.append_message('ai', msg))
            
        finally:
            GLib.idle_add(self.hide_thinking_animation)

    def audio_transcription(self, widget):
        """Handle audio transcription."""
        print("Audio transcription...")
        openai_provider = self.providers.get('openai')
        if not openai_provider:
            api_key = os.environ.get('OPENAI_API_KEY', self.api_keys.get('openai', '')).strip()
            if api_key:
                os.environ['OPENAI_API_KEY'] = api_key
                openai_provider = self.initialize_provider('openai', api_key)
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
                        # Create a temporary file
                        temp_dir = Path(tempfile.gettempdir())
                        temp_file = temp_dir / "voice_input.wav"
                        
                        # Record audio using the function from audio.py
                        recording, sample_rate = record_audio(self.microphone, self.recording_event)
                        
                        # Only proceed if recording was successful
                        if recording is not None and sample_rate is not None:
                            try:
                                # Ensure recording is the right shape
                                if len(recording.shape) == 1:
                                    recording = recording.reshape(-1, 1)
                                
                                # Save to temporary file
                                sf.write(temp_file, recording, sample_rate)
                                
                                # Transcribe with Whisper
                                try:
                                    with open(temp_file, "rb") as audio_file:
                                        transcript = openai_provider.transcribe_audio(audio_file)
                                        
                                    # Add transcribed text to input
                                    GLib.idle_add(self.entry_question.set_text, transcript)
                                    
                                except Exception as e:
                                    GLib.idle_add(self.append_message, 'ai', f"Error transcribing audio: {str(e)}")
                            
                            except Exception as e:
                                GLib.idle_add(self.append_message, 'ai', f"Error saving audio: {str(e)}")
                            
                            finally:
                                # Clean up temp file
                                temp_file.unlink(missing_ok=True)
                        else:
                            GLib.idle_add(self.append_message, 'ai', "Error: Failed to record audio")
                    
                    except Exception as e:
                        GLib.idle_add(self.append_message, 'ai', f"Error in recording thread: {str(e)}")
                    
                    finally:
                        # Reset button state
                        GLib.idle_add(self.btn_voice.set_label, "Start Voice Input")
                        self.recording = False
                
                # Start recording in separate thread
                threading.Thread(target=record_thread, daemon=True).start()
                
            except Exception as e:
                self.append_message('ai', f"Error initializing audio system: {str(e)}")
                self.btn_voice.set_label("Start Voice Input")
                self.recording = False
        else:
            # Stop recording
            if hasattr(self, 'recording_event'):
                self.recording_event.clear()  # Signal recording to stop
            self.recording = False
            self.btn_voice.set_label("Start Voice Input")

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
            self.attached_file_path = dialog.get_filename()
            filename = os.path.basename(self.attached_file_path)
            self.btn_attach.set_label(f"Attached: {filename}")
            print(f"File selected: {self.attached_file_path}")
        
        dialog.destroy()

    def on_voice_input(self, widget):
        current_model = self.combo_model.get_active_text()

        if current_model is None or current_model == "":
            self.show_error_dialog("Please select a model before using voice input")
            return False

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
                        self.ws_provider = OpenAIWebSocketProvider()
                        self.ws_provider.microphone = self.microphone  # Pass selected microphone
                    
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
                        temperature=self.temperament,
                        voice=self.realtime_voice
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
                        temperature=self.temperament
                    )
                    
                except Exception as e:
                    print(f"Real-time streaming error: {e}")
                    self.append_message('ai', f"Error starting real-time streaming: {str(e)}")
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
                
                # Reset conversation state
                self.conversation_history = [create_system_message(self.system_message)]
                self.current_chat_id = None

            # Delete the chat history and associated files
            delete_chat_history(filename)
            
            # Refresh the history list
            self.refresh_history_list()


    def on_sidebar_toggle(self, button):
        """Toggle sidebar visibility."""
        if self.sidebar_visible:
            self.sidebar.hide()
            arrow = Gtk.Arrow(arrow_type=Gtk.ArrowType.RIGHT, shadow_type=Gtk.ShadowType.NONE)
        else:
            self.sidebar.show()
            arrow = Gtk.Arrow(arrow_type=Gtk.ArrowType.LEFT, shadow_type=Gtk.ShadowType.NONE)
        
        # Update button arrow
        old_arrow = button.get_child()
        button.remove(old_arrow)
        button.add(arrow)
        button.show_all()
        
        self.sidebar_visible = not self.sidebar_visible

    def on_new_chat_clicked(self, button):
        """Start a new chat conversation."""
        # Clear conversation history
        self.conversation_history = [create_system_message(self.system_message)]
        
        # Reset chat ID to indicate this is a new chat
        self.current_chat_id = None
        
        # Clear the conversation display
        for child in self.conversation_box.get_children():
            child.destroy()
        
        # Refresh the history list
        self.refresh_history_list()

    def refresh_history_list(self):
        """Refresh the list of chat histories in the sidebar."""
        # Clear existing items
        for child in self.history_list.get_children():
            self.history_list.remove(child)
        
        # Get histories from utils
        histories = list_chat_histories()

        for history in histories:
            row = Gtk.ListBoxRow()
            
            # Create vertical box for title and timestamp
            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            vbox.set_margin_start(10)
            vbox.set_margin_end(10)
            
            # Get chat title (will use custom title if it exists)
            title = get_chat_title(history['filename'])
            
            title_label = Gtk.Label(label=title, xalign=0)
            title_label.get_style_context().add_class('title')
            title_label.set_line_wrap(False)
            title_label.set_ellipsize(Pango.EllipsizeMode.END)
            
            # Timestamp label
            timestamp = self.get_chat_timestamp(history['filename'])
            time_label = Gtk.Label(label=timestamp, xalign=0)
            time_label.get_style_context().add_class('timestamp')
            
            vbox.pack_start(title_label, True, True, 0)
            vbox.pack_start(time_label, True, True, 0)
            
            row.add(vbox)
            row.filename = history['filename']
            
            self.history_list.add(row)
        
        self.history_list.show_all()

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

    def on_history_selected(self, listbox, row):
        """Handle selection of a chat history."""
        # Save current chat if it's new and has messages
        if self.current_chat_id is None and len(self.conversation_history) > 1:
            self.save_current_chat()
        
        # Load the selected chat history
        history = load_chat_history(row.filename, messages_only=True)  # Only get messages
        if history:
            # Update conversation history and chat ID
            self.conversation_history = history
            self.current_chat_id = row.filename
            
            # Set the model if it was saved with the chat
            if history and len(history) > 0 and "model" in history[0]:
                saved_model = history[0]["model"]
                # Find and set the model in combo box
                model_store = self.combo_model.get_model()
                for i in range(len(model_store)):
                    if model_store[i][0] == saved_model:
                        self.combo_model.set_active(i)
                        break
            
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
            
            # Rebuild conversation display with formatting
            for message in history:
                if message['role'] != 'system':  # Skip system message
                    if message['role'] == 'user':
                        self.append_message('user', message['content'])
                    elif message['role'] == 'assistant':
                        formatted_content = format_response(message['content'])
                        self.append_message('ai', formatted_content)

    def save_current_chat(self):
        """Save the current chat history."""
        if len(self.conversation_history) > 1:  # More than just the system message
            # Check if the chat already has a model name
            if len(self.conversation_history) > 0 and "model" in self.conversation_history[0]:
                current_model = self.conversation_history[0]["model"]
            else:
                current_model = self.combo_model.get_active_text()

            # Only store the model name if it's not dall-e-3 and does not contain "tts" or "audio"
            if "dall-e" not in current_model.lower() and "tts" not in current_model.lower() and "audio" not in current_model.lower():
                self.conversation_history[0]["model"] = current_model

            # TODO: This may be reduntant
            if self.current_chat_id is None:
                # New chat - generate name and save
                chat_name = generate_chat_name(self.conversation_history[1]['content'])
                self.current_chat_id = chat_name
            else:
                # Existing chat - use current ID
                chat_name = self.current_chat_id
            
            try:
                # Get any existing metadata before saving
                metadata = get_chat_metadata(chat_name)
                save_chat_history(chat_name, self.conversation_history, metadata)
            except Exception as e:
                print(f"Error preserving metadata: {e}")
                # Fall back to original save behavior
                save_chat_history(chat_name, self.conversation_history)
            
            self.refresh_history_list()

    def show_thinking_animation(self):
        """Show an animated thinking indicator."""
        # Remove any existing thinking animation first
        if hasattr(self, 'thinking_label') and self.thinking_label:
            self.thinking_label.destroy()
            self.thinking_label = None
        
        # Create new thinking label
        self.thinking_label = Gtk.Label()
        hex_color = rgb_to_hex(self.ai_color)
        self.thinking_label.set_markup(f"<span color='{hex_color}'>{self.ai_name} is thinking</span>")
        self.conversation_box.pack_start(self.thinking_label, False, False, 0)
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
        
        self.thinking_dots = 0
        
        def update_dots():
            if hasattr(self, 'thinking_label') and self.thinking_label:
                self.thinking_dots = (self.thinking_dots + 1) % 4
                dots = "." * self.thinking_dots
                hex_color = rgb_to_hex(self.ai_color)
                self.thinking_label.set_markup(
                    f"<span color='{hex_color}'>{self.ai_name} is thinking{dots}</span>"
                )
                return True  # Continue animation
            return False  # Stop animation if label is gone
        
        # Update every 500ms
        self.thinking_timer = GLib.timeout_add(500, update_dots)

    def hide_thinking_animation(self):
        """Remove the thinking animation."""
        # Only try to remove the timer if it exists
        if hasattr(self, 'thinking_timer') and self.thinking_timer is not None:
            try:
                GLib.source_remove(self.thinking_timer)
            except:
                pass
        self.thinking_timer = None
        
        # Remove the label if it exists
        if hasattr(self, 'thinking_label') and self.thinking_label:
            self.thinking_label.destroy()
            self.thinking_label = None

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
                # Update the visible title
                history_row.get_children()[0].get_children()[0].set_text(new_name)
                
                # Load and update the chat history
                history = load_chat_history(history_row.filename)
                if history:
                    # Update the first message which is used as the title
                    history[1]['content'] = new_name  # Update first user message
                    save_chat_history(history_row.filename, history)
        
        dialog.destroy()

    def on_export_chat(self, widget, history_row):
        """Handle export to PDF action."""
        # Use a FileChooserDialog for saving files
        dialog = Gtk.FileChooserDialog(
            title="Export Chat to PDF",
            parent=self,
            action=Gtk.FileChooserAction.SAVE
        )
        dialog.add_buttons(
            "Cancel", Gtk.ResponseType.CANCEL,
            "Save", Gtk.ResponseType.OK
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
            
            if response == Gtk.ResponseType.OK:
                filename = dialog.get_filename()
                if not filename.endswith('.pdf'):
                    filename += '.pdf'
                    
                # Load the chat history
                history = load_chat_history(history_row.filename, messages_only=True)
                if history:
                    # Get a custom title for the exported chat
                    custom_title = get_chat_title(history_row.filename)
                    title = f"Chat Export - {custom_title[:50]}"
                    
                    # Get the chat ID from the filename
                    chat_id = history_row.filename
                    
                    try:
                        success = export_chat_to_pdf(history, filename, title, chat_id)
                        
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
            scrollbar {
                background: transparent;
                border: none;
            }
            scrollbar slider {
                min-width: 0px;
                min-height: 0px;
                background: transparent;
            }
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
        """
        btn_speak = Gtk.Button()
        button_size = self.font_size * 2
        btn_speak.set_size_request(button_size, button_size)
        
        icon_play = Gtk.Image.new_from_icon_name("media-playback-start", Gtk.IconSize.SMALL_TOOLBAR)
        icon_stop = Gtk.Image.new_from_icon_name("media-playback-stop", Gtk.IconSize.SMALL_TOOLBAR)
        btn_speak.set_image(icon_play)
        btn_speak.set_tooltip_text("Play response")
        
        is_playing = False
        
        # Convert list to string if necessary
        if isinstance(full_text, list):
            text_content = " ".join(full_text)
        else:
            text_content = str(full_text)
        
        # Check if this is a stored audio response from an audio model
        audio_file_match = re.search(r'<audio_file>(.*?)</audio_file>', text_content)
        initial_audio_path = audio_file_match.group(1) if audio_file_match else None
        
        def on_speak_clicked(widget):
            nonlocal is_playing
            if not is_playing:
                is_playing = True
                btn_speak.set_image(icon_stop)
                btn_speak.set_tooltip_text("Stop playback")
                
                # Track if generation/playback was completed
                generation_completed = False
                
                def speak_thread():
                    nonlocal is_playing, generation_completed
                    try:
                        # Reset audio_file_path for each playback attempt
                        audio_file_path = initial_audio_path
                        # Remove audio file tag from text if present
                        clean_text = re.sub(r'<audio_file>.*?</audio_file>', '', text_content).strip()
                        
                        # Check for existing audio file from "audio model"
                        if audio_file_path and Path(audio_file_path).exists():
                            # Play existing audio file (from audio model)
                            self.current_playback_process = subprocess.Popen(['paplay', str(audio_file_path)])
                            self.current_playback_process.wait()
                            generation_completed = True
                            return
                        
                        # We do not have Audio model, use TTS
                        if self.current_chat_id:
                            # Get audio directory
                            audio_dir = get_chat_dir(self.current_chat_id) / 'audio'
                            # Generate a hash of the message text for uniqueness
                            import hashlib
                            text_hash = hashlib.md5(text_content.encode()).hexdigest()[:8]

                            # Look for file matching the current settings and text hash
                            current_mode = "ttshd" if self.tts_hd else "tts"
                            existing_file = audio_dir / f"{current_mode}_{self.tts_voice}_{text_hash}.wav"
                            
                            if existing_file.exists():
                                # Play existing TTS file
                                self.current_playback_process = subprocess.Popen(['paplay', str(existing_file)])
                                self.current_playback_process.wait()
                                generation_completed = True
                                return
                        
                            # No existing file found, generate new one
                            audio_dir.mkdir(parents=True, exist_ok=True)
                            
                            # Generate filename with timestamp and TTS settings
                            audio_file = existing_file
                            
                            with ai_provider.audio.speech.with_streaming_response.create(
                                model="tts-1-hd" if self.tts_hd else "tts-1",
                                voice=self.tts_voice,
                                input=clean_text
                            ) as response:
                                with open(audio_file, 'wb') as f:
                                    for chunk in response.iter_bytes():
                                        if not is_playing:  # Check if stopped
                                            break
                                        f.write(chunk)
                            
                            if is_playing:  # Only keep and play if not stopped
                                # Update audio file path for future playback
                                audio_file_path = str(audio_file)
                                
                                # Play the generated audio
                                self.current_playback_process = subprocess.Popen(['paplay', str(audio_file)])
                                self.current_playback_process.wait()
                                generation_completed = True
                            else:
                                # Clean up partial file if stopped
                                audio_file.unlink(missing_ok=True)
                    
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
                if hasattr(self, 'current_playback_process'):
                    self.current_playback_process.terminate()
                btn_speak.set_image(icon_play)
                btn_speak.set_tooltip_text("Play response")
        
        btn_speak.connect("clicked", on_speak_clicked)
        return btn_speak

    # -----------------------------------------------------------------------
    # Read Aloud Helpers – synthesize and play text via TTS or audio-preview
    # -----------------------------------------------------------------------

    def _synthesize_and_play_tts(self, text: str, *, chat_id: str, stop_event: threading.Event = None) -> bool:
        """
        Synthesize text using OpenAI TTS and play it.
        
        Uses the existing TTS voice/HD settings and caches audio files per chat.
        Returns True if playback completed successfully, False otherwise.
        """
        import hashlib
        
        # Get the OpenAI provider for TTS
        openai_provider = self.providers.get('openai')
        if not openai_provider:
            api_key = os.environ.get('OPENAI_API_KEY', self.api_keys.get('openai', '')).strip()
            if api_key:
                openai_provider = self.initialize_provider('openai', api_key)
        
        if not openai_provider:
            print("Read Aloud: OpenAI provider not available for TTS")
            return False
        
        try:
            # Clean the text of any audio file tags
            clean_text = re.sub(r'<audio_file>.*?</audio_file>', '', text).strip()
            if not clean_text:
                return True  # Nothing to say
            
            # Get audio directory for caching
            if chat_id:
                audio_dir = get_chat_dir(chat_id) / 'audio'
                audio_dir.mkdir(parents=True, exist_ok=True)
                
                # Generate a hash of the message text for uniqueness
                text_hash = hashlib.md5(clean_text.encode()).hexdigest()[:8]
                current_mode = "ttshd" if self.tts_hd else "tts"
                audio_file = audio_dir / f"read_aloud_{current_mode}_{self.tts_voice}_{text_hash}.wav"
                
                # Check for cached file
                if audio_file.exists():
                    self.current_read_aloud_process = subprocess.Popen(['paplay', str(audio_file)])
                    self.current_read_aloud_process.wait()
                    return True
            else:
                # No chat_id, use a temp file
                import tempfile
                audio_file = Path(tempfile.gettempdir()) / f"read_aloud_{hash(clean_text)}.wav"
            
            # Generate TTS audio
            with openai_provider.audio.speech.with_streaming_response.create(
                model="tts-1-hd" if self.tts_hd else "tts-1",
                voice=self.tts_voice,
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
        # Get the OpenAI provider
        openai_provider = self.providers.get('openai')
        if not openai_provider:
            api_key = os.environ.get('OPENAI_API_KEY', self.api_keys.get('openai', '')).strip()
            if api_key:
                openai_provider = self.initialize_provider('openai', api_key)
        
        if not openai_provider:
            print("Read Aloud: OpenAI provider not available for audio-preview")
            return False
        
        try:
            # Clean the text of any audio file tags
            clean_text = re.sub(r'<audio_file>.*?</audio_file>', '', text).strip()
            if not clean_text:
                return True  # Nothing to say
            
            # Build the prompt using the configured template
            template = getattr(self, 'read_aloud_audio_prompt_template', '') or 'Please say the following verbatim in a New York accent: "{text}"'
            prompt = template.replace('{text}', clean_text)
            
            # Call the audio-preview model
            response = openai_provider.client.chat.completions.create(
                model=model_id,
                modalities=["text", "audio"],
                audio={"voice": self.tts_voice, "format": "wav"},
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
                
                # Save to file
                if chat_id:
                    audio_dir = get_chat_dir(chat_id) / 'audio'
                    audio_dir.mkdir(parents=True, exist_ok=True)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    audio_file = audio_dir / f"read_aloud_audio_preview_{timestamp}.wav"
                else:
                    import tempfile
                    audio_file = Path(tempfile.gettempdir()) / f"read_aloud_audio_preview_{hash(clean_text)}.wav"
                
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
                print("Read Aloud: No audio in response from audio-preview model")
                return False
                
        except Exception as e:
            print(f"Read Aloud audio-preview error: {e}")
            return False

    def read_aloud_text(self, text: str, *, chat_id: str = None):
        """
        Read the given text aloud using the configured speech provider.
        
        This is the main entry point for the Read Aloud feature. It checks
        if read aloud is enabled and dispatches to the appropriate synthesis
        method based on the configured provider.
        
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
            provider = getattr(self, 'read_aloud_provider', 'tts') or 'tts'
            
            try:
                if provider == 'tts':
                    self._synthesize_and_play_tts(
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
                else:
                    print(f"Read Aloud: Unknown provider '{provider}'")
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

    def _create_table_cell_widget(self, text, alignment=0.0, bold=False):
        """Create a widget for a single table cell with markup/LaTeX support."""
        processed_text = process_tex_markup(
            text,
            self.latex_color,
            self.current_chat_id,
            self.source_theme,
            self.latex_dpi
        )

        css = (
            f"label {{ color: {self.ai_color}; font-family: {self.font_family}; "
            f"font-size: {self.font_size}pt; }}"
        )

        if "<img" in processed_text:
            text_view = Gtk.TextView()
            text_view.set_wrap_mode(Gtk.WrapMode.WORD)
            text_view.set_editable(False)
            text_view.set_cursor_visible(False)
            text_view.set_hexpand(True)
            text_view.set_vexpand(False)
            text_view.set_halign(Gtk.Align.FILL)
            text_view.set_justification(self._get_justification(alignment))
            css_provider = Gtk.CssProvider()
            css_text = f"""
                textview {{
                    font-family: {self.font_family};
                    font-size: {self.font_size}pt;
                }}
                textview text {{
                    color: {self.ai_color};
                }}
            """
            css_provider.load_from_data(css_text.encode())
            text_view.get_style_context().add_provider(
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
            buffer = text_view.get_buffer()
            parts = re.split(r'(<img src="[^"]+"/>)', processed_text)
            iter_ = buffer.get_start_iter()
            for part in parts:
                if part.startswith('<img src="'):
                    img_path = re.search(r'src="([^"]+)"', part).group(1)
                    # Keep LaTeX math images at their natural size
                    if self._is_latex_math_image(img_path):
                        insert_tex_image(buffer, iter_, img_path)
                    else:
                        # Make model-generated and other non-math images responsive
                        insert_resized_image(buffer, iter_, img_path, text_view)
                else:
                    markup = process_text_formatting(part, self.font_size)
                    buffer.insert_markup(iter_, markup, -1)
            return text_view

        markup = process_inline_markup(processed_text, self.font_size)
        if bold and markup.strip():
            markup = f"<b>{markup}</b>"

        lbl = Gtk.Label()
        lbl.set_use_markup(True)
        lbl.set_line_wrap(True)
        lbl.set_line_wrap_mode(Gtk.WrapMode.WORD)
        lbl.set_xalign(alignment)
        lbl.set_halign(self._get_widget_alignment(alignment))
        self.apply_css(lbl, css)
        lbl.set_markup(markup or ' ')
        return lbl

    def create_table_widget(self, table_text):
        """Convert markdown table text to a GTK grid widget."""
        if not table_text:
            return None

        lines = [line for line in table_text.split('\n') if line.strip()]
        if len(lines) < 2:
            return None

        header_cells = self._split_table_row(lines[0])
        if not header_cells:
            return None

        separator_line = lines[1]
        alignments = self._get_table_alignments(separator_line, len(header_cells))

        data_lines = lines[2:]
        grid = Gtk.Grid()
        grid.set_column_spacing(12)
        grid.set_row_spacing(6)
        grid.set_margin_start(6)
        grid.set_margin_end(6)
        grid.set_margin_top(6)
        grid.set_margin_bottom(6)
        grid.set_hexpand(True)

        # Header row
        for col, header in enumerate(header_cells):
            alignment = alignments[col] if col < len(alignments) else 0
            widget = self._create_table_cell_widget(header, alignment, bold=True)
            grid.attach(widget, col, 0, 1, 1)

        # Data rows
        for row_idx, line in enumerate(data_lines, start=1):
            cells = self._split_table_row(line)
            if not cells:
                continue
            if len(cells) < len(header_cells):
                cells.extend([''] * (len(header_cells) - len(cells)))
            elif len(cells) > len(header_cells):
                cells = cells[:len(header_cells)]

            for col, cell in enumerate(cells):
                alignment = alignments[col] if col < len(alignments) else 0
                widget = self._create_table_cell_widget(cell, alignment)
                grid.attach(widget, col, row_idx, 1, 1)

        frame = Gtk.Frame()
        frame.set_shadow_type(Gtk.ShadowType.IN)
        frame.set_margin_top(5)
        frame.set_margin_bottom(5)
        frame.add(grid)
        return frame

    def on_stream_content_received(self, content):
        """Handle received streaming content."""
        if content.startswith('Error:'):
            print(f"Error: {content}")

def create_source_view(code_content, code_lang, font_size, source_theme='solarized-dark'):
    """Create a styled source view for code display."""
    source_view = GtkSource.View.new()
    
    # Apply styling
    css_provider = Gtk.CssProvider()
    css = f"""
        textview {{
            font-family: Monospace;
            font-size: {font_size}pt;
        }}
    """
    css_provider.load_from_data(css.encode())
    source_view.get_style_context().add_provider(
        css_provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    
    # Configure view settings
    source_view.set_editable(False)
    source_view.set_wrap_mode(Gtk.WrapMode.NONE)
    source_view.set_highlight_current_line(False)
    source_view.set_show_line_numbers(False)
    
    # Set up buffer with language and style
    buffer = source_view.get_buffer()
    lang_manager = GtkSource.LanguageManager.get_default()
    if code_lang in lang_manager.get_language_ids():
        lang = lang_manager.get_language(code_lang)
    else:
        lang = None
        
    scheme_manager = GtkSource.StyleSchemeManager.get_default()
    style_scheme = scheme_manager.get_scheme(source_theme)
    
    buffer.set_language(lang)
    buffer.set_highlight_syntax(True)
    buffer.set_style_scheme(style_scheme)
    buffer.set_text(code_content)
    buffer.set_highlight_matching_brackets(False)
    
    source_view.set_size_request(-1, -1)
    
    return source_view 

def main():
    win = OpenAIGTKClient()
    win.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()
