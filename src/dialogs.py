"""
dialogs.py – GTK dialog classes extracted from ChatGTK.py.

This module contains:
- SettingsDialog: For configuring application settings.
- ToolsDialog: For configuring tool enablement (image, music).
- APIKeyDialog: For managing API keys for different providers.
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

from config import BASE_DIR
from utils import load_settings, apply_settings, parse_color_to_rgba


class SettingsDialog(Gtk.Dialog):
    """Dialog for configuring application settings."""
    
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

        # Preferred Image Model
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Image Model", xalign=0)
        label.set_hexpand(True)
        self.combo_image_model = Gtk.ComboBoxText()

        # Known image-capable models across providers. These are merged with any
        # image models discovered from the APIs at runtime.
        known_image_models = [
            # OpenAI
            "dall-e-3",
            "gpt-image-1",
            # Gemini
            "gemini-3-pro-image-preview",
            "gemini-2.5-flash-image",
            # Grok
            "grok-2-image-1212",
        ]

        # Start with the known list; any dynamically fetched models that look
        # like image models will be appended when the main window is created.
        for model_id in known_image_models:
            self.combo_image_model.append_text(model_id)

        # Select the current image model from settings, defaulting to dall-e-3.
        current_image_model = getattr(self, "image_model", "dall-e-3")
        # Find index of current_image_model, defaulting to first entry.
        active_index = 0
        for idx, model_id in enumerate(known_image_models):
            if model_id == current_image_model:
                active_index = idx
                break
        self.combo_image_model.set_active(active_index)

        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.combo_image_model, False, True, 0)
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
        settings_dict = load_settings()
        current_theme = settings_dict.get('SOURCE_THEME', 'solarized-dark')
        
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
            'tts_hd': self.switch_hd.get_active(),
            'image_model': self.combo_image_model.get_active_text() or 'dall-e-3',
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


class APIKeyDialog(Gtk.Dialog):
    """Dialog for managing API keys for different providers."""
    
    def __init__(self, parent, openai_key='', gemini_key='', grok_key=''):
        super().__init__(title="API Keys", transient_for=parent, flags=0)
        self.set_modal(True)
        self.set_default_size(500, 300)

        # Get the content area
        box = self.get_content_area()
        box.set_spacing(6)

        # Create list box
        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)

        # Style the list box
        list_box.set_margin_top(12)
        list_box.set_margin_bottom(12)
        list_box.set_margin_start(12)
        list_box.set_margin_end(12)

        # Add list box to content area
        box.pack_start(list_box, True, True, 0)

        # OpenAI API Key
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="OpenAI API Key", xalign=0)
        label.set_hexpand(True)
        self.entry_openai = Gtk.Entry()
        self.entry_openai.set_visibility(False)
        self.entry_openai.set_placeholder_text("sk-...")
        self.entry_openai.set_text(openai_key)
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.entry_openai, False, True, 0)
        list_box.add(row)

        # Gemini API Key
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Gemini API Key", xalign=0)
        label.set_hexpand(True)
        self.entry_gemini = Gtk.Entry()
        self.entry_gemini.set_visibility(False)
        self.entry_gemini.set_placeholder_text("AI...")
        self.entry_gemini.set_text(gemini_key)
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.entry_gemini, False, True, 0)
        list_box.add(row)

        # Grok API Key
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(hbox)
        label = Gtk.Label(label="Grok API Key", xalign=0)
        label.set_hexpand(True)
        self.entry_grok = Gtk.Entry()
        self.entry_grok.set_visibility(False)
        self.entry_grok.set_placeholder_text("gsk-...")
        self.entry_grok.set_text(grok_key)
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(self.entry_grok, False, True, 0)
        list_box.add(row)

        # Add buttons
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("OK", Gtk.ResponseType.OK)

        self.show_all()

    def get_keys(self):
        """Return the API keys from the dialog."""
        return {
            'openai': self.entry_openai.get_text().strip(),
            'gemini': self.entry_gemini.get_text().strip(),
            'grok': self.entry_grok.get_text().strip()
        }

