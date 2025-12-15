"""
dialogs.py – GTK dialog classes extracted from ChatGTK.py.

This module contains:
- SettingsDialog: For configuring application settings (sidebar with categories).
- ToolsDialog: For configuring tool enablement (image, music).
- APIKeyDialog: For managing API keys for different providers (legacy, kept for compatibility).
"""

import json
import os
import subprocess
import tempfile
import threading
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "4")

from gi.repository import Gtk, GtkSource, GLib
import sounddevice as sd

from config import BASE_DIR, PARENT_DIR, SETTINGS_CONFIG, MODEL_CACHE_FILE
from model_cards import get_card, list_cards
from utils import (
    load_settings,
    apply_settings,
    parse_color_to_rgba,
    save_settings,
    save_api_keys,
    load_api_keys,
    load_custom_models,
    save_custom_models,
    load_model_display_names,
    save_model_display_names,
    get_object_settings,
    convert_settings_for_save,
)
from ai_providers import CustomProvider


# ---------------------------------------------------------------------------
# Model cache helpers – persist available models per provider to disk
# ---------------------------------------------------------------------------

def load_model_cache() -> dict:
    """
    Load the model cache from disk.
    Returns a dict keyed by provider ID (e.g. 'openai', 'gemini', 'grok', 'claude'),
    each value being a list of model ID strings.
    Returns an empty dict if the cache file does not exist or is invalid.
    """
    if not os.path.exists(MODEL_CACHE_FILE):
        return {}
    try:
        with open(MODEL_CACHE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception as e:
        print(f"Warning: could not load model cache: {e}")
    return {}


def save_model_cache(cache: dict) -> None:
    """
    Save the model cache to disk.
    `cache` should be a dict keyed by provider ID, each value a list of model IDs.
    """
    try:
        with open(MODEL_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"Warning: could not save model cache: {e}")


# ---------------------------------------------------------------------------
# Small UI helper(s)
# ---------------------------------------------------------------------------

def _add_listbox_row_margins(row, top=4, bottom=4):
    """
    Add a bit of vertical breathing room to rows in settings-style ListBoxes.
    """
    row.set_margin_top(top)
    row.set_margin_bottom(bottom)
    # Also add small horizontal margins so row contents don't sit flush
    # against any theme-drawn borders around the ListBox.
    row.set_margin_start(6)
    row.set_margin_end(6)
    return row


# ---------------------------------------------------------------------------
# Custom Model dialog
# ---------------------------------------------------------------------------

class CustomModelDialog(Gtk.Dialog):
    """Dialog for creating or editing a custom model definition."""

    API_TYPES = [
        ("chat.completions", "chat.completions"),
        ("responses", "responses"),
        ("images", "images"),
        ("tts", "tts"),
    ]

    def __init__(self, parent, initial: dict = None):
        super().__init__(title="Custom Model", transient_for=parent, flags=0)
        self.set_modal(True)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Save", Gtk.ResponseType.OK)
        self.set_default_size(620, 300)

        data = initial or {}

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        # Model ID
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        label = Gtk.Label(label="Model ID", xalign=0)
        label.set_size_request(120, -1)
        self.entry_model_id = Gtk.Entry()
        self.entry_model_id.set_placeholder_text("unique-model-id")
        self.entry_model_id.set_text(str(data.get("model_id", data.get("model_name", ""))))
        row.pack_start(label, False, False, 0)
        row.pack_start(self.entry_model_id, True, True, 0)
        box.pack_start(row, False, False, 0)

        # Display name (optional)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        label = Gtk.Label(label="Display Name", xalign=0)
        label.set_size_request(120, -1)
        self.entry_display = Gtk.Entry()
        self.entry_display.set_placeholder_text("Shown in dropdowns (optional)")
        self.entry_display.set_text(str(data.get("display_name", "")))
        row.pack_start(label, False, False, 0)
        row.pack_start(self.entry_display, True, True, 0)
        box.pack_start(row, False, False, 0)

        # Endpoint
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        label = Gtk.Label(label="Endpoint URL", xalign=0)
        label.set_size_request(120, -1)
        self.entry_endpoint = Gtk.Entry()
        self.entry_endpoint.set_placeholder_text("https://api.example.com/v1")
        self.entry_endpoint.set_text(str(data.get("endpoint", "")))
        row.pack_start(label, False, False, 0)
        row.pack_start(self.entry_endpoint, True, True, 0)
        box.pack_start(row, False, False, 0)

        # API key - dropdown with text entry
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        label = Gtk.Label(label="API Key", xalign=0)
        label.set_size_request(120, -1)
        self.combo_api_key = Gtk.ComboBoxText.new_with_entry()
        self.combo_api_key.set_entry_text_column(0)
        # Get the entry widget for password visibility
        entry_widget = self.combo_api_key.get_child()
        entry_widget.set_visibility(False)
        entry_widget.set_placeholder_text("Optional - select from known keys or enter custom")
        
        # Load known API keys and populate dropdown
        from utils import API_KEY_FIELDS, get_api_key_env_vars
        api_keys = load_api_keys()
        
        # Track items as we add them for initial value matching
        item_index_map = {}  # Maps key_name -> index
        self._env_var_items = {}  # Maps index -> env_var_name for env var entries
        
        # Add environment variable API keys first
        env_vars = get_api_key_env_vars()
        for env_name in sorted(env_vars.keys()):
            item_text = f"ENV: ${env_name}"
            self.combo_api_key.append_text(item_text)
            model = self.combo_api_key.get_model()
            index = model.iter_n_children(None) - 1
            item_index_map[f"${env_name}"] = index
            self._env_var_items[index] = env_name
        
        # Add standard keys
        standard_key_names = {
            'openai': 'OpenAI',
            'gemini': 'Gemini',
            'grok': 'Grok',
            'claude': 'Claude',
            'perplexity': 'Perplexity'
        }
        for key_name in API_KEY_FIELDS:
            if api_keys.get(key_name):
                display_name = standard_key_names.get(key_name, key_name.capitalize())
                item_text = f"{display_name} ({key_name})"
                self.combo_api_key.append_text(item_text)
                # Get index after appending (it's the last item)
                model = self.combo_api_key.get_model()
                index = model.iter_n_children(None) - 1
                item_index_map[key_name] = index
        
        # Add custom keys
        for key_name, key_value in api_keys.items():
            if key_name not in API_KEY_FIELDS and key_value:
                item_text = f"{key_name} (custom)"
                self.combo_api_key.append_text(item_text)
                # Get index after appending (it's the last item)
                model = self.combo_api_key.get_model()
                index = model.iter_n_children(None) - 1
                item_index_map[key_name] = index
        
        # Set initial value if provided
        initial_api_key = str(data.get("api_key", "")).strip()
        if initial_api_key:
            # Check if it's an env var reference (starts with $)
            if initial_api_key.startswith('$'):
                if initial_api_key in item_index_map:
                    self.combo_api_key.set_active(item_index_map[initial_api_key])
                else:
                    entry_widget.set_text(initial_api_key)
            else:
                # Try to match with a known key name
                matched = False
                for key_name, key_value in api_keys.items():
                    if key_value == initial_api_key:
                        # Find matching item in our index map
                        if key_name in item_index_map:
                            index = item_index_map[key_name]
                            self.combo_api_key.set_active(index)
                            matched = True
                            break
                
                # If no match found, set as custom text
                if not matched:
                    entry_widget.set_text(initial_api_key)
        
        row.pack_start(label, False, False, 0)
        row.pack_start(self.combo_api_key, True, True, 0)
        box.pack_start(row, False, False, 0)

        # API type
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        label = Gtk.Label(label="API Type", xalign=0)
        label.set_size_request(120, -1)
        self.combo_api_type = Gtk.ComboBoxText()
        for key, display in self.API_TYPES:
            self.combo_api_type.append_text(display)
        api_type_val = str(data.get("api_type", "chat.completions"))
        try:
            idx = [k for k, _ in self.API_TYPES].index(api_type_val)
        except ValueError:
            idx = 0
        self.combo_api_type.set_active(idx)
        row.pack_start(label, False, False, 0)
        row.pack_start(self.combo_api_type, False, False, 0)
        box.pack_start(row, False, False, 0)

        # Voice (for TTS models only)
        self.voice_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        label = Gtk.Label(label="Voice", xalign=0)
        label.set_size_request(120, -1)
        voice_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.combo_voice = Gtk.ComboBoxText.new_with_entry()
        self.combo_voice.set_entry_text_column(0)
        self.combo_voice.set_hexpand(True)
        self.voice_entry = self.combo_voice.get_child()
        self.voice_entry.set_placeholder_text("Select or type a voice (e.g., alloy, nova)")

        # Populate voices (support legacy single voice or list of voices)
        initial_voices = []
        data_voices = data.get("voices")
        if isinstance(data_voices, list):
            initial_voices.extend([v for v in data_voices if isinstance(v, str) and v.strip()])
        legacy_voice = str(data.get("voice", "")).strip()
        if legacy_voice and legacy_voice not in initial_voices:
            initial_voices.insert(0, legacy_voice)
        for voice in initial_voices:
            self._add_voice_option(voice)

        if legacy_voice and legacy_voice in initial_voices:
            self.combo_voice.set_active(initial_voices.index(legacy_voice))
        elif initial_voices:
            self.combo_voice.set_active(0)

        self.btn_add_voice = Gtk.Button.new_from_icon_name("list-add", Gtk.IconSize.BUTTON)
        self.btn_add_voice.set_tooltip_text("Edit voice list")
        self.btn_add_voice.connect("clicked", self._on_manage_voices_clicked)

        voice_box.pack_start(self.combo_voice, True, True, 0)
        voice_box.pack_start(self.btn_add_voice, False, False, 0)
        self.voice_row.pack_start(label, False, False, 0)
        self.voice_row.pack_start(voice_box, True, True, 0)
        box.pack_start(self.voice_row, False, False, 0)
        
        # Show/hide voice row based on api_type
        self.combo_api_type.connect("changed", self._on_api_type_changed)
        self._on_api_type_changed(self.combo_api_type)  # Set initial visibility

        # Store initial data for editing existing models
        self._initial_model_id = str(data.get("model_id", data.get("model_name", "")))

        # Advanced button for model card editing
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        spacer = Gtk.Label(label="", xalign=0)
        spacer.set_size_request(120, -1)
        self.btn_advanced = Gtk.Button(label="Advanced...")
        self.btn_advanced.set_tooltip_text("Edit model capabilities and quirks")
        self.btn_advanced.connect("clicked", self._on_advanced_clicked)
        row.pack_start(spacer, False, False, 0)
        row.pack_start(self.btn_advanced, False, False, 0)
        box.pack_start(row, False, False, 0)

        # Test connection button
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        spacer = Gtk.Label(label="", xalign=0)
        spacer.set_size_request(120, -1)
        self.btn_test = Gtk.Button(label="Test Connection")
        self.btn_test.connect("clicked", self._on_test_connection)
        self.lbl_test_result = Gtk.Label(label="", xalign=0)
        self.lbl_test_result.set_line_wrap(True)
        row.pack_start(spacer, False, False, 0)
        row.pack_start(self.btn_test, False, False, 0)
        row.pack_start(self.lbl_test_result, True, True, 0)
        box.pack_start(row, False, False, 0)

        self.show_all()

    def get_data(self) -> dict:
        model_id = self.entry_model_id.get_text().strip()
        display_name = self.entry_display.get_text().strip()
        endpoint = self.entry_endpoint.get_text().strip()
        # Get API key from combobox entry
        entry_widget = self.combo_api_key.get_child()
        api_key_text = entry_widget.get_text().strip()
        
        # Check if a dropdown item is selected
        active_id = self.combo_api_key.get_active()
        api_key = api_key_text  # Default to entry text
        
        if active_id >= 0:
            # Check if it's an environment variable selection
            if active_id in self._env_var_items:
                # Store env var reference instead of actual key
                env_var_name = self._env_var_items[active_id]
                api_key = f"${env_var_name}"
            else:
                # User selected from dropdown, extract key name and get actual value
                from utils import load_api_keys, API_KEY_FIELDS
                import re
                api_keys = load_api_keys()
                active_text = self.combo_api_key.get_active_text()
                
                # Extract key name from dropdown text
                # Format for standard keys: "Display Name (key_name)" -> extract "key_name" from parentheses
                # Format for custom keys: "key_name (custom)" -> extract "key_name" before "(custom)"
                key_name = None
                
                # First try to match custom key format: "key_name (custom)"
                custom_match = re.match(r'^(.+?)\s+\(custom\)$', active_text)
                if custom_match:
                    key_name = custom_match.group(1).strip()
                else:
                    # Try standard key format: "Display Name (key_name)"
                    standard_match = re.search(r'\(([^)]+)\)', active_text)
                    if standard_match:
                        key_name = standard_match.group(1).strip()
                
                # Look up the actual key value
                if key_name and key_name in api_keys and api_keys[key_name]:
                    api_key = api_keys[key_name]
                # If key not found or empty, fall through to use entry text (user may have edited it)
        
        # If no dropdown item selected or lookup failed, api_key is already set to entry_text
        # This handles both custom typed values and edited dropdown selections
        
        api_type = self.combo_api_type.get_active_text() or "chat.completions"

        if not model_id:
            raise ValueError("Model ID is required")
        if not endpoint:
            raise ValueError("Endpoint URL is required")

        result = {
            "model_id": model_id,
            "model_name": model_id,
            "display_name": display_name or model_id,
            "endpoint": endpoint,
            "api_key": api_key,
            "api_type": api_type,
        }
        
        # Include voice for TTS models
        if api_type == "tts":
            voice_entry = self.combo_voice.get_child()
            voice = self.combo_voice.get_active_text() or (voice_entry.get_text().strip() if voice_entry else "")
            voices = self._get_voice_options()
            if voice and voice not in voices:
                voices.append(voice)
            if voice:
                result["voice"] = voice
            if voices:
                result["voices"] = voices
        
        return result

    def _get_voice_options(self):
        """Return the list of voice options currently in the combo box."""
        voices = []
        model = self.combo_voice.get_model()
        if model is None:
            return voices
        itr = model.get_iter_first()
        while itr:
            value = model[itr][0]
            if value:
                voices.append(value)
            itr = model.iter_next(itr)
        return voices

    def _add_voice_option(self, voice: str):
        """Add a voice to the combo if it is non-empty and not already present."""
        voice_clean = (voice or "").strip()
        if not voice_clean:
            return
        existing = self._get_voice_options()
        if voice_clean in existing:
            return
        self.combo_voice.append_text(voice_clean)

    def _set_voice_options(self, voices):
        """Replace combo options with provided voices, keeping active selection when possible."""
        voices_clean = []
        for v in voices or []:
            v_clean = (v or "").strip()
            if v_clean and v_clean not in voices_clean:
                voices_clean.append(v_clean)

        current_voice = self.combo_voice.get_active_text()
        self.combo_voice.remove_all()
        for voice in voices_clean:
            self.combo_voice.append_text(voice)

        if current_voice and current_voice in voices_clean:
            self.combo_voice.set_active(voices_clean.index(current_voice))
        elif voices_clean:
            self.combo_voice.set_active(0)
        else:
            entry = self.combo_voice.get_child()
            if entry:
                entry.set_text("")

    def _on_manage_voices_clicked(self, button):
        """Open a dialog to edit the list of voices."""
        dialog = Gtk.Dialog(title="Edit Voices", transient_for=self, flags=0)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save", Gtk.ResponseType.OK)
        dialog.set_default_size(350, 260)

        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(10)
        box.set_margin_end(10)

        instructions = Gtk.Label(
            label="Enter one voice per line. Remove a line to delete a voice.",
            xalign=0
        )
        instructions.set_line_wrap(True)
        box.pack_start(instructions, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        box.pack_start(scrolled, True, True, 0)

        textview = Gtk.TextView()
        textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        buffer = textview.get_buffer()
        existing = "\n".join(self._get_voice_options())
        buffer.set_text(existing)
        scrolled.add(textview)

        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            start_iter = buffer.get_start_iter()
            end_iter = buffer.get_end_iter()
            text = buffer.get_text(start_iter, end_iter, include_hidden_chars=True)
            voices = []
            for line in text.splitlines():
                line_clean = line.strip()
                if line_clean and line_clean not in voices:
                    voices.append(line_clean)
            self._set_voice_options(voices)

        dialog.destroy()

    def _on_api_type_changed(self, combo):
        """Show/hide voice field based on API type selection."""
        api_type = combo.get_active_text() or "chat.completions"
        if api_type == "tts":
            self.voice_row.show_all()
        else:
            self.voice_row.hide()

    def _on_advanced_clicked(self, button):
        """Open the Model Card Editor dialog for this custom model."""
        model_id = self.entry_model_id.get_text().strip()
        if not model_id:
            self.lbl_test_result.set_markup('<span color="red">Enter a Model ID first</span>')
            return
        
        # Load custom models to pass context
        custom_models = load_custom_models()
        
        dialog = ModelCardEditorDialog(self, model_id, custom_models)
        response = dialog.run()
        
        if response == Gtk.ResponseType.OK:
            from model_cards import set_override
            override_data = dialog.get_override_data()
            set_override(model_id, override_data)
        
        dialog.destroy()

    def _on_test_connection(self, button):
        """Test the custom model connection."""
        try:
            data = self.get_data()
        except ValueError as e:
            self.lbl_test_result.set_markup(f'<span color="red">{e}</span>')
            return
        
        # Resolve env var reference for testing
        from utils import resolve_api_key
        resolved_key = resolve_api_key(data["api_key"])
        
        provider = CustomProvider()
        provider.initialize(
            api_key=resolved_key,
            endpoint=data["endpoint"],
            model_name=data["model_id"],
            api_type=data["api_type"],
            voice=data.get("voice"),
        )
        
        self.btn_test.set_sensitive(False)
        self.lbl_test_result.set_text("Testing...")
        
        def do_test():
            ok, message = provider.test_connection()
            GLib.idle_add(self._show_test_result, ok, message)
        
        threading.Thread(target=do_test, daemon=True).start()

    def _show_test_result(self, ok, message):
        """Show the test connection result."""
        self.btn_test.set_sensitive(True)
        if ok:
            self.lbl_test_result.set_markup('<span color="green">✓ Connected</span>')
        else:
            # Truncate long error messages
            short_msg = message[:80] + "..." if len(message) > 80 else message
            self.lbl_test_result.set_markup(f'<span color="red">✗ {short_msg}</span>')
        return False  # Don't repeat


# ---------------------------------------------------------------------------
# Model Card Editor dialog
# ---------------------------------------------------------------------------

class ModelCardEditorDialog(Gtk.Dialog):
    """
    Dialog for viewing and editing model card capabilities, API settings, and quirks.
    
    Can be used to:
    - View capabilities of builtin models
    - Override settings for any model
    - Configure capabilities for custom models
    """

    PROVIDERS = ["openai", "gemini", "grok", "claude", "perplexity", "custom"]
    API_FAMILIES = ["chat.completions", "responses", "images", "tts", "realtime"]

    def __init__(self, parent, model_id: str, custom_models: dict = None):
        super().__init__(title=f"Edit Model: {model_id}", transient_for=parent, flags=0)
        self.set_modal(True)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Save", Gtk.ResponseType.OK)
        self.set_default_size(500, 550)

        self.model_id = model_id
        self.custom_models = custom_models or {}
        
        # Load the current card (may be None for unknown models)
        self.original_card = get_card(model_id, self.custom_models)
        
        # Check if there's an existing override
        from model_cards import get_override
        self.existing_override = get_override(model_id)
        
        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        # Model ID (read-only display)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        label = Gtk.Label(label="Model ID", xalign=0)
        label.set_size_request(120, -1)
        id_label = Gtk.Label(label=model_id, xalign=0)
        id_label.set_selectable(True)
        row.pack_start(label, False, False, 0)
        row.pack_start(id_label, True, True, 0)
        box.pack_start(row, False, False, 0)

        # Display Name
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        label = Gtk.Label(label="Display Name", xalign=0)
        label.set_size_request(120, -1)
        self.entry_display_name = Gtk.Entry()
        self.entry_display_name.set_placeholder_text("Optional display name")
        if self.original_card and self.original_card.display_name:
            self.entry_display_name.set_text(self.original_card.display_name)
        row.pack_start(label, False, False, 0)
        row.pack_start(self.entry_display_name, True, True, 0)
        box.pack_start(row, False, False, 0)

        # Provider
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        label = Gtk.Label(label="Provider", xalign=0)
        label.set_size_request(120, -1)
        self.combo_provider = Gtk.ComboBoxText()
        for p in self.PROVIDERS:
            self.combo_provider.append_text(p)
        provider_idx = 0
        if self.original_card:
            try:
                provider_idx = self.PROVIDERS.index(self.original_card.provider)
            except ValueError:
                pass
        elif isinstance(parent, CustomModelDialog):
            # When opened from CustomModelDialog, default to "custom" for new models
            try:
                provider_idx = self.PROVIDERS.index("custom")
            except ValueError:
                pass
        self.combo_provider.set_active(provider_idx)
        row.pack_start(label, False, False, 0)
        row.pack_start(self.combo_provider, False, False, 0)
        box.pack_start(row, False, False, 0)

        # Base URL
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        label = Gtk.Label(label="Base URL", xalign=0)
        label.set_size_request(120, -1)
        self.entry_base_url = Gtk.Entry()
        self.entry_base_url.set_placeholder_text("Optional endpoint override")
        if self.original_card and self.original_card.base_url:
            self.entry_base_url.set_text(self.original_card.base_url)
        row.pack_start(label, False, False, 0)
        row.pack_start(self.entry_base_url, True, True, 0)
        box.pack_start(row, False, False, 0)

        # API Family
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        label = Gtk.Label(label="API Family", xalign=0)
        label.set_size_request(120, -1)
        self.combo_api_family = Gtk.ComboBoxText()
        for af in self.API_FAMILIES:
            self.combo_api_family.append_text(af)
        api_idx = 0
        if self.original_card:
            try:
                api_idx = self.API_FAMILIES.index(self.original_card.api_family)
            except ValueError:
                pass
        self.combo_api_family.set_active(api_idx)
        row.pack_start(label, False, False, 0)
        row.pack_start(self.combo_api_family, False, False, 0)
        box.pack_start(row, False, False, 0)

        # --- Capabilities Section ---
        frame = Gtk.Frame(label=" Capabilities ")
        frame.set_margin_top(8)
        caps_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        caps_box.set_margin_top(8)
        caps_box.set_margin_bottom(8)
        caps_box.set_margin_start(8)
        caps_box.set_margin_end(8)
        frame.add(caps_box)

        # Capability checkboxes in a grid for vertical alignment
        caps = self.original_card.capabilities if self.original_card else None
        
        caps_grid = Gtk.Grid()
        caps_grid.set_column_spacing(16)
        caps_grid.set_row_spacing(4)
        caps_grid.set_column_homogeneous(True)
        
        self.chk_text = Gtk.CheckButton(label="Text")
        self.chk_text.set_active(caps.text if caps else True)
        self.chk_text.set_tooltip_text("Indicates that a model can receive text as an input modality.")
        self.chk_vision = Gtk.CheckButton(label="Vision")
        self.chk_vision.set_active(caps.vision if caps else False)
        self.chk_vision.set_tooltip_text("Indicates that a model can receive images or videos as input.")
        self.chk_audio_in = Gtk.CheckButton(label="Audio Input")
        self.chk_audio_in.set_active(caps.audio_in if caps else False)
        self.chk_audio_in.set_tooltip_text("Allows the model to receive audio and enables its use as a speech-to-text provider.")
        caps_grid.attach(self.chk_text, 0, 0, 1, 1)
        caps_grid.attach(self.chk_vision, 1, 0, 1, 1)
        caps_grid.attach(self.chk_audio_in, 2, 0, 1, 1)

        self.chk_tool_use = Gtk.CheckButton(label="Tool Use")
        self.chk_tool_use.set_active(caps.tool_use if caps else False)
        self.chk_tool_use.set_tooltip_text("Enables function calling for the model and use of tools from the tools menu.")
        self.chk_audio_out = Gtk.CheckButton(label="Audio Output")
        self.chk_audio_out.set_active(caps.audio_out if caps else False)
        self.chk_audio_out.set_tooltip_text("Flags models that speak directly; skips the built-in text-to-speech playback.")
        self.chk_files = Gtk.CheckButton(label="File Uploads")
        self.chk_files.set_active(caps.files if caps else False)
        self.chk_files.set_tooltip_text("Allows file uploads to capable models.")
        caps_grid.attach(self.chk_tool_use, 0, 1, 1, 1)
        caps_grid.attach(self.chk_audio_out, 1, 1, 1, 1)
        caps_grid.attach(self.chk_files, 2, 1, 1, 1)

        self.chk_web_search = Gtk.CheckButton(label="Web Search")
        self.chk_web_search.set_active(caps.web_search if caps else False)
        self.chk_web_search.set_tooltip_text("Adds provider search tools (currently OpenAI, Grok, and Gemini).")
        self.chk_image_gen = Gtk.CheckButton(label="Image Gen")
        self.chk_image_gen.set_active(caps.image_gen if caps else False)
        self.chk_image_gen.set_tooltip_text("Marks the model as able to generate images; adds it to image tool options.")
        self.chk_image_edit = Gtk.CheckButton(label="Image Edit")
        self.chk_image_edit.set_active(caps.image_edit if caps else False)
        self.chk_image_edit.set_tooltip_text("Allows attached images to be forwarded as editing sources in a conversation.")
        caps_grid.attach(self.chk_web_search, 0, 2, 1, 1)
        caps_grid.attach(self.chk_image_gen, 1, 2, 1, 1)
        caps_grid.attach(self.chk_image_edit, 2, 2, 1, 1)
        
        caps_box.pack_start(caps_grid, False, False, 0)

        box.pack_start(frame, False, False, 0)

        # --- Quirks Section ---
        frame = Gtk.Frame(label=" Quirks ")
        frame.set_margin_top(8)
        quirks_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        quirks_box.set_margin_top(8)
        quirks_box.set_margin_bottom(8)
        quirks_box.set_margin_start(8)
        quirks_box.set_margin_end(8)
        frame.add(quirks_box)

        quirks = self.original_card.quirks if self.original_card else {}

        row1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        temp_tip = "Temperature is not supported by all models. Lower values make the model more deterministic."
        self.chk_temperature = Gtk.CheckButton(label="Temperature")
        self.chk_temperature.set_tooltip_text(temp_tip)
        self.scale_temperature = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 2.0, 0.01)
        self.scale_temperature.set_digits(2)
        self.scale_temperature.set_size_request(160, -1)
        self.scale_temperature.set_hexpand(True)
        initial_temp = getattr(self.original_card, "temperature", None)
        if initial_temp is not None:
            self.chk_temperature.set_active(True)
            self.scale_temperature.set_value(float(initial_temp))
        else:
            self.scale_temperature.set_value(1.0)
            self.scale_temperature.set_sensitive(False)
        self.chk_temperature.connect("toggled", self._on_temperature_toggled)
        row1.pack_start(self.chk_temperature, False, False, 0)
        row1.pack_start(self.scale_temperature, True, True, 0)
        quirks_box.pack_start(row1, False, False, 0)

        row2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self.chk_dev_role = Gtk.CheckButton(label="Needs Developer Role")
        self.chk_dev_role.set_active(quirks.get("needs_developer_role", False))
        self.chk_dev_role.set_tooltip_text("Model requires 'developer' role instead of 'system'")
        row2.pack_start(self.chk_dev_role, False, False, 0)
        quirks_box.pack_start(row2, False, False, 0)

        # Voice agent flag on its own row for clarity
        row_voice = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self.chk_audio_modality = Gtk.CheckButton(label="Voice Agent")
        self.chk_audio_modality.set_active(quirks.get("requires_audio_modality", False))
        self.chk_audio_modality.set_tooltip_text("Not a plain transcription model; uses chat endpoints with audio modality.")
        row_voice.pack_start(self.chk_audio_modality, False, False, 0)
        quirks_box.pack_start(row_voice, False, False, 0)

        # Reasoning effort row
        row3 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.chk_reasoning_effort = Gtk.CheckButton(label="Reasoning Effort")
        self.chk_reasoning_effort.set_active(quirks.get("reasoning_effort_enabled", False))
        self.chk_reasoning_effort.set_tooltip_text("Not all models support reasoning or all parameters")
        self.chk_reasoning_effort.connect("toggled", self._on_reasoning_effort_toggled)
        row3.pack_start(self.chk_reasoning_effort, False, False, 0)
        
        self.combo_reasoning_effort = Gtk.ComboBoxText()
        self.REASONING_LEVELS = ["none", "minimal", "low", "medium", "high", "xhigh"]
        for level in self.REASONING_LEVELS:
            self.combo_reasoning_effort.append_text(level)
        effort_level = quirks.get("reasoning_effort_level", "low")
        try:
            effort_idx = self.REASONING_LEVELS.index(effort_level)
        except ValueError:
            effort_idx = 2  # Default to "low"
        self.combo_reasoning_effort.set_active(effort_idx)
        self.combo_reasoning_effort.set_sensitive(quirks.get("reasoning_effort_enabled", False))
        row3.pack_start(self.combo_reasoning_effort, False, False, 0)
        quirks_box.pack_start(row3, False, False, 0)

        box.pack_start(frame, False, False, 0)

        # --- Reset Button ---
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_margin_top(12)
        self.btn_reset = Gtk.Button(label="Reset to Default")
        self.btn_reset.connect("clicked", self._on_reset_clicked)
        self.btn_reset.set_tooltip_text("Remove all overrides and revert to builtin defaults")
        # Only enable if there's an existing override
        self.btn_reset.set_sensitive(self.existing_override is not None)
        btn_box.pack_end(self.btn_reset, False, False, 0)
        box.pack_start(btn_box, False, False, 0)

        self.show_all()

    def _on_reset_clicked(self, button):
        """Reset to default by deleting the override."""
        from model_cards import delete_override
        delete_override(self.model_id)
        self.response(Gtk.ResponseType.REJECT)  # Special response to indicate reset

    def _on_temperature_toggled(self, checkbox):
        """Enable/disable temperature slider based on checkbox state."""
        self.scale_temperature.set_sensitive(checkbox.get_active())

    def _on_reasoning_effort_toggled(self, checkbox):
        """Enable/disable reasoning effort dropdown based on checkbox state."""
        self.combo_reasoning_effort.set_sensitive(checkbox.get_active())

    def get_override_data(self) -> dict:
        """
        Build override data dict from current dialog state.
        
        Returns a dict suitable for saving to model_card_overrides.json.
        """
        override = {}
        
        # Basic fields
        display_name = self.entry_display_name.get_text().strip()
        if display_name:
            override["display_name"] = display_name
        
        provider = self.combo_provider.get_active_text()
        if provider:
            override["provider"] = provider
        
        base_url = self.entry_base_url.get_text().strip()
        if base_url:
            override["base_url"] = base_url
        
        api_family = self.combo_api_family.get_active_text()
        if api_family:
            override["api_family"] = api_family

        # Temperature
        if self.chk_temperature.get_active():
            override["temperature"] = round(self.scale_temperature.get_value(), 2)
        elif self.existing_override and "temperature" in self.existing_override:
            # Explicitly clear any previously set temperature
            override["temperature"] = None
        
        # Capabilities
        override["capabilities"] = {
            "text": self.chk_text.get_active(),
            "vision": self.chk_vision.get_active(),
            "files": self.chk_files.get_active(),
            "tool_use": self.chk_tool_use.get_active(),
            "web_search": self.chk_web_search.get_active(),
            "audio_in": self.chk_audio_in.get_active(),
            "audio_out": self.chk_audio_out.get_active(),
            "image_gen": self.chk_image_gen.get_active(),
            "image_edit": self.chk_image_edit.get_active(),
        }
        
        # Quirks
        quirks = {}
        if self.chk_dev_role.get_active():
            quirks["needs_developer_role"] = True
        if self.chk_audio_modality.get_active():
            quirks["requires_audio_modality"] = True
        if self.chk_reasoning_effort.get_active():
            quirks["reasoning_effort_enabled"] = True
            quirks["reasoning_effort_level"] = self.combo_reasoning_effort.get_active_text() or "low"
        if quirks:
            override["quirks"] = quirks
        
        return override


# ---------------------------------------------------------------------------
# Helper: build the API keys editor (reused in SettingsDialog and APIKeyDialog)
# ---------------------------------------------------------------------------

def build_api_keys_editor(openai_key='', gemini_key='', grok_key='', claude_key='', perplexity_key='', custom_keys=None):
    """
    Build and return a Gtk.Box containing API key entry fields.
    Also returns references to the entry widgets in a dict.
    
    Args:
        custom_keys: Optional dict of custom key name -> value pairs
    """
    list_box = Gtk.ListBox()
    list_box.set_selection_mode(Gtk.SelectionMode.NONE)
    list_box.set_margin_top(0)
    list_box.set_margin_bottom(0)
    list_box.set_margin_start(0)
    list_box.set_margin_end(0)

    entries = {}
    custom_keys = custom_keys or {}
    
    # Create size groups to make labels and entries uniform width
    label_size_group = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
    entry_size_group = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
    size_groups = {'label': label_size_group, 'entry': entry_size_group}

    def _add_key_row(key_name, label_text, value, placeholder='', is_custom=False):
        """Helper to add a key row with uniform entry width."""
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label=label_text, xalign=0)
        label.set_hexpand(False)  # Don't expand, use fixed width via size group
        # Add label to size group for uniform width
        label_size_group.add_widget(label)
        entry = Gtk.Entry()
        entry.set_hexpand(True)  # Entry expands to fill remaining space
        entry.set_visibility(False)
        if placeholder:
            entry.set_placeholder_text(placeholder)
        entry.set_text(value)
        # Add entry to size group for uniform width
        entry_size_group.add_widget(entry)
        hbox.pack_start(label, False, False, 0)  # Pack label with False for expand
        hbox.pack_start(entry, True, True, 0)  # Entry expands
        # Add delete button for custom keys (will be connected in SettingsDialog)
        if is_custom:
            delete_btn = Gtk.Button.new_from_icon_name("edit-delete", Gtk.IconSize.BUTTON)
            delete_btn.set_tooltip_text("Delete this custom key")
            hbox.pack_start(delete_btn, False, False, 0)
            row.delete_button = delete_btn  # Store reference for later connection
        list_box.add(row)
        entries[key_name] = entry
        return row

    # OpenAI API Key
    _add_key_row('openai', 'OpenAI API Key', openai_key, 'sk-...')

    # Gemini API Key
    _add_key_row('gemini', 'Gemini API Key', gemini_key, 'AI...')

    # Grok API Key
    _add_key_row('grok', 'Grok API Key', grok_key, 'gsk-...')

    # Claude API Key
    _add_key_row('claude', 'Claude API Key', claude_key, 'sk-ant-...')

    # Perplexity API Key
    _add_key_row('perplexity', 'Perplexity API Key', perplexity_key, 'pplx-...')

    # Custom keys
    for key_name, key_value in custom_keys.items():
        row = _add_key_row(key_name, f'{key_name} API Key', key_value, is_custom=True)
        row.custom_key_name = key_name  # Mark as custom key row

    return list_box, entries, size_groups


# ---------------------------------------------------------------------------
# SettingsDialog – sidebar-based settings with categories
# ---------------------------------------------------------------------------

class SettingsDialog(Gtk.Dialog):
    """Dialog for configuring application settings with a sidebar for categories."""

    # Categories displayed in the sidebar
    CATEGORIES = ["General", "Audio", "Tool Options", "System Prompts", "Custom Models", "Model Whitelist", "API Keys"]

    def __init__(self, parent, ai_provider=None, providers=None, api_keys=None, **settings):
        super().__init__(title="Settings", transient_for=parent, flags=0)
        self.ai_provider = ai_provider  # OpenAI provider (for TTS preview)
        self.providers = providers or {}  # dict of provider_name -> provider instance
        self.initial_api_keys = api_keys or {}  # dict of provider_name -> key string
        self.custom_models = load_custom_models()
        apply_settings(self, settings)
        self.set_modal(True)

        # Load saved dialog size or use defaults
        settings_dict = load_settings()
        dialog_width = settings_dict.get('SETTINGS_DIALOG_WIDTH', 800)
        dialog_height = settings_dict.get('SETTINGS_DIALOG_HEIGHT', 800)
        self.set_default_size(dialog_width, dialog_height)

        # Connect to size change signal to save dialog size
        self.connect('configure-event', self._on_configure_event)

        # Storage for model whitelist checkboxes: {provider: {model_id: Gtk.CheckButton}}
        self.model_checkboxes = {}
        # Storage for model display name entries: {provider: {model_id: Gtk.Entry}}
        self.model_display_entries = {}
        # Lazily build the Model Whitelist page on first access so opening the
        # settings dialog does not block on network calls to list models.
        self._model_whitelist_built = False

        # Get the content area
        content = self.get_content_area()
        content.set_spacing(50)

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
        self._build_audio_page()
        self._build_tool_options_page()
        self._build_system_prompts_page()
        self._build_custom_models_page()
        # Model Whitelist page is built lazily when that category is selected
        # to avoid slow dialog startup caused by provider model listing calls.
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
                # Lazily construct the Model Whitelist page the first time it
                # is selected so we don't block dialog opening on network I/O.
                if cat == "Model Whitelist":
                    self._ensure_model_whitelist_page()
                self.stack.set_visible_child_name(cat)

    # -----------------------------------------------------------------------
    # General page
    # -----------------------------------------------------------------------
    def _build_general_page(self):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        list_box.set_margin_top(0)
        list_box.set_margin_bottom(0)
        list_box.set_margin_start(0)
        list_box.set_margin_end(0)
        scroll.add(list_box)

        # AI Name
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="AI Name", xalign=0)
        label.set_hexpand(True)
        self.entry_ai_name = Gtk.Entry()
        self.entry_ai_name.set_text(self.ai_name)
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.entry_ai_name, False, True, 0)
        list_box.add(row)

        # Default Model
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Default Model", xalign=0)
        label.set_hexpand(True)
        self.entry_default_model = Gtk.Entry()
        self.entry_default_model.set_text(self.default_model)
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.entry_default_model, False, True, 0)
        list_box.add(row)

        # --- Separator (as its own ListBoxRow, so it's visible) ---
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.set_margin_top(8)
        separator.set_margin_bottom(8)
        box.pack_start(separator, True, True, 0)
        row.add(box)
        # Make separator row not selectable/focusable:
        row.set_selectable(False)
        row.set_activatable(False)
        list_box.add(row)

        # Font Family
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
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
        _add_listbox_row_margins(row)
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
        _add_listbox_row_margins(row)
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
        _add_listbox_row_margins(row)
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

        # Math - LaTeX Color picker
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
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

        # Math - LaTeX DPI
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
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

        # Code Theme
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
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

        # --- Separator (as its own ListBoxRow, so it's visible) ---
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.set_margin_top(8)
        separator.set_margin_bottom(8)
        box.pack_start(separator, True, True, 0)
        row.add(box)
        # Make separator row not selectable/focusable:
        row.set_selectable(False)
        row.set_activatable(False)
        list_box.add(row)

        # Max Tokens
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
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

        # Conversation Buffer Length
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(
            label="Message Buffer (1 = No Memory, ALL = Whole Conversation)",
            xalign=0,
        )
        label.set_hexpand(True)
        self.entry_conv_buffer = Gtk.Entry()
        self.entry_conv_buffer.set_hexpand(False)
        self.entry_conv_buffer.set_width_chars(10)
        current_buffer = getattr(self, "conversation_buffer_length", "ALL") or "ALL"
        self.entry_conv_buffer.set_text(str(current_buffer))
        self.entry_conv_buffer.set_placeholder_text("ALL")
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.entry_conv_buffer, False, True, 0)
        list_box.add(row)

        # Minimize to tray
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Minimize to system tray", xalign=0)
        label.set_hexpand(True)
        self.switch_minimize_to_tray = Gtk.Switch()
        current_minimize_to_tray = bool(getattr(self, "minimize_to_tray_enabled", False))
        self.switch_minimize_to_tray.set_active(current_minimize_to_tray)
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.switch_minimize_to_tray, False, True, 0)
        list_box.add(row)

        self.stack.add_named(scroll, "General")

    # -----------------------------------------------------------------------
    # Audio page
    # -----------------------------------------------------------------------
    def _build_audio_page(self):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        list_box.set_margin_top(0)
        list_box.set_margin_bottom(0)
        list_box.set_margin_start(0)
        list_box.set_margin_end(0)
        scroll.add(list_box)

        # Microphone
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
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

        # TTS Voice Provider (unified - used by play button, auto read-aloud, and read-aloud tool)
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Text-to-Speech Model", xalign=0)
        label.set_hexpand(True)
        self.combo_tts_provider = Gtk.ComboBoxText()

        # Built-in TTS provider options
        tts_providers = [
            ("openai", "OpenAI TTS (tts-1 / tts-1-hd)"),
            ("gemini", "Gemini TTS"),
            ("gpt-4o-audio-preview", "gpt-4o-audio-preview"),
            ("gpt-4o-mini-audio-preview", "gpt-4o-mini-audio-preview"),
        ]
        for provider_id, display_name in tts_providers:
            self.combo_tts_provider.append(provider_id, display_name)

        # Add custom TTS models from custom_models.json
        for model_id, cfg in self.custom_models.items():
            if (cfg.get("api_type") or "").lower() == "tts":
                display_name = cfg.get("display_name") or model_id
                self.combo_tts_provider.append(model_id, f"{display_name} (custom)")

        current_tts_provider = getattr(self, "tts_voice_provider", "openai") or "openai"
        self.combo_tts_provider.set_active_id(current_tts_provider)
        self.combo_tts_provider.connect("changed", self._on_tts_provider_changed)

        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.combo_tts_provider, False, True, 0)
        list_box.add(row)

        # TTS Voice
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="TTS Voice", xalign=0)
        label.set_hexpand(True)
        voice_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.combo_tts = Gtk.ComboBoxText()

        # Populate voice list based on the current provider
        self._populate_tts_voices()

        self.btn_preview = Gtk.Button(label="Preview")
        self.btn_preview.connect("clicked", self.on_preview_voice)

        voice_box.pack_start(self.combo_tts, True, True, 0)
        voice_box.pack_start(self.btn_preview, False, False, 0)
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(voice_box, False, True, 0)
        list_box.add(row)

        # HD Voice Toggle (only applies to OpenAI TTS)
        self.row_hd_voice = Gtk.ListBoxRow()
        _add_listbox_row_margins(self.row_hd_voice)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.row_hd_voice.add(hbox)
        label = Gtk.Label(label="TTS HD Voice", xalign=0)
        label.set_hexpand(True)
        label.set_tooltip_text("Use tts-1-hd model for higher quality (OpenAI TTS only)")
        self.switch_hd = Gtk.Switch()
        self.switch_hd.set_active(self.tts_hd)
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.switch_hd, False, True, 0)
        list_box.add(self.row_hd_voice)

        # Speech Prompt Template (for Gemini TTS and audio-preview models)
        self.row_prompt_template = Gtk.ListBoxRow()
        _add_listbox_row_margins(self.row_prompt_template)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.row_prompt_template.add(hbox)
        label = Gtk.Label(label="Speech Prompt Template", xalign=0)
        label.set_hexpand(False)
        label.set_tooltip_text('Use {text} as placeholder for the response text. Only applies to Gemini TTS and audio-preview models.')
        self.entry_audio_prompt_template = Gtk.Entry()
        self.entry_audio_prompt_template.set_hexpand(True)
        self.entry_audio_prompt_template.set_width_chars(50)
        default_template = 'Say cheerfully: {text}'
        self.entry_audio_prompt_template.set_placeholder_text(default_template)
        current_template = getattr(self, "tts_prompt_template", "") or getattr(self, "read_aloud_audio_prompt_template", "") or ""
        self.entry_audio_prompt_template.set_text(current_template)
        self.entry_audio_prompt_template.set_tooltip_text('Use {text} as placeholder for the response text. Only applies to Gemini TTS and audio-preview models.')
        hbox.pack_start(label, False, True, 0)
        hbox.pack_start(self.entry_audio_prompt_template, True, True, 0)
        list_box.add(self.row_prompt_template)

        # Update visibility of HD Voice and Prompt Template based on current provider
        self._update_tts_option_visibility()

        # --- Separator (as its own ListBoxRow, so it's visible) ---
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.set_margin_top(8)
        separator.set_margin_bottom(8)
        box.pack_start(separator, True, True, 0)
        row.add(box)
        # Make separator row not selectable/focusable:
        row.set_selectable(False)
        row.set_activatable(False)
        list_box.add(row)

        # Automatically read responses aloud
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Automatically read responses aloud", xalign=0)
        label.set_hexpand(True)
        self.switch_read_aloud = Gtk.Switch()
        current_read_aloud_enabled = bool(getattr(self, "read_aloud_enabled", False))
        self.switch_read_aloud.set_active(current_read_aloud_enabled)
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.switch_read_aloud, False, True, 0)
        list_box.add(row)

        # --- Separator (as its own ListBoxRow, so it's visible) ---
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.set_margin_top(8)
        separator.set_margin_bottom(8)
        box.pack_start(separator, True, True, 0)
        row.add(box)
        # Make separator row not selectable/focusable:
        row.set_selectable(False)
        row.set_activatable(False)
        list_box.add(row)

        # Realtime Voice
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
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

        self.stack.add_named(scroll, "Audio")

    # -----------------------------------------------------------------------
    # Tool Options page
    # -----------------------------------------------------------------------
    def _get_all_image_models(self):
        """
        Get all image-capable models from the catalog and custom models.
        
        Returns a sorted list of model IDs that have image generation capability.
        """
        image_models = set()
        
        # Get image models from the catalog
        for model_id, card in list_cards().items():
            if card.is_image_model() or card.capabilities.image_gen:
                image_models.add(model_id)
        
        # Add custom image models (from custom_models.json)
        for model_id, cfg in self.custom_models.items():
            if (cfg.get("api_type") or "").lower() == "images":
                image_models.add(model_id)
            # Also check if there's a card override with image_gen capability
            card = get_card(model_id, self.custom_models)
            if card and (card.is_image_model() or card.capabilities.image_gen):
                image_models.add(model_id)
        
        return sorted(image_models)

    def _refresh_image_model_dropdown(self):
        """Refresh the image model dropdown to include all image-capable models."""
        if not hasattr(self, 'combo_image_model') or self.combo_image_model is None:
            return
        
        # Get current value
        current_value = self.combo_image_model.get_active_text() or (self.combo_image_model.get_child().get_text() if self.combo_image_model.get_child() else '') or getattr(self, "image_model", "dall-e-3")
        
        # Clear and rebuild the list
        self.combo_image_model.remove_all()
        
        # Get all image models from catalog and custom models
        all_models = self._get_all_image_models()
        
        for model_id in all_models:
            self.combo_image_model.append_text(model_id)
        
        # Restore current value
        if current_value in all_models:
            active_index = all_models.index(current_value)
            self.combo_image_model.set_active(active_index)
        else:
            # Set as entry text if not in list (allows custom values)
            entry = self.combo_image_model.get_child()
            if entry:
                entry.set_text(current_value)

    def _build_tool_options_page(self):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        # Add explicit margins so layout is consistent across themes/desktops.
        # Some themes provide inner padding around stack pages, others do not.
        # By setting margins here, the Tool Options page will always have
        # comfortable spacing from the sidebar and window edges.
        list_box.set_margin_top(0)
        list_box.set_margin_bottom(0)
        list_box.set_margin_start(0)
        list_box.set_margin_end(0)
        scroll.add(list_box)

        # ---- Image Tool section ----
        header_row = Gtk.ListBoxRow()
        _add_listbox_row_margins(header_row)
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header_row.add(header_box)
        header_label = Gtk.Label()
        header_label.set_xalign(0)
        header_label.set_markup("<b>Image Tool</b>")
        header_box.pack_start(header_label, True, True, 0)
        list_box.add(header_row)

        # Enable Image Tool
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Enable Image Tool", xalign=0)
        label.set_hexpand(True)
        self.switch_image_tool_settings = Gtk.Switch()
        current_image_tool_enabled = bool(getattr(self, "image_tool_enabled", True))
        self.switch_image_tool_settings.set_active(current_image_tool_enabled)
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.switch_image_tool_settings, False, True, 0)
        list_box.add(row)

        # Preferred Image Model for the image tool
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Image Tool Model", xalign=0)
        label.set_hexpand(True)
        self.combo_image_model = Gtk.ComboBoxText.new_with_entry()

        # Get all image models from catalog and custom models
        all_image_models = self._get_all_image_models()

        for model_id in all_image_models:
            self.combo_image_model.append_text(model_id)

        current_image_model = getattr(self, "image_model", "dall-e-3")
        
        # If current model is in the list, select it; otherwise set as entry text
        if current_image_model in all_image_models:
            active_index = all_image_models.index(current_image_model)
            self.combo_image_model.set_active(active_index)
        else:
            entry = self.combo_image_model.get_child()
            if entry:
                entry.set_text(current_image_model)
        
        # Set entry width to fit the longest model name
        entry = self.combo_image_model.get_child()
        if entry and all_image_models:
            # Calculate width based on longest model name
            max_width = max(len(model_id) for model_id in all_image_models)
            # Use exact width - GTK handles dropdown arrow space automatically
            entry.set_width_chars(max_width)
        
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.combo_image_model, False, True, 0)
        list_box.add(row)

        # --- Separator (as its own ListBoxRow, so it's visible) ---
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.set_margin_top(8)
        separator.set_margin_bottom(8)
        box.pack_start(separator, True, True, 0)
        row.add(box)
        # Make separator row not selectable/focusable:
        row.set_selectable(False)
        row.set_activatable(False)
        list_box.add(row)

        # ---- Music Tool section ----
        header_row = Gtk.ListBoxRow()
        _add_listbox_row_margins(header_row)
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header_row.add(header_box)
        header_label = Gtk.Label()
        header_label.set_xalign(0)
        header_label.set_markup("<b>Music Tool</b>")
        header_box.pack_start(header_label, True, True, 0)
        list_box.add(header_row)

        # Enable Music Tool
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Enable Music Tool", xalign=0)
        label.set_hexpand(True)
        self.switch_music_tool_settings = Gtk.Switch()
        current_music_tool_enabled = bool(getattr(self, "music_tool_enabled", False))
        self.switch_music_tool_settings.set_active(current_music_tool_enabled)
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.switch_music_tool_settings, False, True, 0)
        list_box.add(row)

        # Music Player Executable / Command
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Music Player Command", xalign=0)
        label.set_hexpand(False)
        self.entry_music_player_path = Gtk.Entry()
        self.entry_music_player_path.set_hexpand(True)
        self.entry_music_player_path.set_width_chars(40)
        self.entry_music_player_path.set_placeholder_text('/usr/bin/mpv --playlist=<playlist>')
        self.entry_music_player_path.set_text(getattr(self, "music_player_path", "/usr/bin/mpv") or "/usr/bin/mpv")
        self.entry_music_player_path.set_tooltip_text(
            'Full command to launch your player. You can include arguments and use '
            '<playlist> as a placeholder for the generated playlist file. '
            'If <playlist> is omitted, the playlist path is passed as the last argument.'
        )
        hbox.pack_start(label, False, True, 0)
        hbox.pack_start(self.entry_music_player_path, True, True, 0)
        list_box.add(row)

        # Music Library Directory
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Music Library Directory", xalign=0)
        label.set_hexpand(False)
        self.entry_music_library_dir = Gtk.Entry()
        self.entry_music_library_dir.set_hexpand(True)
        self.entry_music_library_dir.set_width_chars(40)
        self.entry_music_library_dir.set_placeholder_text('/home/user/Music')
        self.entry_music_library_dir.set_text(getattr(self, "music_library_dir", "") or "")
        self.entry_music_library_dir.set_tooltip_text('Directory where your music files are stored (used by beets)')
        hbox.pack_start(label, False, True, 0)
        hbox.pack_start(self.entry_music_library_dir, True, True, 0)
        list_box.add(row)

        # Beets Library DB Path (optional, for advanced users)
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Beets Library DB (optional)", xalign=0)
        label.set_hexpand(False)
        self.entry_music_library_db = Gtk.Entry()
        self.entry_music_library_db.set_hexpand(True)
        self.entry_music_library_db.set_width_chars(30)
        self.entry_music_library_db.set_placeholder_text('Leave empty to use app default')
        self.entry_music_library_db.set_text(getattr(self, "music_library_db", "") or "")
        self.entry_music_library_db.set_tooltip_text('Path to beets library.db file (leave empty to use app-generated library)')
        self.btn_generate_library = Gtk.Button(label="Generate Library")
        self.btn_generate_library.set_tooltip_text('Scan Music Library Directory and generate a beets library')
        self.btn_generate_library.connect("clicked", self._on_generate_library_clicked)
        hbox.pack_start(label, False, True, 0)
        hbox.pack_start(self.entry_music_library_db, True, True, 0)
        hbox.pack_start(self.btn_generate_library, False, False, 0)
        list_box.add(row)

        # --- Separator (as its own ListBoxRow, so it's visible) ---
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.set_margin_top(8)
        separator.set_margin_bottom(8)
        box.pack_start(separator, True, True, 0)
        row.add(box)
        # Make separator row not selectable/focusable:
        row.set_selectable(False)
        row.set_activatable(False)
        list_box.add(row)

        # ---- Read Aloud Tool section ----
        header_row = Gtk.ListBoxRow()
        _add_listbox_row_margins(header_row)
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header_row.add(header_box)
        header_label = Gtk.Label()
        header_label.set_xalign(0)
        header_label.set_markup("<b>Read Aloud Tool</b>")
        header_box.pack_start(header_label, True, True, 0)
        list_box.add(header_row)

        # Enable Read Aloud Tool (model can invoke read_aloud)
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Enable Read Aloud Tool", xalign=0)
        label.set_hexpand(True)
        self.switch_read_aloud_tool = Gtk.Switch()
        current_read_aloud_tool_enabled = bool(getattr(self, "read_aloud_tool_enabled", False))
        self.switch_read_aloud_tool.set_active(current_read_aloud_tool_enabled)
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.switch_read_aloud_tool, False, True, 0)
        list_box.add(row)

        # --- Separator (as its own ListBoxRow, so it's visible) ---
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.set_margin_top(8)
        separator.set_margin_bottom(8)
        box.pack_start(separator, True, True, 0)
        row.add(box)
        # Make separator row not selectable/focusable:
        row.set_selectable(False)
        row.set_activatable(False)
        list_box.add(row)

        # ---- Music Tool section ----
        header_row = Gtk.ListBoxRow()
        _add_listbox_row_margins(header_row)
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header_row.add(header_box)
        header_label = Gtk.Label()
        header_label.set_xalign(0)
        header_label.set_markup("<b>Web Search Tool</b>")
        header_box.pack_start(header_label, True, True, 0)
        list_box.add(header_row)

        # Enable Web Search (provider-native tools)
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Enable Web Search", xalign=0)
        label.set_hexpand(True)
        self.switch_web_search_settings = Gtk.Switch()
        current_web_search_enabled = bool(getattr(self, "web_search_enabled", False))
        self.switch_web_search_settings.set_active(current_web_search_enabled)
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.switch_web_search_settings, False, True, 0)
        list_box.add(row)

        # Connect signals to enforce mutual exclusivity between auto-read and tool
        self.switch_read_aloud.connect("state-set", self._on_read_aloud_state_set)
        self.switch_read_aloud_tool.connect("state-set", self._on_read_aloud_tool_state_set)

        self.stack.add_named(scroll, "Tool Options")

    # -----------------------------------------------------------------------
    # System Prompts page
    # -----------------------------------------------------------------------
    def _parse_system_prompts_json(self):
        """
        Parse the system_prompts_json attribute into a list of prompt dicts.
        Falls back to a single 'default' prompt built from system_message if
        the JSON is empty or invalid.
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
        return prompts

    def _build_system_prompts_page(self):
        """Build a page for managing multiple named system prompts."""
        # Parse prompts from settings
        self._system_prompts_list = self._parse_system_prompts_json()
        
        # Determine active prompt ID
        active_id = getattr(self, "active_system_prompt_id", "") or ""
        # Validate that active_id exists in the list
        valid_ids = {p["id"] for p in self._system_prompts_list}
        if active_id not in valid_ids:
            active_id = self._system_prompts_list[0]["id"] if self._system_prompts_list else ""
        self._active_prompt_id = active_id

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(0)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)

        # --- Header row: Prompt selector + Add/Rename/Delete buttons ---
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        label = Gtk.Label(label="Prompt:", xalign=0)
        header_box.pack_start(label, False, False, 0)
        
        self._prompt_combo = Gtk.ComboBoxText()
        self._populate_prompt_combo()
        self._prompt_combo.connect("changed", self._on_prompt_combo_changed)
        header_box.pack_start(self._prompt_combo, False, False, 0)
        
        # Spacer
        header_box.pack_start(Gtk.Box(), True, True, 0)
        
        btn_add = Gtk.Button(label="Add")
        btn_add.connect("clicked", self._on_add_prompt_clicked)
        header_box.pack_start(btn_add, False, False, 0)
        
        btn_rename = Gtk.Button(label="Rename")
        btn_rename.connect("clicked", self._on_rename_prompt_clicked)
        header_box.pack_start(btn_rename, False, False, 0)
        
        self._btn_delete_prompt = Gtk.Button(label="Delete")
        self._btn_delete_prompt.connect("clicked", self._on_delete_prompt_clicked)
        header_box.pack_start(self._btn_delete_prompt, False, False, 0)
        
        vbox.pack_start(header_box, False, False, 0)

        # --- Text editor for the selected prompt ---
        frame = Gtk.Frame()
        frame.set_shadow_type(Gtk.ShadowType.IN)

        text_scroll = Gtk.ScrolledWindow()
        text_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        text_scroll.set_vexpand(True)

        self.entry_system_message = Gtk.TextView()
        self.entry_system_message.set_wrap_mode(Gtk.WrapMode.WORD)

        # Set outer margins on the TextView widget itself
        self.entry_system_message.set_margin_start(0)
        self.entry_system_message.set_margin_end(0)
        self.entry_system_message.set_margin_top(0)
        self.entry_system_message.set_margin_bottom(0)
        self.entry_system_message.set_editable(True)
        self.entry_system_message.set_cursor_visible(True)
        self.entry_system_message.set_can_focus(True)
        self.entry_system_message.set_accepts_tab(True)

        # Native CSS padding for the text area isn't supported in Gtk3; use set_left_margin()/set_right_margin()/set_top_margin()/set_bottom_margin() on the buffer.
        # Set padding by using Gtk.TextView's own margin APIs for the buffer.
        self.entry_system_message.set_left_margin(12)
        self.entry_system_message.set_right_margin(12)
        self.entry_system_message.set_top_margin(12)
        self.entry_system_message.set_bottom_margin(12)

        text_scroll.set_can_focus(False)
        frame.set_can_focus(False)

        def on_focus_in(widget, event):
            return False

        def on_button_press(widget, event):
            widget.grab_focus()
            return False

        self.entry_system_message.connect("focus-in-event", on_focus_in)
        self.entry_system_message.connect("button-press-event", on_button_press)
        
        # Connect buffer changed to save content back to the prompt list
        self.entry_system_message.get_buffer().connect("changed", self._on_prompt_content_changed)

        # Load active prompt content
        self._load_prompt_content()

        text_scroll.add(self.entry_system_message)
        frame.add(text_scroll)
        vbox.pack_start(frame, True, True, 0)
        
        # Update delete button sensitivity
        self._update_delete_button_sensitivity()

        self.stack.add_named(vbox, "System Prompts")

    def _populate_prompt_combo(self):
        """Populate the prompt combo box from _system_prompts_list."""
        self._prompt_combo.remove_all()
        for prompt in self._system_prompts_list:
            self._prompt_combo.append(prompt["id"], prompt["name"])
        # Set active
        if self._active_prompt_id:
            self._prompt_combo.set_active_id(self._active_prompt_id)
        elif self._system_prompts_list:
            self._prompt_combo.set_active(0)

    def _load_prompt_content(self):
        """Load the content of the active prompt into the TextView."""
        prompt = self._get_prompt_by_id(self._active_prompt_id)
        content = prompt["content"] if prompt else ""
        buf = self.entry_system_message.get_buffer()
        # Block signal temporarily to avoid feedback loop
        buf.handler_block_by_func(self._on_prompt_content_changed)
        buf.set_text(content)
        buf.handler_unblock_by_func(self._on_prompt_content_changed)

    def _get_prompt_by_id(self, prompt_id):
        """Return the prompt dict with the given ID, or None."""
        for p in self._system_prompts_list:
            if p["id"] == prompt_id:
                return p
        return None

    def _on_prompt_combo_changed(self, combo):
        """Handle selection change in the prompt combo box."""
        new_id = combo.get_active_id()
        if new_id and new_id != self._active_prompt_id:
            self._active_prompt_id = new_id
            self._load_prompt_content()
            self._update_delete_button_sensitivity()

    def _on_prompt_content_changed(self, buffer):
        """Update the prompt list when the user edits the content."""
        prompt = self._get_prompt_by_id(self._active_prompt_id)
        if prompt:
            start = buffer.get_start_iter()
            end = buffer.get_end_iter()
            prompt["content"] = buffer.get_text(start, end, True)

    def _update_delete_button_sensitivity(self):
        """Disable delete button if only one prompt remains."""
        self._btn_delete_prompt.set_sensitive(len(self._system_prompts_list) > 1)

    def _on_add_prompt_clicked(self, button):
        """Add a new prompt with a user-provided name."""
        dialog = Gtk.Dialog(
            title="Add System Prompt",
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL,
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Add", Gtk.ResponseType.OK)
        dialog.set_default_size(300, 100)
        
        box = dialog.get_content_area()
        box.set_spacing(6)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        label = Gtk.Label(label="Name:")
        entry = Gtk.Entry()
        entry.set_placeholder_text("New Prompt")
        entry.set_activates_default(True)
        hbox.pack_start(label, False, False, 0)
        hbox.pack_start(entry, True, True, 0)
        box.pack_start(hbox, False, False, 0)
        
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.show_all()
        
        response = dialog.run()
        name = entry.get_text().strip()
        dialog.destroy()
        
        if response == Gtk.ResponseType.OK and name:
            # Generate a unique ID
            import time
            new_id = f"prompt_{int(time.time() * 1000)}"
            new_prompt = {
                "id": new_id,
                "name": name,
                "content": "You are a helpful assistant."
            }
            self._system_prompts_list.append(new_prompt)
            self._active_prompt_id = new_id
            self._populate_prompt_combo()
            self._load_prompt_content()
            self._update_delete_button_sensitivity()

    def _on_rename_prompt_clicked(self, button):
        """Rename the currently selected prompt."""
        prompt = self._get_prompt_by_id(self._active_prompt_id)
        if not prompt:
            return
        
        dialog = Gtk.Dialog(
            title="Rename System Prompt",
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL,
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Rename", Gtk.ResponseType.OK)
        dialog.set_default_size(300, 100)
        
        box = dialog.get_content_area()
        box.set_spacing(6)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        label = Gtk.Label(label="Name:")
        entry = Gtk.Entry()
        entry.set_text(prompt["name"])
        entry.set_activates_default(True)
        hbox.pack_start(label, False, False, 0)
        hbox.pack_start(entry, True, True, 0)
        box.pack_start(hbox, False, False, 0)
        
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.show_all()
        
        response = dialog.run()
        new_name = entry.get_text().strip()
        dialog.destroy()
        
        if response == Gtk.ResponseType.OK and new_name:
            prompt["name"] = new_name
            self._populate_prompt_combo()

    def _on_delete_prompt_clicked(self, button):
        """Delete the currently selected prompt (if more than one exists)."""
        if len(self._system_prompts_list) <= 1:
            return
        
        prompt = self._get_prompt_by_id(self._active_prompt_id)
        if not prompt:
            return
        
        # Confirm deletion
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=f"Delete prompt \"{prompt['name']}\"?"
        )
        response = dialog.run()
        dialog.destroy()
        
        if response == Gtk.ResponseType.YES:
            self._system_prompts_list.remove(prompt)
            # Select the first remaining prompt
            self._active_prompt_id = self._system_prompts_list[0]["id"] if self._system_prompts_list else ""
            self._populate_prompt_combo()
            self._load_prompt_content()
            self._update_delete_button_sensitivity()

    # -----------------------------------------------------------------------
    # Custom Models page
    # -----------------------------------------------------------------------
    def _build_custom_models_page(self):
        page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        page_box.set_margin_top(12)
        page_box.set_margin_bottom(0)
        page_box.set_margin_start(12)
        page_box.set_margin_end(12)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        add_btn = Gtk.Button(label="Add Custom Model")
        add_btn.connect("clicked", self._on_add_custom_model)
        controls.pack_start(add_btn, False, False, 0)
        page_box.pack_start(controls, False, False, 0)

        # Encapsulate the list in a frame (like system prompts page)
        frame = Gtk.Frame()
        frame.set_shadow_type(Gtk.ShadowType.IN)

        self._custom_models_list = Gtk.ListBox()
        self._custom_models_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._custom_models_list.set_margin_top(0)
        self._custom_models_list.set_margin_bottom(0)
        self._custom_models_list.set_margin_start(0)
        self._custom_models_list.set_margin_end(0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.add(self._custom_models_list)
        frame.add(scroll)
        page_box.pack_start(frame, True, True, 0)

        self._refresh_custom_models_list()
        self.stack.add_named(page_box, "Custom Models")

    def _refresh_custom_models_list(self):
        for child in list(self._custom_models_list.get_children()):
            self._custom_models_list.remove(child)

        if not self.custom_models:
            row = Gtk.ListBoxRow()
            _add_listbox_row_margins(row)
            empty = Gtk.Label(label="No custom models added yet.", xalign=0)
            row.add(empty)
            self._custom_models_list.add(row)
            self._custom_models_list.show_all()
            return

        for model_id in sorted(self.custom_models.keys()):
            cfg = self.custom_models.get(model_id, {})
            row = Gtk.ListBoxRow()
            _add_listbox_row_margins(row)
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.add(hbox)
            
            label = Gtk.Label(
                label=f"{cfg.get('display_name', model_id)}  ({cfg.get('api_type', 'chat.completions')})",
                xalign=0,
            )
            label.set_hexpand(True)
            hbox.pack_start(label, True, True, 0)

            btn_test = Gtk.Button(label="Test")
            btn_test.connect("clicked", self._on_test_custom_model, model_id)
            hbox.pack_start(btn_test, False, False, 0)

            btn_edit = Gtk.Button(label="Edit")
            btn_edit.connect("clicked", self._on_edit_custom_model, model_id)
            hbox.pack_start(btn_edit, False, False, 0)

            btn_delete = Gtk.Button(label="Delete")
            btn_delete.connect("clicked", self._on_delete_custom_model, model_id)
            hbox.pack_start(btn_delete, False, False, 0)

            self._custom_models_list.add(row)

        self._custom_models_list.show_all()

    def _on_add_custom_model(self, button):
        dialog = CustomModelDialog(self)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            try:
                data = dialog.get_data()
                model_id = data["model_id"]
                
                # Check if model_id already exists
                if model_id in self.custom_models:
                    # Show confirmation dialog
                    confirm_dialog = Gtk.MessageDialog(
                        transient_for=self,
                        flags=0,
                        message_type=Gtk.MessageType.WARNING,
                        buttons=Gtk.ButtonsType.YES_NO,
                        text=f"Model '{model_id}' already exists"
                    )
                    confirm_dialog.format_secondary_text(
                        "A custom model with this ID already exists. "
                        "Do you want to overwrite it? If you want to edit the existing model, "
                        "please use the Edit button instead."
                    )
                    overwrite_response = confirm_dialog.run()
                    confirm_dialog.destroy()
                    
                    if overwrite_response != Gtk.ResponseType.YES:
                        dialog.destroy()
                        return
                
                self.custom_models[model_id] = data
                save_custom_models(self.custom_models)
                self._refresh_custom_models_list()
                
                # Automatically enable the model in the whitelist
                current_whitelist = getattr(self, 'custom_model_whitelist', '') or ''
                whitelist_models = set(m.strip() for m in current_whitelist.split(",") if m.strip())
                if model_id not in whitelist_models:
                    whitelist_models.add(model_id)
                    self.custom_model_whitelist = ",".join(sorted(whitelist_models))
                    # Save the updated whitelist immediately
                    settings = get_object_settings(self)
                    save_settings(convert_settings_for_save(settings))
                
                # Refresh image model dropdown if this is an image model
                if (data.get("api_type") or "").lower() == "images":
                    self._refresh_image_model_dropdown()
                # Update whitelist page if it's built
                if hasattr(self, '_model_whitelist_built') and self._model_whitelist_built:
                    # Refresh the whitelist page to show the new model with checkbox checked
                    self._populate_model_whitelist_sections(preserve_selections=True)
                elif hasattr(self, 'model_checkboxes') and 'custom' in self.model_checkboxes:
                    # Update checkbox if it exists (fallback for edge cases)
                    if model_id in self.model_checkboxes['custom']:
                        self.model_checkboxes['custom'][model_id].set_active(True)
                if hasattr(self, 'model_display_entries'):
                    for provider_key, entries in self.model_display_entries.items():
                        if model_id in entries:
                            display_name = data.get('display_name', '')
                            if display_name and display_name != model_id:
                                entries[model_id].set_text(display_name)
                            else:
                                entries[model_id].set_text('')
                if hasattr(self, "_model_cache"):
                    self._model_cache["custom"] = sorted(self.custom_models.keys())
            except Exception as e:
                self._show_error_dialog(str(e))
        dialog.destroy()

    def _on_edit_custom_model(self, button, model_id):
        cfg = self.custom_models.get(model_id, {})
        dialog = CustomModelDialog(self, initial=cfg)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            try:
                data = dialog.get_data()
                new_id = data["model_id"]
                if new_id != model_id and model_id in self.custom_models:
                    self.custom_models.pop(model_id, None)
                self.custom_models[new_id] = data
                save_custom_models(self.custom_models)
                self._refresh_custom_models_list()
                # Refresh image model dropdown if this is an image model or was an image model
                if (data.get("api_type") or "").lower() == "images" or (cfg.get("api_type") or "").lower() == "images":
                    self._refresh_image_model_dropdown()
                # Update whitelist page if it's built and has entries for this model
                if hasattr(self, 'model_display_entries'):
                    # Update the display name entry if it exists
                    for provider_key, entries in self.model_display_entries.items():
                        if model_id in entries:
                            display_name = data.get('display_name', '')
                            if display_name and display_name != model_id:
                                entries[model_id].set_text(display_name)
                            else:
                                entries[model_id].set_text('')
                if hasattr(self, "_model_cache"):
                    self._model_cache["custom"] = sorted(self.custom_models.keys())
            except Exception as e:
                self._show_error_dialog(str(e))
        dialog.destroy()

    def _on_delete_custom_model(self, button, model_id):
        if model_id in self.custom_models:
            cfg = self.custom_models.get(model_id, {})
            was_image_model = (cfg.get("api_type") or "").lower() == "images"
            self.custom_models.pop(model_id, None)
            save_custom_models(self.custom_models)
            self._refresh_custom_models_list()
            # Refresh image model dropdown if deleted model was an image model
            if was_image_model:
                self._refresh_image_model_dropdown()
            if hasattr(self, "_model_cache"):
                self._model_cache["custom"] = sorted(self.custom_models.keys())

    def _on_test_custom_model(self, button, model_id):
        cfg = self.custom_models.get(model_id, {})
        ok, msg = self._test_custom_model(cfg)
        message_type = Gtk.MessageType.INFO if ok else Gtk.MessageType.ERROR
        dlg = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=message_type,
            buttons=Gtk.ButtonsType.OK,
            text="Connection Test",
        )
        dlg.format_secondary_text(msg)
        dlg.run()
        dlg.destroy()

    def _test_custom_model(self, cfg: dict):
        try:
            from utils import resolve_api_key
            provider = CustomProvider()
            voice = cfg.get("voice")
            if not voice:
                cfg_voices = cfg.get("voices")
                if isinstance(cfg_voices, list) and cfg_voices:
                    voice = cfg_voices[0]
            provider.initialize(
                api_key=resolve_api_key(cfg.get("api_key", "")),
                endpoint=cfg.get("endpoint"),
                model_name=cfg.get("model_name") or cfg.get("model_id"),
                api_type=cfg.get("api_type") or "chat.completions",
                voice=voice,
            )
            return provider.test_connection()
        except Exception as exc:
            return False, str(exc)

    def get_custom_models(self):
        return dict(self.custom_models)

    def _show_error_dialog(self, message: str):
        dlg = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Error",
        )
        dlg.format_secondary_text(str(message))
        dlg.run()
        dlg.destroy()

    # -----------------------------------------------------------------------
    # Lazy builder for Model Whitelist page
    # -----------------------------------------------------------------------
    def _ensure_model_whitelist_page(self):
        """
        Ensure the Model Whitelist page is built.

        We delay constructing this page until it is first selected. If the
        on-disk model cache already contains model lists, no network calls are
        made and the page loads quickly. Otherwise, provider APIs are queried
        and results cached to disk for future sessions.
        """
        if not getattr(self, "_model_whitelist_built", False):
            self._build_model_whitelist_page()
            self._model_whitelist_built = True
            # The dialog may already be visible, so explicitly show new widgets.
            self.stack.show_all()

    # -----------------------------------------------------------------------
    # Model Whitelist page
    # -----------------------------------------------------------------------

    # Provider info used by the Model Whitelist page
    # (display_name, provider_key, whitelist_attr, env_key)
    _PROVIDER_INFO = [
        ("OpenAI", "openai", "openai_model_whitelist", "OPENAI_API_KEY"),
        ("Custom", "custom", "custom_model_whitelist", None),
        ("Gemini", "gemini", "gemini_model_whitelist", "GEMINI_API_KEY"),
        ("Grok", "grok", "grok_model_whitelist", "GROK_API_KEY"),
        ("Claude", "claude", "claude_model_whitelist", "CLAUDE_API_KEY"),
        ("Perplexity", "perplexity", "perplexity_model_whitelist", "PERPLEXITY_API_KEY"),
    ]

    def _build_model_whitelist_page(self):
        # Main container for the page
        page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        page_box.set_margin_top(12)
        page_box.set_margin_bottom(0)
        page_box.set_margin_start(12)
        page_box.set_margin_end(12)

        # --- Header row: Provider filter dropdown + Refresh button ---
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header_box.set_margin_bottom(6)

        # Provider filter combo box
        filter_label = Gtk.Label(label="Provider:")
        header_box.pack_start(filter_label, False, False, 0)

        self._provider_filter_combo = Gtk.ComboBoxText()
        self._provider_filter_combo.append("all", "All Providers")
        for display_name, provider_key, _, _ in self._PROVIDER_INFO:
            self._provider_filter_combo.append(provider_key, display_name)
        self._provider_filter_combo.set_active_id("all")
        self._provider_filter_combo.connect("changed", self._on_provider_filter_changed)
        header_box.pack_start(self._provider_filter_combo, False, False, 0)

        # Spacer
        header_box.pack_start(Gtk.Box(), True, True, 0)

        # Refresh button
        self._refresh_models_btn = Gtk.Button(label="Refresh Models")
        self._refresh_models_btn.connect("clicked", self._on_refresh_models_clicked)
        header_box.pack_start(self._refresh_models_btn, False, False, 0)

        page_box.pack_start(header_box, False, False, 0)

        # --- Encapsulate the list in a frame (like system prompts page) ---
        frame = Gtk.Frame()
        frame.set_shadow_type(Gtk.ShadowType.IN)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        self._whitelist_outer_box = Gtk.ListBox()
        self._whitelist_outer_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._whitelist_outer_box.set_margin_top(0)
        self._whitelist_outer_box.set_margin_bottom(0)
        self._whitelist_outer_box.set_margin_start(0)
        self._whitelist_outer_box.set_margin_end(0)
        scroll.add(self._whitelist_outer_box)
        frame.add(scroll)
        page_box.pack_start(frame, True, True, 0)

        # Track widgets per provider for filtering: {provider_key: [widgets...]}
        self._model_widgets_by_provider = {}

        # Populate the provider sections
        self._populate_model_whitelist_sections()

        self.stack.add_named(page_box, "Model Whitelist")

    def _populate_model_whitelist_sections(self, preserve_selections=False):
        """
        (Re)build the provider model checkbox sections inside `_whitelist_outer_box`.

        If `preserve_selections` is True, capture current checkbox states before
        clearing and re-apply them where models still exist.
        """
        # Optionally capture existing selections
        previous_selections = {}
        if preserve_selections and self.model_checkboxes:
            for pkey, cbs in self.model_checkboxes.items():
                previous_selections[pkey] = {mid for mid, cb in cbs.items() if cb.get_active()}

        # Clear existing children and reset tracking structures
        for child in self._whitelist_outer_box.get_children():
            self._whitelist_outer_box.remove(child)
        self.model_checkboxes = {}
        self.model_display_entries = {}  # Initialize display name entries storage
        self._model_widgets_by_provider = {}

        # Add header row with column labels
        header_row = Gtk.ListBoxRow()
        _add_listbox_row_margins(header_row)
        header_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header_row.add(header_hbox)
        
        # Model column header
        model_header = Gtk.Label(label="Model", xalign=0)
        model_header.set_size_request(200, -1)
        header_hbox.pack_start(model_header, False, False, 0)
        
        # Spacer to push header to the right
        header_hbox.pack_start(Gtk.Box(), True, True, 0)
        
        # Display Name column header (on the right side)
        display_header = Gtk.Label(label="Display Name", xalign=0)
        display_header.set_size_request(200, -1)
        header_hbox.pack_end(display_header, False, False, 0)
        
        header_row.set_selectable(False)
        header_row.set_activatable(False)
        self._whitelist_outer_box.add(header_row)

        for display_name, provider_key, whitelist_attr, _ in self._PROVIDER_INFO:
            widgets_for_provider = []

            # Section label
            row = Gtk.ListBoxRow()
            _add_listbox_row_margins(row)
            section_label = Gtk.Label(xalign=0)
            section_label.set_markup(f"<b>{display_name}</b>")
            row.add(section_label)
            self._whitelist_outer_box.add(row)
            widgets_for_provider.append(row)

            # Determine available models (from disk cache or network)
            available_models = self._get_available_models_for_provider(provider_key)

            # Determine which models should be checked
            if preserve_selections and provider_key in previous_selections:
                whitelist_set = previous_selections[provider_key]
            else:
                whitelist_str = getattr(self, whitelist_attr, "") or ""
                whitelist_set = set(m.strip() for m in whitelist_str.split(",") if m.strip())

            # Split into enabled and disabled, sort each alphabetically
            enabled_models = sorted([m for m in available_models if m in whitelist_set])
            disabled_models = sorted([m for m in available_models if m not in whitelist_set])

            # Create checkboxes with display name support
            self.model_checkboxes[provider_key] = {}
            self.model_display_entries = {}  # Store entry widgets for display names
            for model_id in enabled_models + disabled_models:
                row = Gtk.ListBoxRow()
                _add_listbox_row_margins(row)
                
                # Create horizontal box for checkbox, model ID label, and display name entry
                hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                row.add(hbox)
                
                # Checkbox with capability badges
                cb = Gtk.CheckButton()
                cb_label = Gtk.Label()
                cb_label.set_markup(self._format_model_label_with_badges(model_id))
                cb_label.set_xalign(0)
                cb.add(cb_label)
                cb.set_active(model_id in whitelist_set)
                cb.set_size_request(250, -1)
                cb.set_tooltip_text(self._get_capability_tooltip(model_id))
                hbox.pack_start(cb, False, False, 0)
                
                # Spacer to push entry box to the right
                hbox.pack_start(Gtk.Box(), True, True, 0)
                
                # Edit button for model card
                edit_btn = Gtk.Button.new_from_icon_name("document-edit-symbolic", Gtk.IconSize.BUTTON)
                edit_btn.set_tooltip_text("Edit model capabilities")
                edit_btn.connect("clicked", self._on_edit_model_card, model_id)
                hbox.pack_end(edit_btn, False, False, 0)
                
                # Display name entry (positioned on the right side)
                display_name_entry = Gtk.Entry()
                display_name_entry.set_placeholder_text("Display name (optional)")
                # Get display name - check custom models first, then display names setting
                # Reload display names fresh each time to ensure we have the latest
                display_name = self._get_display_name_for_model(model_id)
                # Set the text if we have a display name that's different from model_id
                if display_name and display_name != model_id:
                    display_name_entry.set_text(display_name)
                display_name_entry.connect("changed", self._on_display_name_changed, model_id)
                display_name_entry.set_size_request(200, -1)
                hbox.pack_end(display_name_entry, False, False, 0)
                
                # Store references
                if provider_key not in self.model_display_entries:
                    self.model_display_entries[provider_key] = {}
                self.model_display_entries[provider_key][model_id] = display_name_entry
                
                self._whitelist_outer_box.add(row)
                self.model_checkboxes[provider_key][model_id] = cb
                widgets_for_provider.append(row)

            # Separator between providers
            row = Gtk.ListBoxRow()
            _add_listbox_row_margins(row)
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            sep.set_margin_top(6)
            sep.set_margin_bottom(6)
            box.pack_start(sep, True, True, 0)
            row.add(box)
            row.set_selectable(False)
            row.set_activatable(False)
            self._whitelist_outer_box.add(row)
            widgets_for_provider.append(row)

            self._model_widgets_by_provider[provider_key] = widgets_for_provider

        # First show all newly added widgets, then apply the filter so that
        # a non-"all" selection is respected even after refresh.
        self._whitelist_outer_box.show_all()
        self._apply_provider_filter()

    def _apply_provider_filter(self):
        """Show/hide provider sections based on the current filter selection."""
        selected_id = self._provider_filter_combo.get_active_id() or "all"
        for provider_key, widgets in self._model_widgets_by_provider.items():
            visible = (selected_id == "all" or selected_id == provider_key)
            for widget in widgets:
                widget.set_visible(visible)

    def _on_provider_filter_changed(self, combo):
        """Handler for provider filter combo box changes."""
        self._apply_provider_filter()

    def _on_refresh_models_clicked(self, button):
        """Handler for the Refresh Models button."""
        from gi.repository import GLib

        button.set_sensitive(False)
        button.set_label("Refreshing...")

        def do_refresh():
            try:
                # Force refresh for all providers
                for _, provider_key, _, _ in self._PROVIDER_INFO:
                    self._get_available_models_for_provider(provider_key, force_refresh=True)
            except Exception as e:
                print(f"Error refreshing models: {e}")

            def finish_refresh():
                self._populate_model_whitelist_sections(preserve_selections=True)
                button.set_sensitive(True)
                button.set_label("Refresh Models")
                return False

            GLib.idle_add(finish_refresh)

        threading.Thread(target=do_refresh, daemon=True).start()

    def _get_display_name_for_model(self, model_id):
        """Get display name for a model, checking: custom models -> settings -> card -> empty."""
        # Check custom models first
        if model_id in self.custom_models:
            custom_model = self.custom_models[model_id]
            if custom_model.get('display_name') and custom_model.get('display_name') != model_id:
                return custom_model['display_name']
        
        # Check display names setting
        display_names = load_model_display_names()
        if model_id in display_names:
            return display_names[model_id]
        
        # Check model card for display name
        card = get_card(model_id)
        if card and card.display_name:
            return card.display_name
        
        return ''

    def _format_model_label_with_badges(self, model_id):
        """Format model label with capability badges from model card."""
        card = get_card(model_id)
        
        badges = []
        if card:
            if card.capabilities.vision:
                badges.append("V")
            if card.capabilities.tool_use:
                badges.append("T")
            if card.capabilities.web_search:
                badges.append("W")
            if card.capabilities.image_gen:
                badges.append("I")
            if card.capabilities.audio_out:
                badges.append("A")
        
        if badges:
            return f"{model_id}  <small><tt>[{' '.join(badges)}]</tt></small>"
        return model_id

    def _get_capability_tooltip(self, model_id):
        """Get a tooltip describing model capabilities."""
        card = get_card(model_id)
        if not card:
            return model_id
        
        lines = [model_id]
        caps = []
        if card.capabilities.vision:
            caps.append("Vision")
        if card.capabilities.tool_use:
            caps.append("Tools")
        if card.capabilities.web_search:
            caps.append("Web Search")
        if card.capabilities.image_gen:
            caps.append("Image Generation")
        if card.capabilities.audio_out:
            caps.append("Audio Output")
        if card.capabilities.files:
            caps.append("File Uploads")
        
        if caps:
            lines.append(f"Capabilities: {', '.join(caps)}")
        
        if card.api_family != "chat.completions":
            lines.append(f"API: {card.api_family}")
        
        return "\n".join(lines)
    
    def _on_display_name_changed(self, entry, model_id):
        """Handler for when display name entry is changed."""
        new_display_name = entry.get_text().strip()
        
        # Update custom model if it exists
        if model_id in self.custom_models:
            if new_display_name:
                self.custom_models[model_id]['display_name'] = new_display_name
            else:
                # Remove display_name if empty (fall back to model_id)
                self.custom_models[model_id].pop('display_name', None)
            save_custom_models(self.custom_models)
        else:
            # Update display names setting for non-custom models
            display_names = load_model_display_names()
            if new_display_name:
                display_names[model_id] = new_display_name
            else:
                # Remove if empty
                display_names.pop(model_id, None)
            # Save the updated display names
            save_model_display_names(display_names)
        
        # Reload custom models to ensure we have the latest data
        # (in case a custom model was added with the same ID)
        self.custom_models = load_custom_models()
        
        # Refresh custom models list if this model is a custom model
        if model_id in self.custom_models:
            self._refresh_custom_models_list()

    def _on_edit_model_card(self, button, model_id):
        """Open the Model Card Editor dialog for the given model."""
        dialog = ModelCardEditorDialog(self, model_id, self.custom_models)
        response = dialog.run()
        
        if response == Gtk.ResponseType.OK:
            # Save the override
            from model_cards import set_override
            override_data = dialog.get_override_data()
            set_override(model_id, override_data)
            # Refresh the whitelist to update capability badges
            self._populate_model_whitelist_sections(preserve_selections=True)
        elif response == Gtk.ResponseType.REJECT:
            # Reset was clicked - override already deleted, just refresh
            self._populate_model_whitelist_sections(preserve_selections=True)
        
        dialog.destroy()

    def _get_available_models_for_provider(self, provider_key, force_refresh=False):
        """
        Return a list of available models for the given provider.

        By default, reads from the on-disk cache (self._model_cache). If the
        cache is empty for this provider, or if `force_refresh` is True,
        fetches models from the provider API (or falls back to SETTINGS_CONFIG
        defaults) and updates the disk cache.
        """
        # Ensure we have an in-memory copy of the disk cache
        if not hasattr(self, '_model_cache') or self._model_cache is None:
            self._model_cache = load_model_cache()

        # Custom models are stored locally and do not require network fetch.
        if provider_key == "custom":
            models = sorted(self.custom_models.keys())
            self._model_cache[provider_key] = models
            save_model_cache(self._model_cache)
            return models

        cached = self._model_cache.get(provider_key)
        if cached and not force_refresh:
            return cached

        # Need to fetch from provider (network call) or fall back to defaults
        models = []
        provider = self.providers.get(provider_key)
        if provider:
            try:
                models = provider.get_available_models(disable_filter=True)
            except Exception as e:
                print(f"Error fetching models for {provider_key}: {e}")

        # If still empty, fall back to SETTINGS_CONFIG defaults
        if not models:
            config_key = f"{provider_key.upper()}_MODEL_WHITELIST"
            default_str = SETTINGS_CONFIG.get(config_key, {}).get('default', '')
            models = [m.strip() for m in default_str.split(",") if m.strip()]

        # Update in-memory and disk cache
        self._model_cache[provider_key] = models
        save_model_cache(self._model_cache)

        return models

    # -----------------------------------------------------------------------
    # API Keys page
    # -----------------------------------------------------------------------
    def _build_api_keys_page(self):
        keys = self.initial_api_keys
        # Separate standard keys from custom keys
        from utils import API_KEY_FIELDS
        standard_keys = {k: keys.get(k, '') for k in API_KEY_FIELDS}
        custom_keys = {k: v for k, v in keys.items() if k not in API_KEY_FIELDS}
        
        list_box, self.api_key_entries, size_groups = build_api_keys_editor(
            openai_key=standard_keys.get('openai', ''),
            gemini_key=standard_keys.get('gemini', ''),
            grok_key=standard_keys.get('grok', ''),
            claude_key=standard_keys.get('claude', ''),
            perplexity_key=standard_keys.get('perplexity', ''),
            custom_keys=custom_keys,
        )
        
        # Store list_box reference and size groups for adding custom keys
        self.api_keys_list_box = list_box
        self.label_size_group = size_groups['label']
        self.entry_size_group = size_groups['entry']
        
        # Store custom key rows for deletion and connect delete buttons
        self.custom_key_rows = []
        for row in list_box.get_children():
            if hasattr(row, 'custom_key_name'):
                self.custom_key_rows.append(row)
                # Connect delete button if it exists
                if hasattr(row, 'delete_button'):
                    row.delete_button.connect("clicked", lambda w, r=row, k=row.custom_key_name: self._on_delete_custom_key(w, r, k))
        
        # Add "Add Custom Key" button row
        add_button_row = Gtk.ListBoxRow()
        _add_listbox_row_margins(add_button_row, top=12, bottom=4)
        add_button_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        add_button_row.add(add_button_hbox)
        add_button_hbox.pack_start(Gtk.Box(), True, True, 0)  # spacer
        self.btn_add_custom_key = Gtk.Button(label="Add Custom Key")
        self.btn_add_custom_key.set_tooltip_text("Add a custom API key with a name and value")
        self.btn_add_custom_key.connect("clicked", self._on_add_custom_key_clicked)
        add_button_hbox.pack_start(self.btn_add_custom_key, False, False, 0)
        list_box.add(add_button_row)
        
        # Add a final row in the same ListBox for the Save button
        button_row = Gtk.ListBoxRow()
        _add_listbox_row_margins(button_row, top=12, bottom=4)
        button_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_row.add(button_hbox)
        button_hbox.pack_start(Gtk.Box(), True, True, 0)  # spacer
        self.btn_save_api_keys = Gtk.Button(label="Save API Keys")
        self.btn_save_api_keys.set_tooltip_text(
            "Save the current API keys so they are available next time you start ChatGTK."
        )
        self.btn_save_api_keys.connect("clicked", self._on_save_api_keys_clicked)
        button_hbox.pack_start(self.btn_save_api_keys, False, False, 0)
        list_box.add(button_row)

        self.stack.add_named(list_box, "API Keys")

    # -----------------------------------------------------------------------
    # Voice preview handlers
    # -----------------------------------------------------------------------
    def on_preview_voice(self, widget):
        """Preview the selected TTS voice. Generate and save if missing."""
        selected_provider = self.combo_tts_provider.get_active_id() or "openai"
        selected_voice = self.combo_tts.get_active_text()
        voice_name_lower = selected_voice.lower() if selected_voice else ""

        # Check for custom TTS providers
        custom_model_cfg = self.custom_models.get(selected_provider) if hasattr(self, 'custom_models') else None
        is_custom_tts = custom_model_cfg and (custom_model_cfg.get("api_type") or "").lower() == "tts"

        if is_custom_tts:
            # Use a cached preview if available
            safe_provider = "".join(c if c.isalnum() else "_" for c in selected_provider)
            preview_dir = Path(BASE_DIR) / "preview_custom"
            preview_file = preview_dir / f"{safe_provider}_{voice_name_lower or 'default'}.wav"

            if preview_file.exists():
                try:
                    subprocess.Popen(['paplay', str(preview_file)])
                except Exception as e:
                    self._show_preview_error(str(e))
                return

            # Generate a new preview clip
            from ai_providers import CustomProvider
            from utils import resolve_api_key

            provider = CustomProvider()
            voice_to_use = selected_voice or custom_model_cfg.get("voice") or "default"
            try:
                provider.initialize(
                    api_key=resolve_api_key(custom_model_cfg.get("api_key", "")),
                    endpoint=custom_model_cfg.get("endpoint", ""),
                    model_name=custom_model_cfg.get("model_name") or custom_model_cfg.get("model_id") or selected_provider,
                    api_type="tts",
                    voice=voice_to_use,
                )

                preview_text = "Hey there!"
                preview_dir.mkdir(parents=True, exist_ok=True)
                audio_bytes = provider.generate_speech(preview_text, voice_to_use)

                with open(preview_file, 'wb') as f:
                    f.write(audio_bytes)

                subprocess.Popen(['paplay', str(preview_file)])
            except Exception as e:
                self._show_preview_error(str(e))
            return

        if selected_provider == "gemini":
            # Gemini TTS preview
            preview_dir = Path(BASE_DIR) / "gemini_preview"
            preview_file = preview_dir / f"chirp3-hd-{voice_name_lower}.wav"

            if preview_file.exists():
                # Play existing preview
                try:
                    subprocess.Popen(['paplay', str(preview_file)])
                except Exception as e:
                    self._show_preview_error(str(e))
                return

            # Generate missing Gemini preview
            gemini_provider = self.providers.get('gemini')
            if not gemini_provider:
                self._show_preview_error("Gemini API key not configured. Please add your Gemini API key in Settings > API Keys.")
                return

            preview_text = f"Hello! This is the {selected_voice} voice."

            try:
                # Ensure preview directory exists
                preview_dir.mkdir(parents=True, exist_ok=True)

                # Generate speech using Gemini TTS
                audio_bytes = gemini_provider.generate_speech(preview_text, selected_voice)

                # Save to preview file
                with open(preview_file, 'wb') as f:
                    f.write(audio_bytes)

                # Play the generated preview
                subprocess.Popen(['paplay', str(preview_file)])

            except Exception as e:
                self._show_preview_error(str(e))
            return

        # OpenAI TTS preview
        preview_dir = Path(BASE_DIR) / "preview"
        preview_file = preview_dir / f"{voice_name_lower}.wav"

        if preview_file.exists():
            # Play existing preview
            try:
                subprocess.Popen(['paplay', str(preview_file)])
            except Exception as e:
                self._show_preview_error(str(e))
            return

        # Generate missing OpenAI preview
        if not self.ai_provider:
            self._show_preview_error("OpenAI API key not configured. Please add your API key in Settings > API Keys.")
            return

        preview_text = f"Hello! This is the {selected_voice} voice."

        try:
            # Ensure preview directory exists
            preview_dir.mkdir(parents=True, exist_ok=True)

            # Generate speech using OpenAI TTS and save to preview file
            with self.ai_provider.audio.speech.with_streaming_response.create(
                model="tts-1-hd" if self.tts_hd else "tts-1",
                voice=selected_voice,
                input=preview_text
            ) as response:
                with open(preview_file, 'wb') as f:
                    for chunk in response.iter_bytes():
                        f.write(chunk)

            # Play the generated preview
            subprocess.Popen(['paplay', str(preview_file)])

        except Exception as e:
            self._show_preview_error(str(e))

    def _show_preview_error(self, message: str):
        """Show an error dialog for voice preview failures."""
        error_dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Error Preview Voice"
        )
        error_dialog.format_secondary_text(message)
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
    # TTS Voice Provider helpers
    # -----------------------------------------------------------------------
    # Voice lists for each TTS provider
    OPENAI_TTS_VOICES = ["alloy", "ash", "coral", "echo", "fable", "onyx", "nova", "shimmer"]
    GEMINI_TTS_VOICES = [
        "Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Aoede",
        "Callirrhoe", "Autonoe", "Enceladus", "Iapetus", "Umbriel", "Algieba",
        "Despina", "Erinome", "Algenib", "Rasalgethi", "Laomedeia", "Achernar",
        "Alnilam", "Schedar", "Gacrux", "Pulcherrima", "Achird", "Zubenelgenubi",
        "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat"
    ]

    def _populate_tts_voices(self):
        """Populate the TTS voice combo based on the currently selected provider."""
        # Remember current selection if any
        current_voice = self.combo_tts.get_active_text()

        # Clear existing items
        self.combo_tts.remove_all()

        # Get the selected provider
        provider_id = self.combo_tts_provider.get_active_id() or "openai"

        # Check if this is a custom TTS model
        custom_model_cfg = self.custom_models.get(provider_id) if hasattr(self, 'custom_models') else None
        is_custom_tts = custom_model_cfg and (custom_model_cfg.get("api_type") or "").lower() == "tts"

        if is_custom_tts:
            # Custom TTS model - use the provided voice list or fallback voice
            cfg_voices = custom_model_cfg.get("voices")
            voices = []
            if isinstance(cfg_voices, list):
                voices.extend([v for v in cfg_voices if isinstance(v, str) and v.strip()])
            custom_voice = (custom_model_cfg.get("voice") or "").strip()
            if custom_voice and custom_voice not in voices:
                voices.insert(0, custom_voice)
            if not voices:
                voices = ["default"]
        elif provider_id == "gemini":
            voices = self.GEMINI_TTS_VOICES
        else:
            # OpenAI TTS and audio-preview models use the same OpenAI voices
            voices = self.OPENAI_TTS_VOICES

        for voice in voices:
            self.combo_tts.append_text(voice)

        # Try to restore previous selection, or use saved setting, or default to first
        saved_voice = getattr(self, "tts_voice", None)
        if current_voice and current_voice in voices:
            self.combo_tts.set_active(voices.index(current_voice))
        elif saved_voice and saved_voice in voices:
            self.combo_tts.set_active(voices.index(saved_voice))
        else:
            self.combo_tts.set_active(0)

    def _update_tts_option_visibility(self):
        """Show/hide HD Voice and Prompt Template rows based on the selected TTS provider."""
        provider_id = self.combo_tts_provider.get_active_id() or "openai"
        
        # Check if this is a custom TTS model
        custom_model_cfg = self.custom_models.get(provider_id) if hasattr(self, 'custom_models') else None
        is_custom_tts = custom_model_cfg and (custom_model_cfg.get("api_type") or "").lower() == "tts"
        
        # HD Voice only applies to OpenAI TTS (tts-1 / tts-1-hd), not custom models
        if hasattr(self, 'row_hd_voice'):
            if provider_id == "openai" and not is_custom_tts:
                self.row_hd_voice.show()
            else:
                self.row_hd_voice.hide()
        
        # Prompt Template only applies to Gemini TTS and audio-preview models (not custom)
        if hasattr(self, 'row_prompt_template'):
            if provider_id in ("gemini", "gpt-4o-audio-preview", "gpt-4o-mini-audio-preview") and not is_custom_tts:
                self.row_prompt_template.show()
            else:
                self.row_prompt_template.hide()

    def _on_tts_provider_changed(self, combo):
        """Handle TTS provider selection change."""
        self._populate_tts_voices()
        self._update_tts_option_visibility()

    # -----------------------------------------------------------------------
    # Read Aloud mutual exclusivity handlers
    # -----------------------------------------------------------------------
    def _on_read_aloud_state_set(self, switch, state):
        """When auto-read is enabled, disable the read aloud tool."""
        if state and self.switch_read_aloud_tool.get_active():
            self.switch_read_aloud_tool.set_active(False)
        return False  # Allow the state change to proceed

    def _on_read_aloud_tool_state_set(self, switch, state):
        """When read aloud tool is enabled, disable auto-read."""
        if state and self.switch_read_aloud.get_active():
            self.switch_read_aloud.set_active(False)
        return False  # Allow the state change to proceed

    # -----------------------------------------------------------------------
    # Beets library generation handler
    # -----------------------------------------------------------------------
    def _on_generate_library_clicked(self, widget):
        """Generate a beets library from the Music Library Directory."""
        from gi.repository import GLib

        music_dir = self.entry_music_library_dir.get_text().strip()
        if not music_dir:
            error_dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text="Music Library Directory Required"
            )
            error_dialog.format_secondary_text(
                "Please enter a Music Library Directory path before generating a library."
            )
            error_dialog.run()
            error_dialog.destroy()
            return

        if not os.path.isdir(music_dir):
            error_dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text="Invalid Directory"
            )
            error_dialog.format_secondary_text(
                f"The directory does not exist: {music_dir}"
            )
            error_dialog.run()
            error_dialog.destroy()
            return

        # Determine library path in app folder
        library_db_path = os.path.join(PARENT_DIR, "music_library.db")

        # Disable the button during generation
        self.btn_generate_library.set_sensitive(False)
        self.btn_generate_library.set_label("Generating...")

        def generate_library_thread():
            """Background thread to generate the beets library."""
            error_msg = None
            try:
                from beets.library import Library
                from beets import util
                import beets.autotag

                # Remove existing library if present
                if os.path.exists(library_db_path):
                    os.remove(library_db_path)

                # Create a new library
                lib = Library(library_db_path, directory=music_dir)

                # Walk the music directory and add tracks
                tracks_added = 0
                for root, dirs, files in os.walk(music_dir):
                    for filename in files:
                        filepath = os.path.join(root, filename)
                        # Check if it's a music file by extension
                        ext = os.path.splitext(filename)[1].lower()
                        if ext in ('.mp3', '.flac', '.ogg', '.m4a', '.wav', '.aac', '.wma', '.opus', '.aiff', '.ape'):
                            try:
                                # Import the item into the library
                                from beets.library import Item
                                item = Item.from_path(filepath)
                                lib.add(item)
                                tracks_added += 1
                            except Exception as e:
                                print(f"Could not add {filepath}: {e}")
                                continue

                # Commit changes
                lib._close()

                if tracks_added == 0:
                    error_msg = f"No music files found in {music_dir}"
                else:
                    # Success - update UI on main thread
                    def update_ui_success():
                        self.entry_music_library_db.set_text(library_db_path)
                        self.btn_generate_library.set_sensitive(True)
                        self.btn_generate_library.set_label("Generate Library")

                        success_dialog = Gtk.MessageDialog(
                            transient_for=self,
                            flags=0,
                            message_type=Gtk.MessageType.INFO,
                            buttons=Gtk.ButtonsType.OK,
                            text="Library Generated"
                        )
                        success_dialog.format_secondary_text(
                            f"Successfully added {tracks_added} tracks to the library.\n"
                            f"Library saved to: {library_db_path}"
                        )
                        success_dialog.run()
                        success_dialog.destroy()
                        return False

                    GLib.idle_add(update_ui_success)
                    return

            except ImportError:
                error_msg = "The beets library is not installed. Please install it with: pip install beets"
            except Exception as e:
                error_msg = f"Error generating library: {e}"

            # Handle error on main thread
            def update_ui_error():
                self.btn_generate_library.set_sensitive(True)
                self.btn_generate_library.set_label("Generate Library")

                error_dialog = Gtk.MessageDialog(
                    transient_for=self,
                    flags=0,
                    message_type=Gtk.MessageType.ERROR,
                    buttons=Gtk.ButtonsType.OK,
                    text="Library Generation Failed"
                )
                error_dialog.format_secondary_text(error_msg)
                error_dialog.run()
                error_dialog.destroy()
                return False

            GLib.idle_add(update_ui_error)

        # Run in background thread
        thread = threading.Thread(target=generate_library_thread, daemon=True)
        thread.start()

    # -----------------------------------------------------------------------
    # Collect settings
    # -----------------------------------------------------------------------
    def get_settings(self):
        """Return updated settings from dialog."""
        # Get active prompt content for backward compatibility (system_message)
        active_prompt = self._get_prompt_by_id(self._active_prompt_id)
        system_message = active_prompt["content"] if active_prompt else ""
        
        # Serialize the full prompts list to JSON
        system_prompts_json = json.dumps(self._system_prompts_list)

        # Build whitelist strings from checkboxes, but only if the Model
        # Whitelist page was actually built/visited. Otherwise, preserve the
        # existing values so opening the dialog without touching that section
        # does not clear any whitelists.
        model_page_built = getattr(self, "_model_whitelist_built", False)

        def whitelist_str(provider_key, attr_name):
            if not model_page_built:
                return getattr(self, attr_name, "")
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
            'system_prompts_json': system_prompts_json,
            'active_system_prompt_id': self._active_prompt_id,
            'microphone': self.combo_mic.get_active_text() or 'default',
            'tts_voice_provider': self.combo_tts_provider.get_active_id() or 'openai',
            'tts_voice': self.combo_tts.get_active_text(),
            'realtime_voice': self.combo_realtime.get_active_text(),
            'max_tokens': int(self.spin_max_tokens.get_value()),
            'source_theme': self.combo_theme.get_active_text(),
            'latex_dpi': int(self.spin_latex_dpi.get_value()),
            'latex_color': self.btn_latex_color.get_rgba().to_string(),
            'tts_hd': self.switch_hd.get_active(),
            'image_model': self.combo_image_model.get_active_text() or (self.combo_image_model.get_child().get_text() if self.combo_image_model.get_child() else '') or 'dall-e-3',
            'image_tool_enabled': self.switch_image_tool_settings.get_active(),
            'music_tool_enabled': self.switch_music_tool_settings.get_active(),
            'web_search_enabled': self.switch_web_search_settings.get_active(),
            'music_player_path': self.entry_music_player_path.get_text().strip() or '/usr/bin/mpv',
            'music_library_dir': self.entry_music_library_dir.get_text().strip(),
            'music_library_db': self.entry_music_library_db.get_text().strip(),
            # Model whitelists
            'openai_model_whitelist': whitelist_str('openai', 'openai_model_whitelist'),
            'gemini_model_whitelist': whitelist_str('gemini', 'gemini_model_whitelist'),
            'grok_model_whitelist': whitelist_str('grok', 'grok_model_whitelist'),
            'claude_model_whitelist': whitelist_str('claude', 'claude_model_whitelist'),
            'custom_model_whitelist': whitelist_str('custom', 'custom_model_whitelist'),
            # Read Aloud settings (uses unified TTS settings above)
            'read_aloud_enabled': self.switch_read_aloud.get_active(),
            'read_aloud_tool_enabled': self.switch_read_aloud_tool.get_active(),
            # Speech prompt template for Gemini TTS and audio-preview models
            'tts_prompt_template': self.entry_audio_prompt_template.get_text().strip(),
            # Conversation buffer length (string: "ALL", "0", "10", etc.)
            'conversation_buffer_length': (self.entry_conv_buffer.get_text() or "ALL").strip(),
            # Window / tray behavior
            'minimize_to_tray_enabled': self.switch_minimize_to_tray.get_active(),
            # Model display names - preserve what was saved during the dialog session
            # Load current value from settings file (already in JSON string format)
            'model_display_names': load_settings().get('MODEL_DISPLAY_NAMES', ''),
        }

    def get_api_keys(self):
        """Return API keys from the API Keys page."""
        keys = {
            'openai': self.api_key_entries['openai'].get_text().strip(),
            'gemini': self.api_key_entries['gemini'].get_text().strip(),
            'grok': self.api_key_entries['grok'].get_text().strip(),
            'claude': self.api_key_entries['claude'].get_text().strip(),
            'perplexity': self.api_key_entries['perplexity'].get_text().strip(),
        }
        # Add custom keys
        from utils import API_KEY_FIELDS
        for key_name, entry in self.api_key_entries.items():
            if key_name not in API_KEY_FIELDS:
                keys[key_name] = entry.get_text().strip()
        return keys

    def _on_add_custom_key_clicked(self, widget):
        """Show a dialog to add a custom API key."""
        dialog = Gtk.Dialog(
            title="Add Custom API Key",
            transient_for=self,
            flags=0,
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Add", Gtk.ResponseType.OK)
        
        content = dialog.get_content_area()
        content.set_spacing(12)
        content.set_margin_start(12)
        content.set_margin_end(12)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        
        # Name entry
        name_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        name_label = Gtk.Label(label="Name:", xalign=0)
        name_label.set_size_request(180, -1)
        name_entry = Gtk.Entry()
        name_entry.set_placeholder_text("e.g., myapi")
        name_box.pack_start(name_label, False, False, 0)
        name_box.pack_start(name_entry, True, True, 0)
        content.pack_start(name_box, False, False, 0)
        
        # Value entry
        value_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        value_label = Gtk.Label(label="Value:", xalign=0)
        value_label.set_size_request(180, -1)
        value_entry = Gtk.Entry()
        value_entry.set_visibility(False)
        value_entry.set_placeholder_text("API key value")
        value_box.pack_start(value_label, False, False, 0)
        value_box.pack_start(value_entry, True, True, 0)
        content.pack_start(value_box, False, False, 0)
        
        dialog.show_all()
        
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            key_name = name_entry.get_text().strip()
            key_value = value_entry.get_text().strip()
            
            if not key_name:
                dialog.destroy()
                msg = Gtk.MessageDialog(
                    transient_for=self,
                    flags=0,
                    message_type=Gtk.MessageType.ERROR,
                    buttons=Gtk.ButtonsType.OK,
                    text="Invalid Name",
                )
                msg.format_secondary_text("Please enter a name for the custom API key.")
                msg.run()
                msg.destroy()
                return
            
            # Check if key name already exists
            from utils import API_KEY_FIELDS
            if key_name in API_KEY_FIELDS or key_name in self.api_key_entries:
                dialog.destroy()
                msg = Gtk.MessageDialog(
                    transient_for=self,
                    flags=0,
                    message_type=Gtk.MessageType.ERROR,
                    buttons=Gtk.ButtonsType.OK,
                    text="Duplicate Name",
                )
                msg.format_secondary_text(f"A key with the name '{key_name}' already exists.")
                msg.run()
                msg.destroy()
                return
            
            # Add the custom key row
            self._add_custom_key_row(key_name, key_value)
        
        dialog.destroy()
    
    def _add_custom_key_row(self, key_name, key_value):
        """Add a custom key row to the list box."""
        list_box = self.api_keys_list_box
        if not list_box:
            return
        
        # Find the position to insert (before the "Add Custom Key" button)
        add_button_row = None
        for row in list_box.get_children():
            if hasattr(row, 'get_children') and row.get_children():
                hbox = row.get_children()[0]
                if isinstance(hbox, Gtk.Box):
                    for widget in hbox.get_children():
                        if isinstance(widget, Gtk.Button) and widget.get_label() == "Add Custom Key":
                            add_button_row = row
                            break
                if add_button_row:
                    break
        
        # Create the custom key row
        row = Gtk.ListBoxRow()
        row.custom_key_name = key_name
        _add_listbox_row_margins(row)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        
        label = Gtk.Label(label=f"{key_name} API Key", xalign=0)
        label.set_hexpand(False)  # Don't expand, use fixed width via size group
        # Add label to size group for uniform width
        self.label_size_group.add_widget(label)
        
        entry = Gtk.Entry()
        entry.set_hexpand(True)  # Entry expands to fill remaining space
        entry.set_visibility(False)
        entry.set_text(key_value)
        # Add to size group for uniform width
        self.entry_size_group.add_widget(entry)
        
        # Delete button
        delete_btn = Gtk.Button.new_from_icon_name("edit-delete", Gtk.IconSize.BUTTON)
        delete_btn.set_tooltip_text("Delete this custom key")
        delete_btn.connect("clicked", lambda w: self._on_delete_custom_key(w, row, key_name))
        
        hbox.pack_start(label, False, False, 0)  # Pack label with False for expand
        hbox.pack_start(entry, True, True, 0)  # Entry expands
        hbox.pack_start(delete_btn, False, False, 0)
        
        # Insert before the "Add Custom Key" button
        if add_button_row:
            list_box.insert(row, list_box.get_children().index(add_button_row))
        else:
            list_box.add(row)
        
        # Store entry in api_key_entries
        self.api_key_entries[key_name] = entry
        self.custom_key_rows.append(row)
        
        list_box.show_all()
    
    def _on_delete_custom_key(self, widget, row, key_name):
        """Delete a custom key row."""
        # Remove from entries
        if key_name in self.api_key_entries:
            del self.api_key_entries[key_name]
        
        # Remove from custom_key_rows
        if row in self.custom_key_rows:
            self.custom_key_rows.remove(row)
        
        # Find the list box and remove the row
        list_box = None
        for child in self.stack.get_children():
            if isinstance(child, Gtk.ListBox):
                list_box = child
                break
        
        if list_box:
            list_box.remove(row)

    def _on_save_api_keys_clicked(self, widget):
        """
        Persist the current API keys to the per-user API keys file.

        This does not close the dialog; it simply writes the keys so they can
        be loaded automatically on the next run of the application.
        """
        keys = self.get_api_keys()
        save_api_keys(keys)

        # Give the user a small confirmation message.
        msg = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="API Keys Saved",
        )
        msg.format_secondary_text(
            "Your API keys have been saved and will be restored automatically "
            "the next time you start ChatGTK."
        )
        msg.run()
        msg.destroy()


# ---------------------------------------------------------------------------
# ToolsDialog – unchanged
# ---------------------------------------------------------------------------

class ToolsDialog(Gtk.Dialog):
    """Dialog for configuring tool enablement (image, music, web search, read aloud)."""

    def __init__(self, parent, **settings):
        super().__init__(title="Tools", transient_for=parent, flags=0)
        apply_settings(self, settings)
        self.set_modal(True)
        self.set_default_size(400, 200)

        box = self.get_content_area()
        box.set_spacing(6)

        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        list_box.set_margin_top(0)
        list_box.set_margin_bottom(0)
        list_box.set_margin_start(0)
        list_box.set_margin_end(0)
        box.pack_start(list_box, True, True, 0)

        # Enable/disable image tool for text models
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
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
        _add_listbox_row_margins(row)
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

        # Enable/disable provider-native web search tools for text models
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Enable Web Search", xalign=0)
        label.set_hexpand(True)
        self.switch_web_search = Gtk.Switch()
        current_web_search_enabled = bool(getattr(self, "web_search_enabled", False))
        self.switch_web_search.set_active(current_web_search_enabled)
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.switch_web_search, False, True, 0)
        list_box.add(row)

        # Enable/disable read aloud tool for text models
        row = Gtk.ListBoxRow()
        _add_listbox_row_margins(row)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Enable Read Aloud Tool", xalign=0)
        label.set_hexpand(True)
        self.switch_read_aloud_tool = Gtk.Switch()
        current_read_aloud_tool_enabled = bool(getattr(self, "read_aloud_tool_enabled", False))
        self.switch_read_aloud_tool.set_active(current_read_aloud_tool_enabled)
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.switch_read_aloud_tool, False, True, 0)
        list_box.add(row)

        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("OK", Gtk.ResponseType.OK)

        self.show_all()

    def get_tool_settings(self):
        """Return the tool settings from the dialog."""
        return {
            "image_tool_enabled": self.switch_image_tool.get_active(),
            "music_tool_enabled": self.switch_music_tool.get_active(),
            "web_search_enabled": self.switch_web_search.get_active(),
            "read_aloud_tool_enabled": self.switch_read_aloud_tool.get_active(),
        }


# ---------------------------------------------------------------------------
# PromptEditorDialog – large editor for composing prompts
# ---------------------------------------------------------------------------

class PromptEditorDialog(Gtk.Dialog):
    """Dialog providing a larger multiline editor for composing prompts."""

    def __init__(self, parent, initial_text: str = ""):
        super().__init__(title="Edit Prompt", transient_for=parent, flags=0)
        self.set_modal(True)

        # Default size; user can resize further
        self.set_default_size(800, 500)

        content = self.get_content_area()
        content.set_spacing(6)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)
        content.pack_start(vbox, True, True, 0)

        # Optional hint label
        label = Gtk.Label(
            label="Compose a longer or multi-line prompt below.",
            xalign=0,
        )
        vbox.pack_start(label, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        vbox.pack_start(scroll, True, True, 0)

        self.textview = Gtk.TextView()
        self.textview.set_wrap_mode(Gtk.WrapMode.WORD)
        self.textview.set_accepts_tab(True)

        buf = self.textview.get_buffer()
        buf.set_text(initial_text or "")

        scroll.add(self.textview)

        # Dialog buttons
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Use Prompt", Gtk.ResponseType.OK)

        self.show_all()

    def get_text(self) -> str:
        """Return the full prompt text from the editor."""
        buf = self.textview.get_buffer()
        start_iter = buf.get_start_iter()
        end_iter = buf.get_end_iter()
        return buf.get_text(start_iter, end_iter, True)


# ---------------------------------------------------------------------------
# APIKeyDialog – kept for legacy compatibility; uses the shared helper
# ---------------------------------------------------------------------------

class APIKeyDialog(Gtk.Dialog):
    """Dialog for managing API keys for different providers."""

    def __init__(self, parent, openai_key='', gemini_key='', grok_key='', claude_key='', perplexity_key=''):
        super().__init__(title="API Keys", transient_for=parent, flags=0)
        self.set_modal(True)
        self.set_default_size(500, 300)

        box = self.get_content_area()
        box.set_spacing(6)

        list_box, self.entries, _ = build_api_keys_editor(
            openai_key=openai_key,
            gemini_key=gemini_key,
            grok_key=grok_key,
            claude_key=claude_key,
            perplexity_key=perplexity_key,
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
            'perplexity': self.entries['perplexity'].get_text().strip(),
        }
