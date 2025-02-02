#!/usr/bin/env python3
import gi
import re
import threading
import os  # Import os to read/write environment variables and settings
import sounddevice as sd  # For recording audio
import soundfile as sf    # For saving audio files
import numpy as np       # For audio processing
import tempfile         # For temporary files
from pathlib import Path # For path handling

from openai import OpenAI
client = OpenAI()

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
    # Lines starting with ### are section titles we want to remove ### and increase font size by 2
    # Pango markup uses size in 1000s of a point, so e.g. 14 pt = 14000.
    # We'll do (base_font_size + 2) * 1000. multiline so we handle lines.
    h3_size = (base_font_size + 2) * 1000

    # Pattern will match lines that start with ### (optionally trailing spaces) and capture the rest
    pattern = r'^###\s+(.*)$'
    replacement = fr"<span size='{h3_size}'><b>\1</b></span>"

    # Removing extraneous newline
    text = text.lstrip()
    return re.sub(pattern, replacement, text, flags=re.MULTILINE)

def format_response(text):
    # 1. Format code blocks
    text = format_code_blocks(text)
    # 2. Format bullet points
    text = format_bullet_points(text)
    # We do not convert asterisks or ### here because we need to handle code blocks separately.
    return text

def load_settings():
    """Load settings from the SETTINGS_FILE if it exists, returning a dict of key-value pairs."""
    settings = {
        'AI_NAME': 'Sheila',
        'FONT_FAMILY': 'Sans',
        'FONT_SIZE': '12',
        'USER_COLOR': '#0000FF',
        'AI_COLOR': '#008000',
        'DEFAULT_MODEL': 'gpt-4o-mini',  # user-specified default
        'WINDOW_WIDTH': '900',
        'WINDOW_HEIGHT': '750',
        # New setting for system message
        'SYSTEM_MESSAGE': 'You are a helpful assistant named Sheila.',
        # New setting for temperature (we'll call it TEMPERAMENT)
        'TEMPERAMENT': '0.7'
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    # Expect format KEY=VALUE
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip().upper()
                        value = value.strip()
                        if key in settings:
                            settings[key] = value
        except Exception as e:
            print("Error loading settings:", e)
    return settings

def save_settings(settings_dict):
    """Save the settings dictionary to the SETTINGS_FILE in a simple key=value format."""
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            f.write("# Application settings\n")
            for key, value in settings_dict.items():
                f.write(f"{key}={value}\n")
    except Exception as e:
        print("Error saving settings:", e)

class SettingsDialog(Gtk.Dialog):
    def __init__(self, parent, ai_name, font_family, font_size, user_color, ai_color, default_model, system_message, temperament):
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

        # Buttons
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("OK", Gtk.ResponseType.OK)

        self.show_all()

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
            'temperament': self.scale_temp.get_value()
        }

class OpenAIGTKClient(Gtk.Window):
    def __init__(self):
        super().__init__(title="Sheila GTK Client")

        # Load settings from file or use defaults
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
        # New: store temperament
        self.temperament = float(loaded['TEMPERAMENT'])
        # Start conversation history with the system prompt
        self.conversation_history = [
            {"role": "system", "content": self.system_message}
        ]
        # Remember the current geometry if not maximized
        self.current_geometry = (self.window_width, self.window_height)

        # Set the initial window size
        self.set_default_size(self.window_width, self.window_height)

        # Connect a configure-event to track resizing
        self.connect("configure-event", self.on_configure_event)
        # Connect destroy to handle saving geometry on exit
        self.connect("destroy", self.on_destroy)

        # Main container
        vbox_main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        vbox_main.set_margin_top(10)
        vbox_main.set_margin_bottom(10)
        vbox_main.set_margin_start(10)
        vbox_main.set_margin_end(10)
        self.add(vbox_main)

        # Top row: API Key, Model, Settings
        hbox_top = Gtk.Box(spacing=6)

        # API Key input
        lbl_api = Gtk.Label(label="API Key:")
        self.entry_api = Gtk.Entry()
        self.entry_api.set_visibility(False)  # Hide API key text

        # Check for API key in environment variable and pre-populate if exists.
        env_api_key = os.environ.get('OPENAI_KEY')
        if env_api_key:
            self.entry_api.set_text(env_api_key)

        hbox_top.pack_start(lbl_api, False, False, 0)
        hbox_top.pack_start(self.entry_api, True, True, 0)

        # Model selection drop-down
        lbl_model = Gtk.Label(label="Model:")
        self.combo_model = Gtk.ComboBoxText()

        hbox_top.pack_start(lbl_model, False, False, 0)
        hbox_top.pack_start(self.combo_model, True, True, 0)

        # Populate model list from OpenAI or fallback
        self.populate_model_list(env_api_key)

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
        self.entry_question.connect("activate", self.on_submit)  # Submit on Enter key
        btn_send = Gtk.Button(label="Send")
        btn_send.connect("clicked", self.on_submit)
        hbox_input.pack_start(self.entry_question, True, True, 0)
        hbox_input.pack_start(btn_send, False, False, 0)
        vbox_main.pack_start(hbox_input, False, False, 0)

        # Voice input button with recording state
        self.recording = False
        self.btn_voice = Gtk.Button(label="Start Voice Input")
        self.btn_voice.connect("clicked", self.on_voice_input)
        vbox_main.pack_start(self.btn_voice, False, False, 0)

    def on_destroy(self, widget):
        # Save the last known geometry to settings
        to_save = load_settings()
        width, height = self.current_geometry
        to_save['WINDOW_WIDTH'] = str(width)
        to_save['WINDOW_HEIGHT'] = str(height)
        to_save['SYSTEM_MESSAGE'] = self.system_message
        # Also save temperament
        to_save['TEMPERAMENT'] = str(self.temperament)
        save_settings(to_save)
        Gtk.main_quit()

    def on_configure_event(self, widget, event):
        # Called whenever window is resized or moved
        if not self.is_maximized():
            width, height = self.get_size()
            self.current_geometry = (width, height)
        return False

    def populate_model_list(self, env_api_key):
        """Retrieve models from OpenAI if possible, otherwise fallback to built-in. Then set the default model."""
        self.combo_model.remove_all()
        models_added = []
        try:
            if env_api_key:
                OpenAI.api_key = env_api_key
                model_list = client.models.list()
                for m in model_list.data:
                    model_id = m.id
                    if "gpt" in model_id:
                        self.combo_model.append_text(model_id)
                        models_added.append(model_id)
            else:
                # If no env var, fallback to manual
                fallback_models = ["gpt-3.5-turbo", "gpt-4o-mini"]
                for fm in fallback_models:
                    self.combo_model.append_text(fm)
                    models_added.append(fm)
        except Exception as e:
            print("Error retrieving models from API:", e)
            fallback_models = ["gpt-3.5-turbo", "gpt-4o-mini"]
            for fm in fallback_models:
                self.combo_model.append_text(fm)
                models_added.append(fm)

        # Attempt to set default model if it's in the list, else set to 0
        if self.default_model in models_added:
            idx = models_added.index(self.default_model)
            self.combo_model.set_active(idx)
        else:
            self.combo_model.append_text(self.default_model)
            models_added.append(self.default_model)
            self.combo_model.set_active(len(models_added) - 1)

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
            temperament=self.temperament
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

            # Re-populate model list so default can be enforced
            self.populate_model_list(os.environ.get('OPENAI_KEY'))

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

    def append_ai_message(self, text):
        """Add an AI message with possible code blocks using GtkSourceView for syntax highlighting."""
        # We split out code blocks by our markers (including optional language spec):
        segments = re.split(r'(--- Code Block Start \(.*?--- Code Block End ---)', text, flags=re.DOTALL)

        # First, show a label with the AI name.
        lbl_name = Gtk.Label()
        lbl_name.set_selectable(True)
        lbl_name.set_line_wrap(True)
        lbl_name.set_line_wrap_mode(Gtk.WrapMode.WORD)
        lbl_name.set_xalign(0)
        css_ai = f"label {{ color: {self.ai_color}; font-family: {self.font_family}; font-size: {self.font_size}pt; }}"
        self.apply_css(lbl_name, css_ai)
        lbl_name.set_text(f"{self.ai_name}:")
        self.conversation_box.pack_start(lbl_name, False, False, 0)

        for seg in segments:
            seg = seg.strip("\n")
            if seg.startswith('--- Code Block Start ('):
                # Example: --- Code Block Start (python) ---some code--- Code Block End ---
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

                # Create a GtkSourceView for syntax highlighting
                source_view = GtkSource.View.new()
                font_desc = Pango.FontDescription(f"Monospace {self.font_size}")
                source_view.override_font(font_desc)
                source_view.set_editable(False)
                source_view.set_wrap_mode(Gtk.WrapMode.NONE)

                # Attempt to load the language definition
                lang_manager = GtkSource.LanguageManager.get_default()
                if code_lang in lang_manager.get_language_ids():
                    lang = lang_manager.get_language(code_lang)
                else:
                    # fallback
                    lang = None

                scheme_manager = GtkSource.StyleSchemeManager.get_default()
                style_scheme = scheme_manager.get_scheme("solarized-dark")
                buffer = source_view.get_buffer()
                buffer.set_language(lang)
                buffer.set_highlight_syntax(True)
                buffer.set_style_scheme(style_scheme)
                buffer.set_text(code_content)

                # Make it a bit smaller so it doesn't expand too large.
                source_view.set_size_request(-1, 100)

                frame = Gtk.Frame()
                frame.add(source_view)

                self.conversation_box.pack_start(frame, False, False, 5)
            else:
                # Normal text from the AI
                if seg.strip():
                    # Escape Pango markup chars, then interpret **bold**
                    escaped = escape_for_pango_markup(seg)
                    escaped = convert_double_asterisks_to_bold(escaped)
                    # Convert lines starting with ### to bigger font
                    escaped = convert_h3_to_large(escaped, self.font_size)

                    lbl_ai_text = Gtk.Label()
                    lbl_ai_text.set_selectable(True)
                    lbl_ai_text.set_line_wrap(True)
                    lbl_ai_text.set_line_wrap_mode(Gtk.WrapMode.WORD)
                    lbl_ai_text.set_xalign(0)
                    # apply same AI style
                    self.apply_css(lbl_ai_text, css_ai)

                    # Use markup instead of set_text
                    lbl_ai_text.set_use_markup(True)
                    lbl_ai_text.set_markup(escaped)

                    self.conversation_box.pack_start(lbl_ai_text, False, False, 0)

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

    def call_openai_api(self, api_key, model):
        OpenAI.api_key = api_key
        try:
            # Use the entire conversation so far
            response = client.chat.completions.create(
                model=model,
                messages=self.conversation_history,
                temperature=float(self.temperament),
            )

            answer = response.choices[0].message.content
            # Append AI reply to the conversation history
            self.conversation_history.append({"role": "assistant", "content": answer})

            # Format the response with bullet points and code blocks
            answer = format_response(answer)
            # Update the UI
            GLib.idle_add(self.append_message, 'ai', answer)
        except Exception as e:
            GLib.idle_add(self.append_message, 'ai', f"** Error: {str(e)} **")

    def record_audio(self, duration=5, sample_rate=44100):
        """Record audio for specified duration."""
        recording = sd.rec(
            int(duration * sample_rate),
            samplerate=sample_rate,
            channels=1,
            dtype=np.int16
        )
        sd.wait()  # Wait until recording is finished
        return recording, sample_rate

    def on_voice_input(self, widget):
        if not self.recording:
            # Start recording
            self.recording = True
            self.btn_voice.set_label("Recording... Click to Stop")
            
            def record_thread():
                # Create a temporary file
                temp_dir = Path(tempfile.gettempdir())
                temp_file = temp_dir / "voice_input.wav"
                
                # Record audio
                recording, sample_rate = self.record_audio()
                
                # Save to temporary file
                sf.write(temp_file, recording, sample_rate)
                
                # Transcribe with Whisper
                try:
                    with open(temp_file, "rb") as audio_file:
                        transcript = client.audio.transcriptions.create(
                            model="whisper-1", 
                            file=audio_file
                        )
                        
                    # Add transcribed text to input
                    GLib.idle_add(self.entry_question.set_text, transcript.text)
                    
                except Exception as e:
                    GLib.idle_add(self.append_message, 'ai', f"Error transcribing audio: {str(e)}")
                
                # Reset button state
                GLib.idle_add(self.btn_voice.set_label, "Start Voice Input")
                self.recording = False
                
                # Clean up temp file
                temp_file.unlink(missing_ok=True)
            
            # Start recording in separate thread
            threading.Thread(target=record_thread, daemon=True).start()
        else:
            # Stop recording
            sd.stop()
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
                voice="alloy",  # Can be: alloy, echo, fable, onyx, nova, shimmer
                input=text
            )
            
            # Save to file
            response.stream_to_file(temp_file)
            
            # Play the audio (you'll need to implement audio playback)
            # This is a placeholder - you might want to use a library like pygame or vlc
            os.system(f"xdg-open {temp_file}")  # Basic playback using system default
            
        except Exception as e:
            self.append_message('ai', f"Error generating speech: {str(e)}")

def main():
    win = OpenAIGTKClient()
    win.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()
