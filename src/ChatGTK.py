#!/usr/bin/env python3
import os
os.environ['AUDIODEV'] = 'pulse'  # Force use of PulseAudio
import gi
import re
import threading
import os  # Import os to read/write environment variables and settings
import sounddevice as sd  # For recording audio
import soundfile as sf    # For saving audio files
import numpy as np       # For audio processing
import tempfile         # For temporary files
from pathlib import Path # For path handling
import subprocess
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
from config import SETTINGS_FILE, HISTORY_DIR, BASE_DIR, SETTINGS_CONFIG
from audio import record_audio
# Initialize provider as None
ai_provider = None

gi.require_version("Gtk", "3.0")
# For syntax highlighting:
gi.require_version("GtkSource", "4")

from gi.repository import Gtk, GLib, Pango, GtkSource 

# Path to settings file (in same directory as this script)
# SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.cfg")

class SettingsDialog(Gtk.Dialog):
    def __init__(self, parent, ai_provider=None, **settings):
        super().__init__(title="Settings", transient_for=parent, flags=0)
        self.ai_provider = ai_provider  # Store the ai_provider
        apply_settings(self, settings)
        self.set_modal(True)
        self.set_default_size(500, 600)  # Made taller to accommodate all content

        # Get the content area
        box = self.get_content_area()
        box.set_spacing(6)  # Add some spacing between elements

        # Create list box directly (no scrolled window)
        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        
        # Style the list box
        list_box.set_margin_top(12)
        list_box.set_margin_bottom(12)
        list_box.set_margin_start(12)
        list_box.set_margin_end(12)

        # Add list box directly to the content area
        box.pack_start(list_box, True, True, 0)

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
        self.scale_temp.set_size_request(200, -1)  # Set a reasonable width for the scale
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
        
        # Get list of available microphones
        devices = []
        all_devices = []
        try:
            devices = sd.query_devices()
            for device in devices:
                if device['max_input_channels'] > 0:  # Only input devices
                    self.combo_mic.append_text(device['name'])
                    all_devices.append(device['name'])
            if not all_devices:
                self.combo_mic.append_text("default")
        except Exception as e:
            print("Error getting audio devices:", e)
            self.combo_mic.append_text("default")
            all_devices = []

        # Set active microphone from settings
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
        
        # Available TTS voices
        tts_voices = ["alloy", "ash", "coral", "echo", "fable", "onyx", "nova", "shimmer"]
        for voice in tts_voices:
            self.combo_tts.append_text(voice)
        
        # Set active voice from settings
        if self.tts_voice in tts_voices:
            self.combo_tts.set_active(tts_voices.index(self.tts_voice))
        else:
            self.combo_tts.set_active(0)
        
        # Preview button
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
        self.switch_hd.set_active(self.tts_hd)  # Set from settings
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
        
        # Available realtime voices
        realtime_voices = ["alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse"]
        for voice in realtime_voices:
            self.combo_realtime.append_text(voice)
        
        # Set active voice from settings (default to alloy if not set)
        if self.realtime_voice in realtime_voices:
            self.combo_realtime.set_active(realtime_voices.index(self.realtime_voice))
        else:
            self.combo_realtime.set_active(0)
        
        # Preview button for realtime voices
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
        self.spin_max_tokens.set_range(0, 32000)  # OpenAI's maximum is 32k for some models
        self.spin_max_tokens.set_increments(100, 1000)
        self.spin_max_tokens.set_value(float(self.max_tokens))
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.spin_max_tokens, False, True, 0)
        list_box.add(row)

        # Add theme selector (before System Message)
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Code Theme", xalign=0)
        label.set_hexpand(True)
        self.combo_theme = Gtk.ComboBoxText()
        
        # Get available themes
        scheme_manager = GtkSource.StyleSchemeManager.get_default()
        themes = scheme_manager.get_scheme_ids()
        
        # Get current theme from settings
        settings = load_settings()
        current_theme = settings.get('SOURCE_THEME', 'solarized-dark')
        
        # Add themes to combo box
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
        self.spin_latex_dpi.set_range(72, 600)  # Reasonable DPI range
        self.spin_latex_dpi.set_increments(1, 10)
        self.spin_latex_dpi.set_value(float(self.latex_dpi))
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.spin_latex_dpi, False, True, 0)
        list_box.add(row)

        # System Message (moved to end)
        row = Gtk.ListBoxRow()
        row.set_activatable(False)  # Disable row activation
        row.set_selectable(False)   # Disable row selection
        
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        row.add(vbox)
        
        label = Gtk.Label(label="System Prompt", xalign=0)
        vbox.pack_start(label, False, False, 0)
        
        # Create text view inside a frame for better visual separation
        frame = Gtk.Frame()
        frame.set_shadow_type(Gtk.ShadowType.IN)
        
        # Create scrolled window specifically for the text view
        text_scroll = Gtk.ScrolledWindow()
        text_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        text_scroll.set_size_request(-1, 150)  # Fixed height for the text area
        
        self.entry_system_message = Gtk.TextView()
        self.entry_system_message.set_wrap_mode(Gtk.WrapMode.WORD)
        self.entry_system_message.set_margin_start(6)
        self.entry_system_message.set_margin_end(6)
        self.entry_system_message.set_margin_top(6)
        self.entry_system_message.set_margin_bottom(6)
        self.entry_system_message.set_editable(True)
        self.entry_system_message.set_cursor_visible(True)
        
        # Make sure TextView can receive focus and input
        self.entry_system_message.set_can_focus(True)
        self.entry_system_message.set_accepts_tab(True)
        
        # Make sure parent widgets don't interfere with events
        text_scroll.set_can_focus(False)
        frame.set_can_focus(False)
        vbox.set_can_focus(False)
        row.set_can_focus(False)
        
        # Connect focus events
        def on_focus_in(widget, event):
            return False  # Allow focus
            
        def on_button_press(widget, event):
            widget.grab_focus()
            return False  # Allow event propagation
            
        self.entry_system_message.connect("focus-in-event", on_focus_in)
        self.entry_system_message.connect("button-press-event", on_button_press)
        
        # Set the text after configuring the TextView
        self.entry_system_message.get_buffer().set_text(self.system_message)
        
        text_scroll.add(self.entry_system_message)
        frame.add(text_scroll)
        vbox.pack_start(frame, True, True, 0)
        
        list_box.add(row)

        # Add buttons
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("OK", Gtk.ResponseType.OK)

        self.show_all()

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
            # Create a temporary file for the speech
            temp_dir = Path(tempfile.gettempdir())
            temp_file = temp_dir / "voice_preview.mp3"
            
            # Generate speech with proper streaming
            with self.ai_provider.audio.speech.with_streaming_response.create(
                model="tts-1-hd" if self.tts_hd else "tts-1",
                voice=selected_voice,
                input=preview_text
            ) as response:
                # Save to file
                with open(temp_file, 'wb') as f:
                    for chunk in response.iter_bytes():
                        f.write(chunk)
            
            # Play using system audio
            os.system(f"paplay {temp_file}")
            
            # Clean up after a delay to ensure playback completes
            def cleanup():
                import time
                time.sleep(3)  # Wait for playback to finish
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

    def get_settings(self):
        """Return updated settings from dialog."""
        buffer = self.entry_system_message.get_buffer()
        system_message = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
        
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
            'tts_hd': self.switch_hd.get_active()
        }

    def on_preview_realtime_voice(self, widget):
        """Preview the selected realtime voice using prepared WAV files."""
        selected_voice = self.combo_realtime.get_active_text()
        preview_file = Path(BASE_DIR) / "preview" / f"{selected_voice}.wav"
        
        try:
            if not preview_file.exists():
                raise FileNotFoundError(f"Preview file not found: {preview_file}")
            
            # Play using system audio
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
        
        # Initialize window
        self.set_default_size(self.window_width, self.window_height)

        # Initialize chat state
        self.current_chat_id = None  # None means this is a new, unsaved chat
        self.conversation_history = [
            {"role": "system", "content": self.system_message}
        ]

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

        # API Key input with focus-out handler
        lbl_api = Gtk.Label(label="API Key:")
        self.entry_api = Gtk.Entry()
        self.entry_api.set_visibility(False)  # Hide API key text
        self.entry_api.connect("focus-out-event", self.on_api_key_changed)

        # Initialize model combo before trying to use it
        self.combo_model = Gtk.ComboBoxText()
        
        # Check for API key in environment variable and pre-populate if exists
        env_api_key = os.environ.get('OPENAI_API_KEY', '')
        if env_api_key:
            global ai_provider
            self.entry_api.set_text(env_api_key)
            ai_provider = get_ai_provider('openai')
            ai_provider.initialize(env_api_key)
            self.fetch_models_async()
        else:
            # Set some default models without fetching
            default_models = ["gpt-3.5-turbo", "gpt-4", "gpt-4o-mini"]
            for model in default_models:
                self.combo_model.append_text(model)
            if self.default_model in default_models:
                self.combo_model.set_active(default_models.index(self.default_model))
            else:
                self.combo_model.set_active(0)

        hbox_top.pack_start(lbl_api, False, False, 0)
        hbox_top.pack_start(self.entry_api, True, True, 0)

        hbox_top.pack_start(self.combo_model, False, False, 0)

        # Settings button
        btn_settings = Gtk.Button(label="Settings")
        btn_settings.connect("clicked", self.on_open_settings)
        hbox_top.pack_start(btn_settings, False, False, 0)

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

        # Question input and send button
        hbox_input = Gtk.Box(spacing=6)
        self.entry_question = Gtk.Entry()
        self.entry_question.set_placeholder_text("Enter your question here...")
        self.entry_question.connect("activate", self.on_submit)
        btn_send = Gtk.Button(label="Send")
        btn_send.connect("clicked", self.on_submit)
        hbox_input.pack_start(self.entry_question, True, True, 0)
        hbox_input.pack_start(btn_send, False, False, 0)
        vbox_main.pack_start(hbox_input, False, False, 0)

        # Create horizontal box for buttons
        button_box = Gtk.Box(spacing=6)

        # Voice input button with recording state
        self.recording = False
        self.btn_voice = Gtk.Button(label="Start Voice Input")
        self.btn_voice.connect("clicked", self.on_voice_input)
        
        # Add voice button to horizontal box
        button_box.pack_start(self.btn_voice, True, True, 0)

        # Add history button to the same horizontal box
        self.history_button = Gtk.Button(label="Clear Chat")
        self.history_button.connect("clicked", self.on_clear_clicked)
        button_box.pack_start(self.history_button, True, True, 0)

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

        # Connect window size handlers
        self.connect("configure-event", self.on_configure_event)
        self.connect("destroy", self.on_destroy)

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
        cleanup_temp_files()
        Gtk.main_quit()

    def on_configure_event(self, widget, event):
        # Called whenever window is resized or moved
        if not self.is_maximized():
            width, height = self.get_size()
            self.current_geometry = (width, height)
        return False

    def update_model_list(self, models):
        """Update the model combo box with fetched models."""
        # Clear existing items
        self.combo_model.remove_all()
        
        # Get currently selected model
        current_model = self.default_model
        
        # Sort models alphabetically, excluding the current model
        other_models = sorted([m for m in models if m != current_model])
        
        # Add current model first if it exists in the list
        if current_model in models:
            self.combo_model.append_text(current_model)
        
        # Add remaining models
        for model in other_models:
            self.combo_model.append_text(model)
        
        # Set active model
        if current_model in models:
            self.combo_model.set_active(0)  # Current model is always first
        else:
            self.combo_model.set_active(0)  # Default to first model if current not found

        # Connect the changed signal handler
        self.combo_model.connect('changed', self.on_model_changed)
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

    def fetch_models_async(self):
        """Fetch available models asynchronously."""
        def fetch_thread():
            global ai_provider
            if not ai_provider:
                default_models = ["gpt-3.5-turbo", "gpt-4", "gpt-4-turbo-preview"]
                GLib.idle_add(self.update_model_list, default_models)
                return

            try:
                model_names = ai_provider.get_available_models()
                # Update GUI from main thread
                GLib.idle_add(self.update_model_list, model_names)
            except Exception as e:
                print(f"Error fetching models: {e}")
                # If fetch fails, ensure we have some default models
                default_models = ["gpt-3.5-turbo", "gpt-4", "gpt-4-turbo-preview"]
                GLib.idle_add(self.update_model_list, default_models)

        # Start fetch in background
        threading.Thread(target=fetch_thread, daemon=True).start()

    def on_open_settings(self, widget):
        # Pass ai_provider to the settings dialog
        dialog = SettingsDialog(self, ai_provider=ai_provider, **{k.lower(): getattr(self, k.lower()) 
                               for k in SETTINGS_CONFIG.keys()})
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            new_settings = dialog.get_settings()
            apply_settings(self, new_settings)
            save_settings(convert_settings_for_save(get_object_settings(self)))
            self.fetch_models_async()
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
        
        pattern = r'(--- Code Block Start \(.*?\) ---\n.*?\n--- Code Block End ---|--- Table Start ---\n.*?\n--- Table End ---)'
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
                                # Use resized image insertion for DALL-E images
                                if 'dalle_' in img_path:
                                    insert_resized_image(buffer, iter, img_path, text_view)
                                else:
                                    # Use regular insertion for other images (like LaTeX)
                                    insert_tex_image(buffer, iter, img_path)
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
        # Get the API key from the entry field
        api_key = self.entry_api.get_text().strip()
        if not api_key:
            self.show_error_dialog("Please enter your OpenAI API key")
            return False
        
        # Set the API key in environment for the websocket provider
        os.environ['OPENAI_API_KEY'] = api_key
        
        question = self.entry_question.get_text().strip()
        if not question:
            return

        # Check if this is a one off image generation request
        if question.lower().startswith("img:"):
            # Remove the "img:" prefix from the prompt
            question = question[4:].strip()
            self.append_message('user', question)
            self.conversation_history.append({"role": "user", "content": question})
            self.entry_question.set_text("")
            self.show_thinking_animation()
            # Switch to dall-e-3 model for image generation
            threading.Thread(
                target=self.call_openai_api,
                args=(api_key, "dall-e-3"),
                daemon=True
            ).start()
            return

        # Check if we're in realtime mode
        if "realtime" in self.combo_model.get_active_text().lower():
            if not hasattr(self, 'ws_provider'):
                self.ws_provider = OpenAIWebSocketProvider()
                # Connect to WebSocket server
                success = self.ws_provider.connect(
                    model=self.combo_model.get_active_text(),
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
        self.append_message('user', question)
        # Store user message in the chat history
        self.conversation_history.append({"role": "user", "content": question})
        
        # Assign a chat ID if none exists
        if self.current_chat_id is None:
            # New chat - generate name and save
            chat_name = generate_chat_name(self.conversation_history[1]['content'])
            self.current_chat_id = chat_name

        # Clear the question input
        self.entry_question.set_text("")
        
        # Show thinking animation before API call
        self.show_thinking_animation()
        
        # Call OpenAI API in a separate thread
        threading.Thread(
            target=self.call_openai_api,
            args=(api_key, self.combo_model.get_active_text()),
            daemon=True
        ).start()

    def call_openai_api(self, api_key, model):
        try:
            # Ensure we have a valid model
            if not model:
                model = "gpt-3.5-turbo"  # Default fallback
                print(f"No model selected, falling back to {model}")
            
            match model:
                case "dall-e-3":
                    # Get the last user message as the prompt
                    prompt = self.conversation_history[-1]["content"]
                    answer = ai_provider.generate_image(prompt, self.current_chat_id or "temp")
                case "gpt-4o-realtime-preview":
                    # Realtime audio model using websockets
                    return
                case "gpt-4o-mini-realtime-preview":
                    # Realtime audio model using websockets
                    return
                case _:
                    answer = ai_provider.generate_chat_completion(
                        messages=self.conversation_history,
                        model=model,
                        temperature=float(self.temperament),
                        max_tokens=self.max_tokens if self.max_tokens > 0 else None,
                        chat_id=self.current_chat_id
                    )

            self.conversation_history.append({"role": "assistant", "content": answer})

            # Update UI in main thread
            GLib.idle_add(self.hide_thinking_animation)
            GLib.idle_add(lambda: self.append_message('ai', format_response(answer)))
            GLib.idle_add(self.save_current_chat)
            
        except Exception as error:
            print(f"\nAPI Call Error: {error}")
            GLib.idle_add(self.hide_thinking_animation)
            GLib.idle_add(lambda: self.append_message('ai', f"** Error: {str(error)} **"))
            
        finally:
            GLib.idle_add(self.hide_thinking_animation)

    def audio_transcription(self, widget):
        """Handle audio transcription."""
        print("Audio transcription...")
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
                                        transcript = ai_provider.transcribe_audio(audio_file)
                                        
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
                    api_key = self.entry_api.get_text().strip()
                    if not api_key:
                        self.show_error_dialog("Please enter your OpenAI API key")
                        return False

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

    def on_clear_clicked(self, widget):
        """Clear the current chat and its associated files."""
        # Clear the display
        for child in self.conversation_box.get_children():
            child.destroy()
            
        # If this was a saved chat, clean up its files
        if self.current_chat_id:
            # Remove formula cache directory
            chat_dir = Path('history') / self.current_chat_id.replace('.json', '')
            if chat_dir.exists():
                import shutil
                shutil.rmtree(chat_dir)
            
            # Remove the chat history file
            history_file = Path('history') / self.current_chat_id
            if history_file.exists():
                history_file.unlink()
        
        # Reset conversation state
        self.conversation_history = [
            {"role": "system", "content": self.system_message}
        ]
        self.current_chat_id = None
        
        # Refresh the history list
        self.refresh_history_list()

    def on_api_key_changed(self, widget, event):
        """Handle API key changes and update model list if needed."""
        global ai_provider
        api_key = self.entry_api.get_text().strip()
        if api_key:  # Only update if we have a key
            ai_provider = get_ai_provider('openai')
            ai_provider.initialize(api_key)
            self.fetch_models_async()
        return False

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
        self.conversation_history = [
            {"role": "system", "content": self.system_message}
        ]
        
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
                            audio_dir = Path('history') / self.current_chat_id.replace('.json', '') / 'audio'
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
                    if 'dalle_' in img_path:
                        insert_resized_image(buffer, iter_, img_path, text_view)
                    else:
                        insert_tex_image(buffer, iter_, img_path)
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
