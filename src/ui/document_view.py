"""
Document view UI component for Document Mode.

This component provides a focused document editing interface with:
- Toggle between edit (raw markdown) and preview (rendered) modes
- Toolbar with undo/redo/export actions
- Summary popover for edit feedback
"""

from typing import Optional, Callable, Any, Dict
import re

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GtkSource', '4')
from gi.repository import Gtk, GLib, Gdk, GtkSource, Pango

from .base import UIComponent
from events import EventBus, EventType, Event


class DocumentView(UIComponent):
    """
    Document editing view for Document Mode.
    
    Replaces the chat view when a document is open.
    """
    
    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        on_content_changed: Optional[Callable[[str], None]] = None,
        on_undo: Optional[Callable[[], None]] = None,
        on_redo: Optional[Callable[[], None]] = None,
        on_export: Optional[Callable[[], None]] = None,
        on_copy: Optional[Callable[[], None]] = None,
        on_preview_toggled: Optional[Callable[[bool], None]] = None,
        font_family: str = "Monospace",
        font_size: int = 12,
        preview_text_color: str = "#000000",
    ):
        self._event_bus = event_bus
        self._on_content_changed = on_content_changed
        self._on_undo = on_undo
        self._on_redo = on_redo
        self._on_export = on_export
        self._on_copy = on_copy
        self._preview_toggled_callback = on_preview_toggled
        self._font_family = font_family
        self._font_size = font_size
        self._preview_text_color = preview_text_color
        
        # Flag to prevent feedback loops during programmatic updates
        self._updating_programmatically = False
        self._updating_preview_state = False
        self._in_preview_mode = False
        self._current_content = ""
        
        # Build UI
        self._widget = self._build_ui()
        
        # Subscribe to events
        if self._event_bus:
            self._event_bus.subscribe(EventType.DOCUMENT_UPDATED, self._on_document_updated)
            self._event_bus.subscribe(EventType.DOCUMENT_UNDO, self._on_document_undo_redo)
            self._event_bus.subscribe(EventType.DOCUMENT_REDO, self._on_document_undo_redo)
    
    @property
    def widget(self) -> Gtk.Widget:
        return self._widget
    
    def _build_ui(self) -> Gtk.Box:
        """Build the document view UI."""
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        
        # Toolbar
        toolbar = self._build_toolbar()
        container.pack_start(toolbar, False, False, 0)
        
        # Stack for edit/preview modes
        self._mode_stack = Gtk.Stack()
        self._mode_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._mode_stack.set_transition_duration(100)
        
        # Edit view (GtkSource)
        edit_scrolled = Gtk.ScrolledWindow()
        edit_scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        edit_scrolled.set_vexpand(True)
        edit_scrolled.set_hexpand(True)
        
        self._text_view = GtkSource.View()
        self._text_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self._text_view.set_editable(True)
        self._text_view.set_cursor_visible(True)
        self._text_view.set_show_line_numbers(False)
        self._text_view.set_auto_indent(True)
        self._text_view.set_indent_on_tab(True)
        self._text_view.set_tab_width(4)
        self._text_view.set_insert_spaces_instead_of_tabs(True)
        self._text_view.set_left_margin(12)
        self._text_view.set_right_margin(12)
        self._text_view.set_top_margin(12)
        self._text_view.set_bottom_margin(12)
        
        self._apply_font_style()
        
        self._buffer = GtkSource.Buffer()
        lang_manager = GtkSource.LanguageManager.get_default()
        markdown_lang = lang_manager.get_language('markdown')
        if markdown_lang:
            self._buffer.set_language(markdown_lang)
        self._text_view.set_buffer(self._buffer)
        self._buffer.connect('changed', self._on_buffer_changed)
        
        edit_scrolled.add(self._text_view)
        self._mode_stack.add_named(edit_scrolled, "edit")
        
        # Preview view (rendered content) - match edit view structure
        preview_scrolled = Gtk.ScrolledWindow()
        preview_scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        preview_scrolled.set_vexpand(True)
        preview_scrolled.set_hexpand(True)
        
        # Use a TextView as container to match edit view behavior
        self._preview_text_view = Gtk.TextView()
        self._preview_text_view.set_editable(False)
        self._preview_text_view.set_cursor_visible(False)
        self._preview_text_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self._preview_text_view.set_left_margin(12)
        self._preview_text_view.set_right_margin(12)
        self._preview_text_view.set_top_margin(12)
        self._preview_text_view.set_bottom_margin(12)
        
        # Apply same font styling
        css = f"""
            textview {{
                font-family: {self._font_family};
                font-size: {self._font_size}pt;
                color: {self._preview_text_color};
            }}
            textview text {{
                padding: 12px;
                color: {self._preview_text_color};
            }}
        """
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(css.encode())
        self._preview_text_view.get_style_context().add_provider(
            css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        
        self._preview_buffer = self._preview_text_view.get_buffer()
        preview_scrolled.add(self._preview_text_view)
        self._mode_stack.add_named(preview_scrolled, "preview")
        
        container.pack_start(self._mode_stack, True, True, 0)
        
        return container
    
    def _build_toolbar(self) -> Gtk.Box:
        """Build the document toolbar."""
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        toolbar.set_margin_start(0)
        toolbar.set_margin_end(0)
        toolbar.set_margin_top(4)
        toolbar.set_margin_bottom(4)
        toolbar.set_hexpand(True)

        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header_box.set_hexpand(True)
        header_box.set_margin_start(0)
        header_box.set_margin_end(0)
        #self._apply_header_style(header_box)
        toolbar.pack_start(header_box, True, True, 0)
        
        # Edit/Preview toggle (compact button) on the left
        self._preview_toggle = Gtk.ToggleButton(label="Preview")
        self._preview_toggle.set_tooltip_text("Toggle Preview (Ctrl+P)")
        self._preview_toggle.connect("toggled", self._on_preview_toggled)
        header_box.pack_start(self._preview_toggle, False, False, 0)

        # Spacer pushes controls to the right
        header_box.pack_start(Gtk.Box(), True, True, 0)
        
        # Separator
        #header_box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 4)
        
        # Undo button
        self._undo_btn = Gtk.Button()
        self._undo_btn.set_image(Gtk.Image.new_from_icon_name("edit-undo-symbolic", Gtk.IconSize.SMALL_TOOLBAR))
        self._undo_btn.set_tooltip_text("Undo (Ctrl+Z)")
        self._undo_btn.connect("clicked", lambda w: self._on_undo() if self._on_undo else None)
        header_box.pack_start(self._undo_btn, False, False, 0)
        
        # Redo button
        self._redo_btn = Gtk.Button()
        self._redo_btn.set_image(Gtk.Image.new_from_icon_name("edit-redo-symbolic", Gtk.IconSize.SMALL_TOOLBAR))
        self._redo_btn.set_tooltip_text("Redo (Ctrl+Shift+Z)")
        self._redo_btn.connect("clicked", lambda w: self._on_redo() if self._on_redo else None)
        header_box.pack_start(self._redo_btn, False, False, 0)
        
        # Separator
        # header_box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 4)
        
        # Copy button
        copy_btn = Gtk.Button()
        copy_btn.set_image(Gtk.Image.new_from_icon_name("edit-copy-symbolic", Gtk.IconSize.SMALL_TOOLBAR))
        copy_btn.set_tooltip_text("Copy all")
        copy_btn.connect("clicked", lambda w: self._on_copy() if self._on_copy else None)
        header_box.pack_start(copy_btn, False, False, 0)
        
        # Export button
        export_btn = Gtk.Button()
        export_btn.set_image(Gtk.Image.new_from_icon_name("document-save-as-symbolic", Gtk.IconSize.SMALL_TOOLBAR))
        export_btn.set_tooltip_text("Export to PDF")
        export_btn.connect("clicked", lambda w: self._on_export() if self._on_export else None)
        header_box.pack_start(export_btn, False, False, 0)
        
        return toolbar

    def _apply_header_style(self, widget: Gtk.Widget) -> None:
        """Apply message-like styling to the document toolbar header."""
        css = """
            box {
                background-color: @theme_base_color;
                padding: 8px;
                border-radius: 0px;
            }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode())
        widget.get_style_context().add_provider(
            provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
    
    def _apply_font_style(self) -> None:
        """Apply font styling to the text view."""
        css = f"""
            textview {{
                font-family: {self._font_family};
                font-size: {self._font_size}pt;
            }}
            textview text {{
                padding: 12px;
            }}
        """
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(css.encode())
        self._text_view.get_style_context().add_provider(
            css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
    
    def _on_preview_toggled(self, button: Gtk.ToggleButton) -> None:
        """Handle preview toggle."""
        if self._updating_preview_state:
            return
        self._in_preview_mode = button.get_active()
        if self._in_preview_mode:
            # Save current content and render preview
            self._current_content = self.get_content()
            self._render_preview()
            self._mode_stack.set_visible_child_name("preview")
        else:
            self._mode_stack.set_visible_child_name("edit")
            self._text_view.grab_focus()
        if self._preview_toggled_callback:
            self._preview_toggled_callback(self._in_preview_mode)
    
    def _render_preview(self) -> None:
        """Render the document content as formatted output."""
        # Clear buffer
        self._preview_buffer.set_text("")
        
        # Import rendering utilities
        try:
            from latex_utils import process_tex_markup, insert_tex_image
            from markup_utils import process_text_formatting, process_inline_markup, format_response
        except ImportError as e:
            self._preview_buffer.set_text(f"Preview unavailable: {e}")
            return
        
        content = self._current_content
        if not content.strip():
            self._preview_buffer.set_text("(empty document)")
            return
        
        # Pre-process content
        processed = format_response(content)
        
        # Split into segments (code blocks, tables, text)
        pattern = r'(--- Code Block Start \(.*?\) ---\n.*?\n--- Code Block End ---|--- Table Start ---\n.*?\n--- Table End ---|---HORIZONTAL-LINE---)'
        segments = re.split(pattern, processed, flags=re.DOTALL)
        
        for seg in segments:
            if seg.startswith('--- Code Block Start ('):
                # Code block - insert as monospace text
                code_content = re.sub(r'^--- Code Block Start \(.*?\) ---', '', seg)
                code_content = re.sub(r'--- Code Block End ---$', '', code_content).strip('\n')
                end_iter = self._preview_buffer.get_end_iter()
                self._preview_buffer.insert(end_iter, code_content + "\n\n")
                
            elif seg.startswith('--- Table Start ---'):
                table_content = re.sub(r'^--- Table Start ---\n?', '', seg)
                table_content = re.sub(r'\n?--- Table End ---$', '', table_content).strip()
                end_iter = self._preview_buffer.get_end_iter()
                self._preview_buffer.insert(end_iter, table_content + "\n\n")
                
            elif seg.strip() == '---HORIZONTAL-LINE---':
                end_iter = self._preview_buffer.get_end_iter()
                self._preview_buffer.insert(end_iter, "─" * 40 + "\n\n")
                
            else:
                seg = seg.strip('\n')
                if seg.strip():
                    # Process LaTeX and formatting
                    processed_text = process_tex_markup(seg, "#888888", None, None, 150)
                    
                    if "<img" in processed_text:
                        # Has LaTeX images
                        parts = re.split(r'(<img src="[^"]+"/>)', processed_text)
                        for part in parts:
                            if part.startswith('<img src="'):
                                img_path = re.search(r'src="([^"]+)"', part).group(1)
                                end_iter = self._preview_buffer.get_end_iter()
                                insert_tex_image(self._preview_buffer, end_iter, img_path, self._preview_text_view, None, is_math_image=True)
                            else:
                                text = process_text_formatting(part, self._font_size)
                                self._insert_markup(self._preview_buffer, text)
                    else:
                        processed_text = process_inline_markup(processed_text, self._font_size)
                        self._insert_markup(self._preview_buffer, processed_text)
                    
                    end_iter = self._preview_buffer.get_end_iter()
                    self._preview_buffer.insert(end_iter, "\n")
    
    def _insert_markup(self, buffer: Gtk.TextBuffer, markup: str) -> None:
        """Insert pango markup into buffer."""
        try:
            end_iter = buffer.get_end_iter()
            buffer.insert_markup(end_iter, markup, -1)
        except Exception:
            # Fallback to plain text
            end_iter = buffer.get_end_iter()
            # Strip markup tags
            plain = re.sub(r'<[^>]+>', '', markup)
            buffer.insert(end_iter, plain)
    
    def _apply_css(self, widget: Gtk.Widget, css: str) -> None:
        """Apply CSS to a widget."""
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode())
        widget.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    
    def _on_buffer_changed(self, buffer: GtkSource.Buffer) -> None:
        """Handle buffer content changes."""
        if self._updating_programmatically:
            return
        if self._on_content_changed:
            content = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
            self._on_content_changed(content)
    
    def _on_document_updated(self, event: Event) -> None:
        """Handle document updated event - show summary popover."""
        summary = event.data.get('summary', '')
        if summary:
            GLib.idle_add(self._show_summary_popover, summary)
        # Refresh preview if in preview mode
        if self._in_preview_mode:
            self._current_content = self.get_content()
            GLib.idle_add(self._render_preview)
    
    def _on_document_undo_redo(self, event: Event) -> None:
        """Handle undo/redo events."""
        pass
    
    def set_popover_anchor(self, widget: Gtk.Widget) -> None:
        """Set the widget to anchor popovers to."""
        self._popover_anchor = widget
    
    def _show_summary_popover(self, summary: str) -> None:
        """Show a summary popover above the input bar."""
        anchor = getattr(self, '_popover_anchor', None) or self._text_view
        
        popover = Gtk.Popover()
        popover.set_relative_to(anchor)
        popover.set_position(Gtk.PositionType.TOP)
        
        event_box = Gtk.EventBox()
        event_box.connect("button-press-event", lambda w, e: popover.popdown())
        
        label = Gtk.Label(label=f"✓ {summary}")
        label.set_margin_start(12)
        label.set_margin_end(12)
        label.set_margin_top(8)
        label.set_margin_bottom(8)
        event_box.add(label)
        popover.add(event_box)
        
        popover.show_all()
    
    # Public methods
    
    def set_content(self, content: str) -> None:
        """Set the document content programmatically."""
        self._updating_programmatically = True
        try:
            self._buffer.set_text(content)
            self._current_content = content
            if self._in_preview_mode:
                self._render_preview()
        finally:
            self._updating_programmatically = False
    
    def get_content(self) -> str:
        """Get the current document content."""
        return self._buffer.get_text(
            self._buffer.get_start_iter(),
            self._buffer.get_end_iter(),
            True
        )

    def set_preview_mode(self, enabled: bool) -> None:
        """Set preview mode programmatically."""
        self._updating_preview_state = True
        try:
            enabled = bool(enabled)
            self._preview_toggle.set_active(enabled)
            self._in_preview_mode = enabled
            if self._in_preview_mode:
                self._current_content = self.get_content()
                self._render_preview()
                self._mode_stack.set_visible_child_name("preview")
            else:
                self._mode_stack.set_visible_child_name("edit")
        finally:
            self._updating_preview_state = False
    
    def set_title(self, title: str) -> None:
        """Retained for compatibility (no-op)."""
        return
    
    def set_undo_enabled(self, enabled: bool) -> None:
        """Enable/disable the undo button."""
        self._undo_btn.set_sensitive(enabled)
    
    def set_redo_enabled(self, enabled: bool) -> None:
        """Enable/disable the redo button."""
        self._redo_btn.set_sensitive(enabled)
    
    def focus_editor(self) -> None:
        """Focus the document editor."""
        self._text_view.grab_focus()

    def editor_has_focus(self) -> bool:
        """Return True when the document editor has keyboard focus."""
        return self._text_view.has_focus()

    def get_editor_view(self) -> GtkSource.View:
        """Expose the document editor view for integrations."""
        return self._text_view
    
    def cleanup(self) -> None:
        """Clean up event subscriptions."""
        if self._event_bus:
            self._event_bus.unsubscribe(EventType.DOCUMENT_UPDATED, self._on_document_updated)
            self._event_bus.unsubscribe(EventType.DOCUMENT_UNDO, self._on_document_undo_redo)
            self._event_bus.unsubscribe(EventType.DOCUMENT_REDO, self._on_document_undo_redo)
