"""
dialogs.py – GTK dialog classes extracted from ChatGTK.py.

This module contains:
- SettingsDialog: For configuring application settings (sidebar with categories).
- ToolsDialog: For configuring tool enablement (image, music).
- APIKeyDialog: For managing API keys for different providers (legacy, kept for compatibility).
"""

import os
import subprocess
import tempfile
import threading
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "4")

from gi.repository import Gtk, GtkSource
import sounddevice as sd

from config import BASE_DIR, SETTINGS_CONFIG
from utils import load_settings, apply_settings, parse_color_to_rgba, save_settings


# ---------------------------------------------------------------------------
# Helper: build the API keys editor (reused in SettingsDialog and APIKeyDialog)
# ---------------------------------------------------------------------------

def build_api_keys_editor(openai_key='', gemini_key='', grok_key='', claude_key=''):
    """
    Build and return a Gtk.Box containing API key entry fields.
    Also returns references to the entry widgets in a dict.
    """
    list_box = Gtk.ListBox()
    list_box.set_selection_mode(Gtk.SelectionMode.NONE)
    list_box.set_margin_top(12)
    list_box.set_margin_bottom(12)
    list_box.set_margin_start(12)
    list_box.set_margin_end(12)

    entries = {}

    # OpenAI API Key
    row = Gtk.ListBoxRow()
    hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    row.add(hbox)
    label = Gtk.Label(label="OpenAI API Key", xalign=0)
    label.set_hexpand(True)
    entry_openai = Gtk.Entry()
    entry_openai.set_visibility(False)
    entry_openai.set_placeholder_text("sk-...")
    entry_openai.set_text(openai_key)
    hbox.pack_start(label, True, True, 0)
    hbox.pack_start(entry_openai, False, True, 0)
    list_box.add(row)
    entries['openai'] = entry_openai

    # Gemini API Key
    row = Gtk.ListBoxRow()
    hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    row.add(hbox)
    label = Gtk.Label(label="Gemini API Key", xalign=0)
    label.set_hexpand(True)
    entry_gemini = Gtk.Entry()
    entry_gemini.set_visibility(False)
    entry_gemini.set_placeholder_text("AI...")
    entry_gemini.set_text(gemini_key)
    hbox.pack_start(label, True, True, 0)
    hbox.pack_start(entry_gemini, False, True, 0)
    list_box.add(row)
    entries['gemini'] = entry_gemini

    # Grok API Key
    row = Gtk.ListBoxRow()
    hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    row.add(hbox)
    label = Gtk.Label(label="Grok API Key", xalign=0)
    label.set_hexpand(True)
    entry_grok = Gtk.Entry()
    entry_grok.set_visibility(False)
    entry_grok.set_placeholder_text("gsk-...")
    entry_grok.set_text(grok_key)
    hbox.pack_start(label, True, True, 0)
    hbox.pack_start(entry_grok, False, True, 0)
    list_box.add(row)
    entries['grok'] = entry_grok

    # Claude API Key
    row = Gtk.ListBoxRow()
    hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    row.add(hbox)
    label = Gtk.Label(label="Claude API Key", xalign=0)
    label.set_hexpand(True)
    entry_claude = Gtk.Entry()
    entry_claude.set_visibility(False)
    entry_claude.set_placeholder_text("sk-ant-...")
    entry_claude.set_text(claude_key)
    hbox.pack_start(label, True, True, 0)
    hbox.pack_start(entry_claude, False, True, 0)
    list_box.add(row)
    entries['claude'] = entry_claude

    return list_box, entries


# ---------------------------------------------------------------------------
# SettingsDialog – sidebar-based settings with categories
# ---------------------------------------------------------------------------

class SettingsDialog(Gtk.Dialog):
    """Dialog for configuring application settings with a sidebar for categories."""

    # Categories displayed in the sidebar
    CATEGORIES = ["General", "System Prompts", "Model Whitelist", "API Keys"]

    def __init__(self, parent, ai_provider=None, providers=None, api_keys=None, **settings):
        super().__init__(title="Settings", transient_for=parent, flags=0)
        self.ai_provider = ai_provider  # OpenAI provider (for TTS preview)
        self.providers = providers or {}  # dict of provider_name -> provider instance
        self.initial_api_keys = api_keys or {}  # dict of provider_name -> key string
        apply_settings(self, settings)
        self.set_modal(True)

        # Load saved dialog size or use defaults
        settings_dict = load_settings()
        dialog_width = settings_dict.get('SETTINGS_DIALOG_WIDTH', 950)
        dialog_height = settings_dict.get('SETTINGS_DIALOG_HEIGHT', 800)
        self.set_default_size(dialog_width, dialog_height)

        # Connect to size change signal to save dialog size
        self.connect('configure-event', self._on_configure_event)

        # Storage for model whitelist checkboxes: {provider: {model_id: Gtk.CheckButton}}
        self.model_checkboxes = {}

        # Get the content area
        content = self.get_content_area()
        content.set_spacing(0)

        # Root horizontal box: sidebar | stack
        root_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        content.pack_start(root_hbox, True, True, 0)

        # --- Sidebar ---
        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_scroll.set_size_request(150, -1)

        self.sidebar_list = Gtk.ListBox()
        self.sidebar_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.sidebar_list.get_style_context().add_class('navigation-sidebar')
        sidebar_scroll.add(self.sidebar_list)
        root_hbox.pack_start(sidebar_scroll, False, False, 0)

        # Populate sidebar rows
        for cat in self.CATEGORIES:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label=cat, xalign=0)
            label.set_margin_start(12)
            label.set_margin_end(12)
            label.set_margin_top(8)
            label.set_margin_bottom(8)
            row.add(label)
            row.category_name = cat  # store category name on the row
            self.sidebar_list.add(row)

        # --- Stack for pages ---
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_UP_DOWN)
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)
        root_hbox.pack_start(self.stack, True, True, 0)

        # Build pages
        self._build_general_page()
        self._build_system_prompts_page()
        self._build_model_whitelist_page()
        self._build_api_keys_page()

        # Connect sidebar selection to stack switching
        self.sidebar_list.connect('row-selected', self._on_sidebar_row_selected)
        # Select first row by default
        first_row = self.sidebar_list.get_row_at_index(0)
        if first_row:
            self.sidebar_list.select_row(first_row)

        # Add dialog buttons
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("OK", Gtk.ResponseType.OK)

        self.show_all()

    # -----------------------------------------------------------------------
    # Size change handler - save dialog size
    # -----------------------------------------------------------------------
    def _on_configure_event(self, widget, event):
        """Save the dialog size when it changes."""
        width = event.width
        height = event.height

        # Load current settings and update dialog size
        settings_dict = load_settings()
        settings_dict['SETTINGS_DIALOG_WIDTH'] = width
        settings_dict['SETTINGS_DIALOG_HEIGHT'] = height
        save_settings(settings_dict)

        return False  # Allow the event to continue

    # -----------------------------------------------------------------------
    # Sidebar selection handler
    # -----------------------------------------------------------------------
    def _on_sidebar_row_selected(self, listbox, row):
        if row is not None:
            cat = getattr(row, 'category_name', None)
            if cat:
                self.stack.set_visible_child_name(cat)

    # -----------------------------------------------------------------------
    # General page
    # -----------------------------------------------------------------------
    def _build_general_page(self):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        list_box.set_margin_top(12)
        list_box.set_margin_bottom(12)
        list_box.set_margin_start(12)
        list_box.set_margin_end(12)
        scroll.add(list_box)

        # AI Name
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="AI Name", xalign=0)
        label.set_hexpand(True)
        self.entry_ai_name = Gtk.Entry()
        self.entry_ai_name.set_text(self.ai_name)
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.entry_ai_name, False, True, 0)
        list_box.add(row)

        # Font Family
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Font Family", xalign=0)
        label.set_hexpand(True)
        self.entry_font = Gtk.Entry()
        self.entry_font.set_text(self.font_family)
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.entry_font, False, True, 0)
        list_box.add(row)

        # Font Size
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Font Size", xalign=0)
        label.set_hexpand(True)
        self.spin_size = Gtk.SpinButton()
        self.spin_size.set_range(6, 72)
        self.spin_size.set_increments(1, 2)
        self.spin_size.set_value(float(self.font_size))
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.spin_size, False, True, 0)
        list_box.add(row)

        # User Color
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="User Color", xalign=0)
        label.set_hexpand(True)
        self.btn_user_color = Gtk.ColorButton()
        rgba = parse_color_to_rgba(self.user_color)
        self.btn_user_color.set_rgba(rgba)
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.btn_user_color, False, True, 0)
        list_box.add(row)

        # AI Color
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="AI Color", xalign=0)
        label.set_hexpand(True)
        self.btn_ai_color = Gtk.ColorButton()
        rgba = parse_color_to_rgba(self.ai_color)
        self.btn_ai_color.set_rgba(rgba)
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.btn_ai_color, False, True, 0)
        list_box.add(row)

        # LaTeX Color picker
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Math Color", xalign=0)
        label.set_hexpand(True)
        self.btn_latex_color = Gtk.ColorButton()
        rgba = parse_color_to_rgba(self.latex_color)
        self.btn_latex_color.set_rgba(rgba)
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.btn_latex_color, False, True, 0)
        list_box.add(row)

        # Default Model
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Default Model", xalign=0)
        label.set_hexpand(True)
        self.entry_default_model = Gtk.Entry()
        self.entry_default_model.set_text(self.default_model)
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.entry_default_model, False, True, 0)
        list_box.add(row)

        # Temperament
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Temperament", xalign=0)
        label.set_hexpand(True)
        self.scale_temp = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.01)
        self.scale_temp.set_size_request(200, -1)
        self.scale_temp.set_value(float(self.temperament))
        self.scale_temp.set_digits(2)
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.scale_temp, False, True, 0)
        list_box.add(row)

        # Microphone
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Microphone", xalign=0)
        label.set_hexpand(True)
        self.combo_mic = Gtk.ComboBoxText()

        all_devices = []
        try:
            devices = sd.query_devices()
            for device in devices:
                if device['max_input_channels'] > 0:
                    self.combo_mic.append_text(device['name'])
                    all_devices.append(device['name'])
            if not all_devices:
                self.combo_mic.append_text("default")
        except Exception as e:
            print("Error getting audio devices:", e)
            self.combo_mic.append_text("default")

        if self.microphone in all_devices:
            self.combo_mic.set_active(all_devices.index(self.microphone))
        else:
            self.combo_mic.set_active(0)

        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.combo_mic, False, True, 0)
        list_box.add(row)

        # TTS Voice
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="TTS Voice", xalign=0)
        label.set_hexpand(True)
        voice_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.combo_tts = Gtk.ComboBoxText()

        tts_voices = ["alloy", "ash", "coral", "echo", "fable", "onyx", "nova", "shimmer"]
        for voice in tts_voices:
            self.combo_tts.append_text(voice)

        if self.tts_voice in tts_voices:
            self.combo_tts.set_active(tts_voices.index(self.tts_voice))
        else:
            self.combo_tts.set_active(0)

        self.btn_preview = Gtk.Button(label="Preview")
        self.btn_preview.connect("clicked", self.on_preview_voice)

        voice_box.pack_start(self.combo_tts, True, True, 0)
        voice_box.pack_start(self.btn_preview, False, False, 0)
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(voice_box, False, True, 0)
        list_box.add(row)

        # HD Voice Toggle
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="TTS HD Voice", xalign=0)
        label.set_hexpand(True)
        self.switch_hd = Gtk.Switch()
        self.switch_hd.set_active(self.tts_hd)
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.switch_hd, False, True, 0)
        list_box.add(row)

        # Realtime Voice
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Realtime Voice", xalign=0)
        label.set_hexpand(True)
        voice_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.combo_realtime = Gtk.ComboBoxText()

        realtime_voices = ["alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse"]
        for voice in realtime_voices:
            self.combo_realtime.append_text(voice)

        if self.realtime_voice in realtime_voices:
            self.combo_realtime.set_active(realtime_voices.index(self.realtime_voice))
        else:
            self.combo_realtime.set_active(0)

        self.btn_preview_realtime = Gtk.Button(label="Preview")
        self.btn_preview_realtime.connect("clicked", self.on_preview_realtime_voice)

        voice_box.pack_start(self.combo_realtime, True, True, 0)
        voice_box.pack_start(self.btn_preview_realtime, False, False, 0)
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(voice_box, False, True, 0)
        list_box.add(row)

        # Max Tokens
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Max Tokens (0 = no limit)", xalign=0)
        label.set_hexpand(True)
        self.spin_max_tokens = Gtk.SpinButton()
        self.spin_max_tokens.set_range(0, 32000)
        self.spin_max_tokens.set_increments(100, 1000)
        self.spin_max_tokens.set_value(float(self.max_tokens))
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.spin_max_tokens, False, True, 0)
        list_box.add(row)

        # Preferred Image Model
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Image Model", xalign=0)
        label.set_hexpand(True)
        self.combo_image_model = Gtk.ComboBoxText()

        known_image_models = [
            "dall-e-3",
            "gpt-image-1",
            "gemini-3-pro-image-preview",
            "gemini-2.5-flash-image",
            "grok-2-image-1212",
        ]

        for model_id in known_image_models:
            self.combo_image_model.append_text(model_id)

        current_image_model = getattr(self, "image_model", "dall-e-3")
        active_index = 0
        for idx, model_id in enumerate(known_image_models):
            if model_id == current_image_model:
                active_index = idx
                break
        self.combo_image_model.set_active(active_index)

        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.combo_image_model, False, True, 0)
        list_box.add(row)

        # Code Theme
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Code Theme", xalign=0)
        label.set_hexpand(True)
        self.combo_theme = Gtk.ComboBoxText()

        scheme_manager = GtkSource.StyleSchemeManager.get_default()
        themes = scheme_manager.get_scheme_ids()

        settings_dict = load_settings()
        current_theme = settings_dict.get('SOURCE_THEME', 'solarized-dark')

        current_idx = 0
        for idx, theme_id in enumerate(sorted(themes)):
            self.combo_theme.append_text(theme_id)
            if theme_id == current_theme:
                current_idx = idx

        self.combo_theme.set_active(current_idx)

        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.combo_theme, False, True, 0)
        list_box.add(row)

        # LaTeX DPI
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Math DPI", xalign=0)
        label.set_hexpand(True)
        self.spin_latex_dpi = Gtk.SpinButton()
        self.spin_latex_dpi.set_range(72, 600)
        self.spin_latex_dpi.set_increments(1, 10)
        self.spin_latex_dpi.set_value(float(self.latex_dpi))
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.spin_latex_dpi, False, True, 0)
        list_box.add(row)

        self.stack.add_named(scroll, "General")

    # -----------------------------------------------------------------------
    # System Prompts page
    # -----------------------------------------------------------------------
    def _build_system_prompts_page(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)

        label = Gtk.Label(label="System Prompt", xalign=0)
        vbox.pack_start(label, False, False, 0)

        frame = Gtk.Frame()
        frame.set_shadow_type(Gtk.ShadowType.IN)

        text_scroll = Gtk.ScrolledWindow()
        text_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        text_scroll.set_vexpand(True)

        self.entry_system_message = Gtk.TextView()
        self.entry_system_message.set_wrap_mode(Gtk.WrapMode.WORD)
        self.entry_system_message.set_margin_start(6)
        self.entry_system_message.set_margin_end(6)
        self.entry_system_message.set_margin_top(6)
        self.entry_system_message.set_margin_bottom(6)
        self.entry_system_message.set_editable(True)
        self.entry_system_message.set_cursor_visible(True)
        self.entry_system_message.set_can_focus(True)
        self.entry_system_message.set_accepts_tab(True)

        text_scroll.set_can_focus(False)
        frame.set_can_focus(False)

        def on_focus_in(widget, event):
            return False

        def on_button_press(widget, event):
            widget.grab_focus()
            return False

        self.entry_system_message.connect("focus-in-event", on_focus_in)
        self.entry_system_message.connect("button-press-event", on_button_press)

        self.entry_system_message.get_buffer().set_text(self.system_message)

        text_scroll.add(self.entry_system_message)
        frame.add(text_scroll)
        vbox.pack_start(frame, True, True, 0)

        self.stack.add_named(vbox, "System Prompts")

    # -----------------------------------------------------------------------
    # Model Whitelist page
    # -----------------------------------------------------------------------
    def _build_model_whitelist_page(self):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        outer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer_box.set_margin_top(12)
        outer_box.set_margin_bottom(12)
        outer_box.set_margin_start(12)
        outer_box.set_margin_end(12)
        scroll.add(outer_box)

        # Provider info: (display_name, settings_attr, env_var_for_key)
        provider_info = [
            ("OpenAI", "openai", "openai_model_whitelist", "OPENAI_API_KEY"),
            ("Gemini", "gemini", "gemini_model_whitelist", "GEMINI_API_KEY"),
            ("Grok", "grok", "grok_model_whitelist", "GROK_API_KEY"),
            ("Claude", "claude", "claude_model_whitelist", "CLAUDE_API_KEY"),
        ]

        for display_name, provider_key, whitelist_attr, env_key in provider_info:
            # Section label
            section_label = Gtk.Label(xalign=0)
            section_label.set_markup(f"<b>{display_name}</b>")
            outer_box.pack_start(section_label, False, False, 0)

            # Determine available models
            available_models = self._get_available_models_for_provider(provider_key)

            # Parse current whitelist
            whitelist_str = getattr(self, whitelist_attr, "") or ""
            whitelist_set = set(m.strip() for m in whitelist_str.split(",") if m.strip())

            # Split into enabled and disabled, sort each alphabetically
            enabled_models = sorted([m for m in available_models if m in whitelist_set])
            disabled_models = sorted([m for m in available_models if m not in whitelist_set])

            # Create checkboxes
            self.model_checkboxes[provider_key] = {}
            for model_id in enabled_models + disabled_models:
                cb = Gtk.CheckButton(label=model_id)
                cb.set_active(model_id in whitelist_set)
                cb.set_margin_start(12)
                outer_box.pack_start(cb, False, False, 0)
                self.model_checkboxes[provider_key][model_id] = cb

            # Separator between providers
            sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            sep.set_margin_top(6)
            sep.set_margin_bottom(6)
            outer_box.pack_start(sep, False, False, 0)

        self.stack.add_named(scroll, "Model Whitelist")

    def _get_available_models_for_provider(self, provider_key):
        """
        Return a list of available models for the given provider.
        Tries to fetch from the provider API; falls back to defaults from SETTINGS_CONFIG.
        """
        provider = self.providers.get(provider_key)
        if provider:
            try:
                return provider.get_available_models(disable_filter=True)
            except Exception as e:
                print(f"Error fetching models for {provider_key}: {e}")

        # Fallback: parse the default whitelist from SETTINGS_CONFIG
        config_key = f"{provider_key.upper()}_MODEL_WHITELIST"
        default_str = SETTINGS_CONFIG.get(config_key, {}).get('default', '')
        return [m.strip() for m in default_str.split(",") if m.strip()]

    # -----------------------------------------------------------------------
    # API Keys page
    # -----------------------------------------------------------------------
    def _build_api_keys_page(self):
        keys = self.initial_api_keys
        list_box, self.api_key_entries = build_api_keys_editor(
            openai_key=keys.get('openai', ''),
            gemini_key=keys.get('gemini', ''),
            grok_key=keys.get('grok', ''),
            claude_key=keys.get('claude', ''),
        )
        self.stack.add_named(list_box, "API Keys")

    # -----------------------------------------------------------------------
    # Voice preview handlers
    # -----------------------------------------------------------------------
    def on_preview_voice(self, widget):
        """Preview the selected TTS voice."""
        if not self.ai_provider:
            error_dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text="Error Preview Voice"
            )
            error_dialog.format_secondary_text("AI Provider not initialized. Please check your API key.")
            error_dialog.run()
            error_dialog.destroy()
            return

        selected_voice = self.combo_tts.get_active_text()
        preview_text = f"Hello! This is the {selected_voice} voice."

        try:
            temp_dir = Path(tempfile.gettempdir())
            temp_file = temp_dir / "voice_preview.mp3"

            with self.ai_provider.audio.speech.with_streaming_response.create(
                model="tts-1-hd" if self.tts_hd else "tts-1",
                voice=selected_voice,
                input=preview_text
            ) as response:
                with open(temp_file, 'wb') as f:
                    for chunk in response.iter_bytes():
                        f.write(chunk)

            os.system(f"paplay {temp_file}")

            def cleanup():
                import time
                time.sleep(3)
                temp_file.unlink(missing_ok=True)

            threading.Thread(target=cleanup, daemon=True).start()

        except Exception as e:
            error_dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text="Error Preview Voice"
            )
            error_dialog.format_secondary_text(str(e))
            error_dialog.run()
            error_dialog.destroy()

    def on_preview_realtime_voice(self, widget):
        """Preview the selected realtime voice using prepared WAV files."""
        selected_voice = self.combo_realtime.get_active_text()
        preview_file = Path(BASE_DIR) / "preview" / f"{selected_voice}.wav"

        try:
            if not preview_file.exists():
                raise FileNotFoundError(f"Preview file not found: {preview_file}")

            subprocess.Popen(['paplay', str(preview_file)])

        except Exception as e:
            error_dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text="Error Preview Voice"
            )
            error_dialog.format_secondary_text(str(e))
            error_dialog.run()
            error_dialog.destroy()

    # -----------------------------------------------------------------------
    # Collect settings
    # -----------------------------------------------------------------------
    def get_settings(self):
        """Return updated settings from dialog."""
        buffer = self.entry_system_message.get_buffer()
        system_message = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)

        # Build whitelist strings from checkboxes
        def whitelist_str(provider_key):
            cbs = self.model_checkboxes.get(provider_key, {})
            return ",".join(sorted(mid for mid, cb in cbs.items() if cb.get_active()))

        return {
            'ai_name': self.entry_ai_name.get_text(),
            'font_family': self.entry_font.get_text(),
            'font_size': int(self.spin_size.get_value()),
            'user_color': self.btn_user_color.get_rgba().to_string(),
            'ai_color': self.btn_ai_color.get_rgba().to_string(),
            'default_model': self.entry_default_model.get_text(),
            'system_message': system_message,
            'temperament': self.scale_temp.get_value(),
            'microphone': self.combo_mic.get_active_text() or 'default',
            'tts_voice': self.combo_tts.get_active_text(),
            'realtime_voice': self.combo_realtime.get_active_text(),
            'max_tokens': int(self.spin_max_tokens.get_value()),
            'source_theme': self.combo_theme.get_active_text(),
            'latex_dpi': int(self.spin_latex_dpi.get_value()),
            'latex_color': self.btn_latex_color.get_rgba().to_string(),
            'tts_hd': self.switch_hd.get_active(),
            'image_model': self.combo_image_model.get_active_text() or 'dall-e-3',
            # Model whitelists
            'openai_model_whitelist': whitelist_str('openai'),
            'gemini_model_whitelist': whitelist_str('gemini'),
            'grok_model_whitelist': whitelist_str('grok'),
            'claude_model_whitelist': whitelist_str('claude'),
        }

    def get_api_keys(self):
        """Return API keys from the API Keys page."""
        return {
            'openai': self.api_key_entries['openai'].get_text().strip(),
            'gemini': self.api_key_entries['gemini'].get_text().strip(),
            'grok': self.api_key_entries['grok'].get_text().strip(),
            'claude': self.api_key_entries['claude'].get_text().strip(),
        }


# ---------------------------------------------------------------------------
# ToolsDialog – unchanged
# ---------------------------------------------------------------------------

class ToolsDialog(Gtk.Dialog):
    """Dialog for configuring tool enablement (image, music)."""

    def __init__(self, parent, **settings):
        super().__init__(title="Tools", transient_for=parent, flags=0)
        apply_settings(self, settings)
        self.set_modal(True)
        self.set_default_size(400, 200)

        box = self.get_content_area()
        box.set_spacing(6)

        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        list_box.set_margin_top(12)
        list_box.set_margin_bottom(12)
        list_box.set_margin_start(12)
        list_box.set_margin_end(12)
        box.pack_start(list_box, True, True, 0)

        # Enable/disable image tool for text models
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Enable Image Tool", xalign=0)
        label.set_hexpand(True)
        self.switch_image_tool = Gtk.Switch()
        current_image_tool_enabled = bool(getattr(self, "image_tool_enabled", True))
        self.switch_image_tool.set_active(current_image_tool_enabled)
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.switch_image_tool, False, True, 0)
        list_box.add(row)

        # Enable/disable music control tool for text models
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Enable Music Tool", xalign=0)
        label.set_hexpand(True)
        self.switch_music_tool = Gtk.Switch()
        current_music_tool_enabled = bool(getattr(self, "music_tool_enabled", False))
        self.switch_music_tool.set_active(current_music_tool_enabled)
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.switch_music_tool, False, True, 0)
        list_box.add(row)

        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("OK", Gtk.ResponseType.OK)

        self.show_all()

    def get_tool_settings(self):
        """Return the tool settings from the dialog."""
        return {
            "image_tool_enabled": self.switch_image_tool.get_active(),
            "music_tool_enabled": self.switch_music_tool.get_active(),
        }


# ---------------------------------------------------------------------------
# APIKeyDialog – kept for legacy compatibility; uses the shared helper
# ---------------------------------------------------------------------------

class APIKeyDialog(Gtk.Dialog):
    """Dialog for managing API keys for different providers."""

    def __init__(self, parent, openai_key='', gemini_key='', grok_key='', claude_key=''):
        super().__init__(title="API Keys", transient_for=parent, flags=0)
        self.set_modal(True)
        self.set_default_size(500, 300)

        box = self.get_content_area()
        box.set_spacing(6)

        list_box, self.entries = build_api_keys_editor(
            openai_key=openai_key,
            gemini_key=gemini_key,
            grok_key=grok_key,
            claude_key=claude_key,
        )
        box.pack_start(list_box, True, True, 0)

        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("OK", Gtk.ResponseType.OK)

        self.show_all()

    def get_keys(self):
        """Return the API keys from the dialog."""
        return {
            'openai': self.entries['openai'].get_text().strip(),
            'gemini': self.entries['gemini'].get_text().strip(),
            'grok': self.entries['grok'].get_text().strip(),
            'claude': self.entries['claude'].get_text().strip(),
        }
