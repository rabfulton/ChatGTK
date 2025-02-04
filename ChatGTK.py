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
    is_latex_installed
)
from utils import (
    load_settings, 
    save_settings, 
    generate_chat_name, 
    save_chat_history, 
    load_chat_history,
    list_chat_histories
)

from openai import OpenAI

# Initialize client as None
client = None

gi.require_version("Gtk", "3.0")
# For syntax highlighting:
gi.require_version("GtkSource", "4")

from gi.repository import Gtk, GLib, Pango, GtkSource 

# Path to settings file (in same directory as this script)
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.cfg")

# Utility functions for response formatting

def format_code_blocks(text):
    # Updated pattern to capture optional language
    pattern = r'```(\w+)?(.*?)```'

    def replacer(match):
        # If the user provided a language after the triple backticks, group(1) will have it.
        code_lang = match.group(1)
        # If there's no specified language, default to 'python' or 'plaintext'
        if code_lang is None:
            code_lang = "plaintext"
        code_content = match.group(2).strip()
        # Replace triple backticks with markers that also store the language
        return f"--- Code Block Start ({code_lang}) ---" + code_content + "--- Code Block End ---"

    return re.sub(pattern, replacer, text, flags=re.DOTALL)

def format_bullet_points(text):
    # Replace lines starting with '-' or '*' with a bullet symbol
    return re.sub(r'^(?:-|\*)\s+', '• ', text, flags=re.MULTILINE)

def escape_for_pango_markup(text):
    # Escapes markup-sensitive characters for Pango markup
    return GLib.markup_escape_text(text)

def convert_double_asterisks_to_bold(text):
    # Convert **bold** to <b>bold</b>
    pattern = r'\*\*(.*?)\*\*'
    return re.sub(pattern, r'<b>\1</b>', text, flags=re.DOTALL)


def convert_h3_to_large(text, base_font_size):
    """Convert markdown headers to large text with appropriate sizing."""
    h3_size = (base_font_size + 2) * 1000
    h4_size = (base_font_size + 1) * 1000
    
    # Convert h3 headers (###)
    pattern = r'^###\s+(.*)$'
    text = re.sub(pattern, fr"<span size='{h3_size}'><b>\1</b></span>", text, flags=re.MULTILINE)
    
    # Convert h4 headers (####)
    pattern = r'^####\s+(.*)$'
    text = re.sub(pattern, fr"<span size='{h4_size}'><b>\1</b></span>", text, flags=re.MULTILINE)
    
    return text

def format_response(text):
    # 1. Format code blocks
    text = format_code_blocks(text)
    # 2. Format bullet points
    text = format_bullet_points(text)
    # We do not convert asterisks or ### here because we need to handle code blocks separately.
    return text

class SettingsDialog(Gtk.Dialog):
    def __init__(self, parent, ai_name, font_family, font_size, user_color, ai_color, default_model, system_message, temperament, microphone, tts_voice):
        super().__init__(title="Settings", transient_for=parent, flags=0)
        self.set_modal(True)
        self.set_default_size(500, 500)

        # Store current values
        self.ai_name = ai_name
        self.font_family = font_family
        self.font_size = font_size
        self.user_color = user_color
        self.ai_color = ai_color
        self.default_model = default_model
        self.system_message = system_message
        self.temperament = temperament
        self.current_microphone = microphone
        self.tts_voice = tts_voice

        box = self.get_content_area()
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.add(vbox)

        # AI name
        hbox_ai_name = Gtk.Box(spacing=6)
        lbl_ai_name = Gtk.Label(label="AI Name:")
        self.entry_ai_name = Gtk.Entry()
        self.entry_ai_name.set_text(self.ai_name)
        hbox_ai_name.pack_start(lbl_ai_name, False, False, 0)
        hbox_ai_name.pack_start(self.entry_ai_name, True, True, 0)
        vbox.pack_start(hbox_ai_name, False, False, 0)

        # Font family
        hbox_font = Gtk.Box(spacing=6)
        lbl_font = Gtk.Label(label="Font Family:")
        self.entry_font = Gtk.Entry()
        self.entry_font.set_text(self.font_family)
        hbox_font.pack_start(lbl_font, False, False, 0)
        hbox_font.pack_start(self.entry_font, True, True, 0)
        vbox.pack_start(hbox_font, False, False, 0)

        # Font size
        hbox_size = Gtk.Box(spacing=6)
        lbl_size = Gtk.Label(label="Font Size:")
        self.spin_size = Gtk.SpinButton()
        self.spin_size.set_range(6, 72)
        self.spin_size.set_increments(1, 2)
        self.spin_size.set_value(float(self.font_size))
        hbox_size.pack_start(lbl_size, False, False, 0)
        hbox_size.pack_start(self.spin_size, True, True, 0)
        vbox.pack_start(hbox_size, False, False, 0)

        # User color
        hbox_user_color = Gtk.Box(spacing=6)
        lbl_user_color = Gtk.Label(label="User Color:")
        self.entry_user_color = Gtk.Entry()
        self.entry_user_color.set_text(self.user_color)
        hbox_user_color.pack_start(lbl_user_color, False, False, 0)
        hbox_user_color.pack_start(self.entry_user_color, True, True, 0)
        vbox.pack_start(hbox_user_color, False, False, 0)

        # AI color
        hbox_ai_color = Gtk.Box(spacing=6)
        lbl_ai_color = Gtk.Label(label="AI Color:")
        self.entry_ai_color = Gtk.Entry()
        self.entry_ai_color.set_text(self.ai_color)
        hbox_ai_color.pack_start(lbl_ai_color, False, False, 0)
        hbox_ai_color.pack_start(self.entry_ai_color, True, True, 0)
        vbox.pack_start(hbox_ai_color, False, False, 0)

        # Default model
        hbox_model = Gtk.Box(spacing=6)
        lbl_model = Gtk.Label(label="Default Model:")
        self.entry_default_model = Gtk.Entry()
        self.entry_default_model.set_text(self.default_model)
        hbox_model.pack_start(lbl_model, False, False, 0)
        hbox_model.pack_start(self.entry_default_model, True, True, 0)
        vbox.pack_start(hbox_model, False, False, 0)

        # System message
        hbox_sys = Gtk.Box(spacing=6)
        lbl_sys = Gtk.Label(label="System Prompt:")
        self.entry_system_message = Gtk.Entry()
        self.entry_system_message.set_text(self.system_message)
        hbox_sys.pack_start(lbl_sys, False, False, 0)
        hbox_sys.pack_start(self.entry_system_message, True, True, 0)
        vbox.pack_start(hbox_sys, False, False, 0)

        # Temperament slider
        hbox_temp = Gtk.Box(spacing=6)
        lbl_temp = Gtk.Label(label="Temperament:")
        self.scale_temp = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.01)
        self.scale_temp.set_value(float(self.temperament))
        self.scale_temp.set_digits(2)  # show 2 decimals
        hbox_temp.pack_start(lbl_temp, False, False, 0)
        hbox_temp.pack_start(self.scale_temp, True, True, 0)
        vbox.pack_start(hbox_temp, False, False, 0)

        # Microphone selection
        hbox_mic = Gtk.Box(spacing=6)
        lbl_mic = Gtk.Label(label="Microphone:")
        self.combo_mic = Gtk.ComboBoxText()
        
        # Get list of available microphones
        try:
            devices = sd.query_devices()
            for i, device in enumerate(devices):
                if device['max_input_channels'] > 0:  # Only input devices
                    self.combo_mic.append_text(f"{device['name']}")
        except Exception as e:
            print("Error getting audio devices:", e)
            self.combo_mic.append_text("default")
        
        # Set active microphone from settings
        all_devices = [d['name'] for d in devices if d['max_input_channels'] > 0]
        if self.current_microphone in all_devices:
            self.combo_mic.set_active(all_devices.index(self.current_microphone))
        else:
            self.combo_mic.set_active(0)
        
        hbox_mic.pack_start(lbl_mic, False, False, 0)
        hbox_mic.pack_start(self.combo_mic, True, True, 0)
        vbox.pack_start(hbox_mic, False, False, 0)

        # TTS Voice selection
        hbox_tts = Gtk.Box(spacing=6)
        lbl_tts = Gtk.Label(label="AI Voice:")
        self.combo_tts = Gtk.ComboBoxText()
        
        # Available TTS voices
        tts_voices = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
        for voice in tts_voices:
            self.combo_tts.append_text(voice)
        
        # Set active voice from settings
        if self.tts_voice in tts_voices:
            self.combo_tts.set_active(tts_voices.index(self.tts_voice))
        else:
            self.combo_tts.set_active(0)
        
        # Preview button
        self.btn_preview = Gtk.Button(label="Preview Voice")
        self.btn_preview.connect("clicked", self.on_preview_voice)
        
        hbox_tts.pack_start(lbl_tts, False, False, 0)
        hbox_tts.pack_start(self.combo_tts, True, True, 0)
        hbox_tts.pack_start(self.btn_preview, False, False, 0)
        vbox.pack_start(hbox_tts, False, False, 0)

        # Buttons
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("OK", Gtk.ResponseType.OK)

        self.show_all()

    def on_preview_voice(self, widget):
        """Preview the selected TTS voice."""
        selected_voice = self.combo_tts.get_active_text()
        preview_text = f"Hello! This is the {selected_voice} voice."
        
        try:
            # Create a temporary file for the speech
            temp_dir = Path(tempfile.gettempdir())
            temp_file = temp_dir / "voice_preview.mp3"
            
            # Generate speech with proper streaming
            with client.audio.speech.with_streaming_response.create(
                model="tts-1",
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
        return {
            'ai_name': self.entry_ai_name.get_text(),
            'font_family': self.entry_font.get_text(),
            'font_size': int(self.spin_size.get_value()),
            'user_color': self.entry_user_color.get_text(),
            'ai_color': self.entry_ai_color.get_text(),
            'default_model': self.entry_default_model.get_text(),
            'system_message': self.entry_system_message.get_text(),
            'temperament': self.scale_temp.get_value(),
            'microphone': self.combo_mic.get_active_text() or 'default',
            'tts_voice': self.combo_tts.get_active_text()
        }

class OpenAIGTKClient(Gtk.Window):
    def __init__(self):
        super().__init__(title="ChatGTK Client")

        # Load settings
        loaded = load_settings()
        self.ai_name = loaded['AI_NAME']
        self.font_family = loaded['FONT_FAMILY']
        self.font_size = int(loaded['FONT_SIZE'])
        self.user_color = loaded['USER_COLOR']
        self.ai_color = loaded['AI_COLOR']
        self.default_model = loaded['DEFAULT_MODEL']
        self.window_width = int(loaded['WINDOW_WIDTH'])
        self.window_height = int(loaded['WINDOW_HEIGHT'])
        self.system_message = loaded['SYSTEM_MESSAGE']
        self.temperament = float(loaded['TEMPERAMENT'])
        self.microphone = loaded['MICROPHONE']
        self.tts_voice = loaded['TTS_VOICE']
        self.sidebar_visible = loaded['SIDEBAR_VISIBLE']
        
        self.sidebar_visible = loaded.get('SIDEBAR_VISIBLE', 'True').lower() == 'true'

        # Initialize chat state
        self.current_chat_id = None  # None means this is a new, unsaved chat
        self.conversation_history = [
            {"role": "system", "content": self.system_message}
        ]

        # Remember the current geometry if not maximized
        self.current_geometry = (self.window_width, self.window_height)

        # Set the initial window size
        self.set_default_size(self.window_width, self.window_height)

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
        self.history_list.connect('row-activated', self.on_history_selected)
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
        self.current_sidebar_width = int(loaded.get('SIDEBAR_WIDTH', '200'))
        self.paned.set_position(self.current_sidebar_width)

        # Update memory value without saving to file
        def on_paned_position_changed(paned, param):
            if not self.is_maximized():
                self.current_sidebar_width = paned.get_position()

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
            global client
            self.entry_api.set_text(env_api_key)
            client = OpenAI(api_key=env_api_key)
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
        self.history_button = Gtk.Button(label="Clear History")
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

        # Connect window size handlers
        self.connect("configure-event", self.on_configure_event)
        self.connect("destroy", self.on_destroy)
        
    def on_destroy(self, widget):
        """Save settings and cleanup before closing."""
        # Save all settings including sidebar width
        to_save = load_settings()
        width, height = self.current_geometry
        to_save['WINDOW_WIDTH'] = str(width)
        to_save['WINDOW_HEIGHT'] = str(height)
        to_save['SYSTEM_MESSAGE'] = self.system_message
        to_save['TEMPERAMENT'] = str(self.temperament)
        to_save['MICROPHONE'] = self.microphone
        to_save['TTS_VOICE'] = self.tts_voice
        to_save['SIDEBAR_WIDTH'] = str(self.current_sidebar_width)
        to_save['SIDEBAR_VISIBLE'] = str(self.sidebar_visible)
        save_settings(to_save)
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
        # Add new models
        for model in models:
            self.combo_model.append_text(model)
        # Set default model
        if self.default_model in models:
            self.combo_model.set_active(models.index(self.default_model))
        else:
            self.combo_model.set_active(0)
        return False

    def fetch_models_async(self):
        """Fetch available models asynchronously."""
        def fetch_thread():
            global client
            if not client:
                default_models = ["gpt-3.5-turbo", "gpt-4", "gpt-4o-mini"]
                GLib.idle_add(self.update_model_list, default_models)
                return

            try:
                models = client.models.list()
                model_names = [model.id for model in models]
                # Update GUI from main thread
                GLib.idle_add(self.update_model_list, model_names)
            except Exception as e:
                print(f"Error fetching models: {e}")
                # If fetch fails, ensure we have some default models
                default_models = ["gpt-3.5-turbo", "gpt-4", "gpt-4o-mini"]
                GLib.idle_add(self.update_model_list, default_models)

        # Start fetch in background
        threading.Thread(target=fetch_thread, daemon=True).start()

    def on_open_settings(self, widget):
        dialog = SettingsDialog(
            self,
            ai_name=self.ai_name,
            font_family=self.font_family,
            font_size=self.font_size,
            user_color=self.user_color,
            ai_color=self.ai_color,
            default_model=self.default_model,
            system_message=self.system_message,
            temperament=self.temperament,
            microphone=self.microphone,
            tts_voice=self.tts_voice
        )
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            new_settings = dialog.get_settings()
            self.ai_name = new_settings['ai_name']
            self.font_family = new_settings['font_family']
            self.font_size = new_settings['font_size']
            self.user_color = new_settings['user_color']
            self.ai_color = new_settings['ai_color']
            self.default_model = new_settings['default_model']
            self.system_message = new_settings['system_message']
            self.temperament = new_settings['temperament']
            self.microphone = new_settings['microphone']
            self.tts_voice = new_settings['tts_voice']

            # Re-populate model list so default can be enforced
            self.fetch_models_async()

            # Save to file
            to_save = load_settings()
            to_save['AI_NAME'] = self.ai_name
            to_save['FONT_FAMILY'] = self.font_family
            to_save['FONT_SIZE'] = str(self.font_size)
            to_save['USER_COLOR'] = self.user_color
            to_save['AI_COLOR'] = self.ai_color
            to_save['DEFAULT_MODEL'] = self.default_model
            to_save['SYSTEM_MESSAGE'] = self.system_message
            to_save['TEMPERAMENT'] = str(self.temperament)
            to_save['MICROPHONE'] = self.microphone
            to_save['TTS_VOICE'] = self.tts_voice
            save_settings(to_save)
        dialog.destroy()

    def append_user_message(self, text):
        """Add a user message as a label with user style."""
        lbl = Gtk.Label()
        lbl.set_selectable(True)
        lbl.set_line_wrap(True)
        lbl.set_line_wrap_mode(Gtk.WrapMode.WORD)
        lbl.set_xalign(0)  # left align
        # Set font color
        css = f"label {{ color: {self.user_color}; font-family: {self.font_family}; font-size: {self.font_size}pt; }}"
        self.apply_css(lbl, css)

        lbl.set_text(f"You: {text}")
        self.conversation_box.pack_start(lbl, False, False, 0)
        self.conversation_box.show_all()

    def create_source_view(self, code_content, code_lang):
        """Create a styled source view for code display."""
        source_view = GtkSource.View.new()
        
        # Apply styling
        css_provider = Gtk.CssProvider()
        css = f"""
            textview {{
                font-family: Monospace;
                font-size: {self.font_size}pt;
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
        style_scheme = scheme_manager.get_scheme("solarized-dark")
        
        buffer.set_language(lang)
        buffer.set_highlight_syntax(True)
        buffer.set_style_scheme(style_scheme)
        buffer.set_text(code_content)
        buffer.set_highlight_matching_brackets(False)
        
        # Set size request
        source_view.set_size_request(-1, 100)
        
        return source_view

    def append_ai_message(self, text):
        """Add an AI message with possible code blocks using GtkSourceView for syntax highlighting."""
        # Container for the entire AI response (including play/stop button)
        response_container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        
        # Container for the text content
        content_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        
        # First, show a label with the AI name.
        lbl_name = Gtk.Label()
        lbl_name.set_selectable(True)
        lbl_name.set_line_wrap(True)
        lbl_name.set_line_wrap_mode(Gtk.WrapMode.WORD)
        lbl_name.set_xalign(0)
        css_ai = f"label {{ color: {self.ai_color}; font-family: {self.font_family}; font-size: {self.font_size}pt; }}"
        self.apply_css(lbl_name, css_ai)
        lbl_name.set_text(f"{self.ai_name}:")
        content_container.pack_start(lbl_name, False, False, 0)

        # Add play/stop button
        btn_speak = Gtk.Button()
        
        # Calculate button size based on font size
        button_size = self.font_size * 2
        
        # Set fixed size and don't expand
        btn_speak.set_size_request(button_size, button_size)
        
        # Create images for play and stop icons
        icon_play = Gtk.Image.new_from_icon_name("media-playback-start", Gtk.IconSize.SMALL_TOOLBAR)
        icon_stop = Gtk.Image.new_from_icon_name("media-playback-stop", Gtk.IconSize.SMALL_TOOLBAR)
        btn_speak.set_image(icon_play)
        btn_speak.set_tooltip_text("Play response")

        # Store the full text for TTS (excluding code blocks)
        full_text = []

        # We split out code blocks by our markers (including optional language spec):
        segments = re.split(r'(--- Code Block Start \(.*?--- Code Block End ---)', text, flags=re.DOTALL)

        for seg in segments:
            if seg.startswith('--- Code Block Start ('):
                # Extract language from parentheses
                lang_match = re.search(r'^--- Code Block Start \((.*?)\) ---', seg)
                if lang_match:
                    code_lang = lang_match.group(1)
                else:
                    code_lang = "plaintext"

                # Now remove the leading marker line entirely
                code_content = re.sub(r'^--- Code Block Start \(.*?\) ---', '', seg)
                code_content = re.sub(r'--- Code Block End ---$', '', code_content)
                code_content = code_content.strip('\n')

                # Create source view using the new function
                source_view = self.create_source_view(code_content, code_lang)
                
                frame = Gtk.Frame()
                frame.add(source_view)
                content_container.pack_start(frame, False, False, 5)
                
                # Add a note about code block for TTS
                full_text.append("Code block follows.")
            else:
                if seg.strip():
                    # Process TeX expressions with chat_id
                    processed = process_tex_markup(seg, self.user_color, self.current_chat_id)
                    
                    if "<img" in processed:
                        # If we have images, use TextView
                        text_view = Gtk.TextView()
                        text_view.set_wrap_mode(Gtk.WrapMode.WORD)
                        text_view.set_editable(False)
                        text_view.set_cursor_visible(False)
                        text_view.set_pixels_above_lines(5)
                        text_view.set_pixels_below_lines(5)
                        text_view.set_left_margin(5)
                        text_view.set_right_margin(5)
                        
                        # Apply font using CSS instead of override_font
                        css_provider = Gtk.CssProvider()
                        css = f"""
                            textview {{
                                font-family: {self.font_family};
                                font-size: {self.font_size}pt;
                            }}
                        """
                        css_provider.load_from_data(css.encode())
                        text_view.get_style_context().add_provider(
                            css_provider,
                            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                        )
                        
                        buffer = text_view.get_buffer()
                        
                        # Process the text and add images
                        parts = re.split(r'(<img src="[^"]+"/>)', processed)
                        iter = buffer.get_start_iter()
                        
                        for part in parts:
                            if part.startswith('<img src="'):
                                # Extract image path and create pixbuf
                                img_path = re.search(r'src="([^"]+)"', part).group(1)
                                insert_tex_image(buffer, iter, img_path)
                            else:
                                # Process remaining text for other markup
                                text = process_inline_markup(part)
                                text = convert_double_asterisks_to_bold(text)
                                text = convert_h3_to_large(text, self.font_size)
                                buffer.insert_markup(iter, text, -1)
                        
                        content_container.pack_start(text_view, False, False, 0)
                    else:
                        # No images, use Label as before
                        processed = process_inline_markup(processed)
                        processed = convert_double_asterisks_to_bold(processed)
                        processed = convert_h3_to_large(processed, self.font_size)
                        
                        lbl_ai_text = Gtk.Label()
                        lbl_ai_text.set_selectable(True)
                        lbl_ai_text.set_line_wrap(True)
                        lbl_ai_text.set_line_wrap_mode(Gtk.WrapMode.WORD)
                        lbl_ai_text.set_xalign(0)
                        self.apply_css(lbl_ai_text, css_ai)
                        lbl_ai_text.set_use_markup(True)
                        lbl_ai_text.set_markup(processed)
                        content_container.pack_start(lbl_ai_text, False, False, 0)
                    
                    full_text.append(seg.strip())

        # Variable to track playback state
        is_playing = False
        cleanup_thread = None

        def on_speak_clicked(widget):
            nonlocal is_playing, cleanup_thread
            
            if not is_playing:
                # Start playback
                is_playing = True
                btn_speak.set_image(icon_stop)
                btn_speak.set_tooltip_text("Stop playback")
                
                def speak_thread():
                    nonlocal is_playing, cleanup_thread
                    try:
                        # Create a temporary file for the speech
                        temp_dir = Path(tempfile.gettempdir())
                        temp_file = temp_dir / "ai_speech.mp3"
                        
                        # Generate speech with proper streaming
                        with client.audio.speech.with_streaming_response.create(
                            model="tts-1",
                            voice=self.tts_voice,
                            input=" ".join(full_text)
                        ) as response:
                            # Save to file
                            with open(temp_file, 'wb') as f:
                                for chunk in response.iter_bytes():
                                    f.write(chunk)
                        
                        # Start playback process
                        self.current_playback_process = subprocess.Popen(['paplay', str(temp_file)])
                        
                        # Wait for playback to complete or be stopped
                        self.current_playback_process.wait()
                        
                        # Clean up after playback
                        def cleanup():
                            nonlocal is_playing
                            time.sleep(0.5)  # Small delay to ensure file is not in use
                            temp_file.unlink(missing_ok=True)
                            # Reset button only if playback completed naturally
                            if is_playing:
                                GLib.idle_add(btn_speak.set_image, icon_play)
                                GLib.idle_add(btn_speak.set_tooltip_text, "Play response")
                                is_playing = False
                        
                        cleanup_thread = threading.Thread(target=cleanup, daemon=True)
                        cleanup_thread.start()
                        
                    except Exception as e:
                        GLib.idle_add(self.append_message, 'ai', f"Error generating speech: {str(e)}")
                        GLib.idle_add(btn_speak.set_image, icon_play)
                        GLib.idle_add(btn_speak.set_tooltip_text, "Play response")
                        is_playing = False
                
                # Start playback in separate thread
                threading.Thread(target=speak_thread, daemon=True).start()
            
            else:
                # Stop playback
                is_playing = False
                if hasattr(self, 'current_playback_process'):
                    self.current_playback_process.terminate()
                btn_speak.set_image(icon_play)
                btn_speak.set_tooltip_text("Play response")
        
        # Connect the button click handler
        btn_speak.connect("clicked", on_speak_clicked)
        
        # Pack everything into the response container (only once!)
        response_container.pack_start(content_container, True, True, 0)
        response_container.pack_end(btn_speak, False, False, 0)
        
        self.conversation_box.pack_start(response_container, False, False, 0)
        self.conversation_box.show_all()

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

    def on_submit(self, widget):
        question = self.entry_question.get_text().strip()
        if not question:
            return

        api_key = self.entry_api.get_text().strip()
        if not api_key:
            self.append_message('ai', "** Error: Please enter your API key. **")
            return

        model = self.combo_model.get_active_text()
        # Use new method to append user message
        self.append_message('user', question)
        # Store user message in the chat history
        self.conversation_history.append({"role": "user", "content": question})

        # Clear the question input
        self.entry_question.set_text("")
        # Call OpenAI API in a separate thread so the UI doesn't freeze
        threading.Thread(
            target=self.call_openai_api,
            args=(api_key, model),
            daemon=True
        ).start()

    def call_dalle_api(self, prompt):
        """Handle image generation requests to DALL-E."""
        try:
            response = client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size="1024x1024",
                quality="standard",
                n=1,
            )
            
            # Get the image URL
            image_url = response.data[0].url
            
            # Download the image
            import requests
            from datetime import datetime
            
            # Create images directory if it doesn't exist
            chat_id = self.current_chat_id or generate_chat_name(prompt)
            images_dir = Path('history') / chat_id.replace('.json', '') / 'images'
            images_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate unique filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            image_path = images_dir / f"dalle_{timestamp}.png"
            
            # Download and save image
            response = requests.get(image_url)
            image_path.write_bytes(response.content)
            
            # Return path to saved image
            return f'<img src="{image_path}"/>'
            
        except Exception as e:
            return f"Error generating image: {str(e)}"

    def call_openai_api(self, api_key, model):
        if not client:
            self.append_message('ai', "** Error: Please enter your API key. **")
            return
            
        try:
            match model:
                case "dall-e-3":
                    # Get the last user message as the prompt
                    prompt = self.conversation_history[-1]["content"]
                    answer = self.call_dalle_api(prompt)
                case _:
                    # Regular chat completion
                    response = client.chat.completions.create(
                        model=model,
                        messages=self.conversation_history,
                        temperature=float(self.temperament),
                    )
                    answer = response.choices[0].message.content

            self.conversation_history.append({"role": "assistant", "content": answer})

            # Save after each response
            GLib.idle_add(self.save_current_chat)

            answer = format_response(answer)
            GLib.idle_add(self.append_message, 'ai', answer)
            
        except Exception as e:
            GLib.idle_add(self.append_message, 'ai', f"** Error: {str(e)} **")

    def record_audio(self, duration=5, sample_rate=16000):
        """Record audio for specified duration."""
        try:
            # Force use of PulseAudio
            os.environ['AUDIODEV'] = 'pulse'  # Force use of PulseAudio
            
            # Find the device index for the selected microphone
            devices = sd.query_devices()
            device_idx = None
            for i, device in enumerate(devices):
                if device['name'] == self.microphone and device['max_input_channels'] > 0:
                    device_idx = i
                    break
            
            # If selected microphone not found, use default
            if device_idx is None:
                device_idx = sd.default.device[0]
            
            # Query device capabilities
            device_info = sd.query_devices(device_idx, 'input')
            if device_info is not None:
                # Use the device's supported sample rate
                supported_sample_rate = int(device_info['default_samplerate'])
            else:
                supported_sample_rate = 16000  # fallback
            
            # Record audio
            recording = sd.rec(
                int(duration * supported_sample_rate),
                samplerate=supported_sample_rate,
                channels=1,
                dtype=np.float32,
                device=device_idx,
                blocking=True  # Make sure recording is complete before continuing
            )
            
            if recording is None or len(recording) == 0:
                print("Error: No audio data recorded")
                return None, None
                
            return recording, supported_sample_rate
            
        except Exception as e:
            print(f"Error recording audio: {e}")
            return None, None

    def on_voice_input(self, widget):
        if not self.recording:
            try:
                # Check if audio system is available
                sd.check_output_settings()
                
                # Start recording
                self.recording = True
                self.btn_voice.set_label("Recording... Click to Stop")
                
                def record_thread():
                    try:
                        # Create a temporary file
                        temp_dir = Path(tempfile.gettempdir())
                        temp_file = temp_dir / "voice_input.wav"
                        
                        # Set a timeout for recording (e.g., 30 seconds)
                        recording = None
                        try:
                            recording, sample_rate = self.record_audio()
                        except Exception as e:
                            GLib.idle_add(self.append_message, 'ai', f"Recording failed: {str(e)}")
                            return
                        
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
                                        transcript = client.audio.transcriptions.create(
                                            model="whisper-1", 
                                            file=audio_file,
                                            timeout=20  # Add timeout for API call
                                        )
                                        
                                    # Add transcribed text to input
                                    GLib.idle_add(self.entry_question.set_text, transcript.text)
                                    
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
            try:
                sd.stop()
            except:
                pass
            self.recording = False
            self.btn_voice.set_label("Start Voice Input")

    def speak_text(self, text):
        """Convert text to speech using OpenAI's TTS."""
        try:
            # Create a temporary file for the speech
            temp_dir = Path(tempfile.gettempdir())
            temp_file = temp_dir / "ai_speech.mp3"
            
            # Generate speech
            response = client.audio.speech.create(
                model="tts-1",
                voice=self.tts_voice,
                input=text
            )
            
            # Save to file
            response.stream_to_file(temp_file)
            
            # Play the audio (you'll need to implement audio playback)
            # This is a placeholder - you might want to use a library like pygame or vlc
            os.system(f"xdg-open {temp_file}")  # Basic playback using system default
            
        except Exception as e:
            self.append_message('ai', f"Error generating speech: {str(e)}")

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
        global client
        api_key = self.entry_api.get_text().strip()
        if api_key:  # Only update if we have a key
            client = OpenAI(api_key=api_key)
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
            # Truncate message to first 40 characters and add ellipsis if needed
            display_text = history['first_message'][:40]
            if len(history['first_message']) > 40:
                display_text += "..."
            
            label = Gtk.Label(
                label=display_text,
                xalign=0,  # Left align
                margin=6
            )
            label.set_line_wrap(False)  # Prevent wrapping
            label.set_ellipsize(Pango.EllipsizeMode.END)  # Add ellipsis if text is too long
            row.add(label)
            
            # Store filename in row data
            row.filename = history['filename']
            
            self.history_list.add(row)
        
        self.history_list.show_all()

    def on_history_selected(self, listbox, row):
        """Handle selection of a chat history."""
        # Save current chat if it's new and has messages
        if self.current_chat_id is None and len(self.conversation_history) > 1:
            self.save_current_chat()
        
        # Load the selected chat history
        history = load_chat_history(row.filename)
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
        """Save the current chat if needed and refresh history list."""
        if len(self.conversation_history) > 1:  # More than just the system message
            # Add or update the model in the system message
            if len(self.conversation_history) > 0:
                self.conversation_history[0]["model"] = self.combo_model.get_active_text()
            
            if self.current_chat_id is None:
                # New chat - generate name and save
                chat_name = generate_chat_name(self.conversation_history[1]['content'])
                self.current_chat_id = chat_name
            else:
                # Existing chat - use current ID
                chat_name = self.current_chat_id
                
            save_chat_history(chat_name, self.conversation_history)
            self.refresh_history_list()

def rgb_to_hex(rgb_str):
    """Convert RGB string like 'rgb(216,222,233)' to hex color like '#D8DEE9'."""
    try:
        # Extract the RGB values
        r, g, b = map(int, rgb_str.strip('rgb()').split(','))
        # Convert to hex
        return f'#{r:02x}{g:02x}{b:02x}'
    except:
        return '#000000'  # Default to black if conversion fails

def process_inline_markup(text):
    """
    Process text for inline code. It splits the text on backticks,
    escapes non-code parts, and converts backticked parts to styled
    monospace with theme-appropriate highlighting.
    """
    import re
    
    # Create a temporary label to get theme colors
    label = Gtk.Label()
    context = label.get_style_context()
    context.add_class('selection')  # This should give us selection colors
    
    # Get computed values for the background and foreground
    bg_color = "#404040"  # Fallback dark gray
    fg_color = "#ffffff"  # Fallback white
    
    try:
        provider = Gtk.CssProvider()
        provider.load_from_data(b"""
            .selection:selected {
                background-color: @theme_selected_bg_color;
                color: @theme_selected_fg_color;
            }
        """)
        context.add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        bg_color = context.get_background_color(Gtk.StateFlags.SELECTED).to_string()
        fg_color = context.get_color(Gtk.StateFlags.SELECTED).to_string()
        bg_color = fix_rgb_colors_in_markup(bg_color)
        fg_color = fix_rgb_colors_in_markup(fg_color)
    except Exception:
        pass  # Use fallback colors if we can't get theme colors
    
    # Split the text on inline-code parts. The backticks are preserved.
    parts = re.split(r'(`[^`]+`)', text)
    processed_parts = []
    for part in parts:
        if part.startswith("`") and part.endswith("`"):
            # Strip the backticks and escape the code content
            code_content = part[1:-1]
            # Style with monospace font and theme colors
            processed_parts.append(
                f'<span font_family="monospace" background="{bg_color}" foreground="{fg_color}">' + 
                GLib.markup_escape_text(code_content) + 
                '</span>'
            )
        else:
            # Escape the non-code parts
            processed_parts.append(GLib.markup_escape_text(part))
    return "".join(processed_parts)

def fix_rgb_colors_in_markup(text: str) -> str:
    """
    Convert any occurrences of 'rgb(R, G, B)' in the string to '#RRGGBB'.
    This does not attempt to parse attribute names or validate usage,
    it just replaces the pattern wherever it appears.
    """
    if not text:
        return text

    # Regex to match rgb(...) anywhere in the string
    pattern = re.compile(r'rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)')

    def replacer(match):
        r = int(match.group(1))
        g = int(match.group(2))
        b = int(match.group(3))
        return f'#{r:02X}{g:02X}{b:02X}'  # uppercase hex

    return pattern.sub(replacer, text)

def main():
    win = OpenAIGTKClient()
    win.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()
