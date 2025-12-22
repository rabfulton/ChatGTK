"""
Input panel UI component.

This component manages the text entry, voice input, and file attachment controls.
"""

from typing import Optional, Callable

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib

from .base import UIComponent
from events import EventBus, EventType


class InputPanel(UIComponent):
    """
    Input panel component for user message entry.
    
    Features:
    - Text entry with clear icon
    - Prompt editor button
    - Send button
    - Voice input button with recording state
    - File attachment button
    - Event-driven recording state updates
    """
    
    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        on_submit: Optional[Callable[[str], None]] = None,
        on_voice_input: Optional[Callable[[], None]] = None,
        on_attach_file: Optional[Callable[[], None]] = None,
        on_open_prompt_editor: Optional[Callable[[], None]] = None,
        on_clear: Optional[Callable[[], None]] = None,
    ):
        """
        Initialize the input panel.
        
        Parameters
        ----------
        event_bus : Optional[EventBus]
            Event bus for communication.
        on_submit : Optional[Callable[[str], None]]
            Callback when user submits message.
        on_voice_input : Optional[Callable[[], None]]
            Callback for voice input button.
        on_attach_file : Optional[Callable[[], None]]
            Callback for attach file button.
        on_open_prompt_editor : Optional[Callable[[], None]]
            Callback for prompt editor button.
        on_clear : Optional[Callable[[], None]]
            Callback when input is cleared.
        """
        super().__init__(event_bus)
        
        self._on_submit = on_submit
        self._on_voice_input = on_voice_input
        self._on_attach_file = on_attach_file
        self._on_open_prompt_editor = on_open_prompt_editor
        self._on_clear = on_clear
        
        # State
        self.recording = False
        self.attached_file_path = None
        
        # Build UI
        self.widget = self._build_ui()
        
        # Subscribe to events
        self.subscribe(EventType.RECORDING_STARTED, self._on_recording_started)
        self.subscribe(EventType.RECORDING_STOPPED, self._on_recording_stopped)
    
    def _build_ui(self) -> Gtk.Box:
        """Build the input panel UI."""
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        
        # Main input row
        input_row = Gtk.Box(spacing=6)
        
        # Voice button (microphone icon)
        self.btn_voice = Gtk.Button()
        self.btn_voice.set_image(Gtk.Image.new_from_icon_name("audio-input-microphone-symbolic", Gtk.IconSize.BUTTON))
        self.btn_voice.set_always_show_image(True)
        self.btn_voice.set_tooltip_text("Start Voice Input")
        self.btn_voice.connect("clicked", self._on_voice_clicked)
        input_row.pack_start(self.btn_voice, False, False, 0)
        
        # Attach button (paperclip icon)
        self.btn_attach = Gtk.Button()
        self.btn_attach.set_image(Gtk.Image.new_from_icon_name("mail-attachment-symbolic", Gtk.IconSize.BUTTON))
        self.btn_attach.set_always_show_image(True)
        self.btn_attach.set_tooltip_text("Attach File")
        self.btn_attach.connect("clicked", self._on_attach_clicked)
        input_row.pack_start(self.btn_attach, False, False, 0)
        
        # Text entry
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Enter your question here...")
        self.entry.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "edit-clear-symbolic")
        self.entry.connect("icon-press", self._on_icon_press)
        self.entry.connect("activate", self._on_activate)
        input_row.pack_start(self.entry, True, True, 0)
        
        # Prompt editor button
        btn_edit = Gtk.Button()
        btn_edit.set_tooltip_text("Open prompt editor")
        edit_icon = Gtk.Image.new_from_icon_name("document-edit-symbolic", Gtk.IconSize.BUTTON)
        btn_edit.add(edit_icon)
        btn_edit.set_relief(Gtk.ReliefStyle.NONE)
        btn_edit.connect("clicked", self._on_edit_clicked)
        input_row.pack_start(btn_edit, False, False, 0)
        
        # Send button (send icon)
        self.btn_send = Gtk.Button()
        self.btn_send.set_image(Gtk.Image.new_from_icon_name("document-send-symbolic", Gtk.IconSize.BUTTON))
        self.btn_send.set_always_show_image(True)
        self.btn_send.set_tooltip_text("Send")
        self.btn_send.connect("clicked", self._on_send_clicked)
        input_row.pack_start(self.btn_send, False, False, 0)
        
        container.pack_start(input_row, False, False, 0)
        
        return container
    
    def apply_font_size(self, font_size: int):
        """Apply font size to the entry."""
        css = f"entry {{ font-size: {font_size}pt; }}"
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode())
        self.entry.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    
    def get_text(self) -> str:
        """Get the current input text."""
        return self.entry.get_text()
    
    def set_text(self, text: str):
        """Set the input text."""
        self.entry.set_text(text)
    
    def clear(self):
        """Clear the input."""
        self.entry.set_text("")
    
    def grab_focus(self):
        """Focus the input entry."""
        self.entry.grab_focus()
    
    def set_recording_state(self, recording: bool):
        """Update the recording state."""
        self.recording = recording
        if recording:
            self.btn_voice.set_image(Gtk.Image.new_from_icon_name("media-record-symbolic", Gtk.IconSize.BUTTON))
            self.btn_voice.set_tooltip_text("Recording... Click to Stop")
        else:
            self.btn_voice.set_image(Gtk.Image.new_from_icon_name("audio-input-microphone-symbolic", Gtk.IconSize.BUTTON))
            self.btn_voice.set_tooltip_text("Start Voice Input")
    
    def set_attachment_label(self, label: str):
        """Update the attach button tooltip."""
        self.btn_attach.set_tooltip_text(label)
    
    def _on_icon_press(self, entry, icon_pos, event):
        """Handle clear icon press."""
        if icon_pos == Gtk.EntryIconPosition.SECONDARY:
            self.clear()
            if self._on_clear:
                self._on_clear()
    
    def _on_activate(self, entry):
        """Handle Enter key press."""
        if self._on_submit:
            self._on_submit(self.get_text())
    
    def _on_send_clicked(self, button):
        """Handle send button click."""
        if self._on_submit:
            self._on_submit(self.get_text())
    
    def _on_edit_clicked(self, button):
        """Handle prompt editor button click."""
        if self._on_open_prompt_editor:
            self._on_open_prompt_editor()
    
    def _on_voice_clicked(self, button):
        """Handle voice button click."""
        if self._on_voice_input:
            self._on_voice_input()
    
    def _on_attach_clicked(self, button):
        """Handle attach button click."""
        if self._on_attach_file:
            self._on_attach_file()
    
    def _on_recording_started(self, event):
        """Handle RECORDING_STARTED event."""
        self.schedule_ui_update(lambda: self.set_recording_state(True))
    
    def _on_recording_stopped(self, event):
        """Handle RECORDING_STOPPED event."""
        self.schedule_ui_update(lambda: self.set_recording_state(False))
