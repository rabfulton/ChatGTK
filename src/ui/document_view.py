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
from .markdown_toolbar import MarkdownActions, MarkdownToolbar
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
        on_insert_image: Optional[Callable[[], None]] = None,
        font_family: str = "Monospace",
        font_size: int = 12,
        preview_text_color: str = "#000000",
        source_theme: str = "solarized-dark",
        message_renderer: Optional[Any] = None,
        get_shortcuts: Optional[Callable[[], Dict[str, str]]] = None,
    ):
        self._event_bus = event_bus
        self._on_content_changed = on_content_changed
        self._on_undo = on_undo
        self._on_redo = on_redo
        self._on_export = on_export
        self._on_copy = on_copy
        self._preview_toggled_callback = on_preview_toggled
        self._on_insert_image = on_insert_image
        self._font_family = font_family
        self._font_size = font_size
        self._preview_text_color = preview_text_color
        self._source_theme = source_theme
        self._message_renderer = message_renderer
        self._get_shortcuts = get_shortcuts
        
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
        self._text_view.connect("key-press-event", self._on_key_press)
        self._text_view.connect("button-press-event", self._on_button_press)
        
        self._apply_font_style()
        
        self._buffer = GtkSource.Buffer()
        lang_manager = GtkSource.LanguageManager.get_default()
        markdown_lang = lang_manager.get_language('markdown')
        if markdown_lang:
            self._buffer.set_language(markdown_lang)
        self._text_view.set_buffer(self._buffer)
        self._buffer.connect('changed', self._on_buffer_changed)
        self._markdown_actions = MarkdownActions(self._text_view)
        
        edit_scrolled.add(self._text_view)
        self._mode_stack.add_named(edit_scrolled, "edit")
        
        # Preview view (rendered content)
        preview_scrolled = Gtk.ScrolledWindow()
        preview_scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        preview_scrolled.set_vexpand(True)
        preview_scrolled.set_hexpand(True)

        self._preview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._preview_box.set_margin_start(0)
        self._preview_box.set_margin_end(5)
        self._preview_box.set_margin_top(0)
        self._preview_box.set_margin_bottom(5)
        preview_scrolled.add(self._preview_box)
        self._mode_stack.add_named(preview_scrolled, "preview")
        
        # Toolbar (built after text view so actions can bind to it)
        toolbar = self._build_toolbar()
        container.pack_start(toolbar, False, False, 0)
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

        # Editing tools centered in the toolbar
        self._markdown_toolbar = MarkdownToolbar(
            self._markdown_actions,
            show_help=False,
            use_spacer=False,
        )
        self._markdown_toolbar.widget.set_hexpand(True)
        self._markdown_toolbar.widget.set_halign(Gtk.Align.CENTER)
        header_box.pack_start(self._markdown_toolbar.widget, True, True, 0)

        # Right-side controls
        right_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header_box.pack_start(right_box, False, False, 0)
        
        # Separator
        #header_box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 4)
        
        # Undo button
        self._undo_btn = Gtk.Button()
        self._undo_btn.set_image(Gtk.Image.new_from_icon_name("edit-undo-symbolic", Gtk.IconSize.SMALL_TOOLBAR))
        self._undo_btn.set_tooltip_text("Undo (Ctrl+Z)")
        self._undo_btn.connect("clicked", lambda w: self._on_undo() if self._on_undo else None)
        right_box.pack_start(self._undo_btn, False, False, 0)
        
        # Redo button
        self._redo_btn = Gtk.Button()
        self._redo_btn.set_image(Gtk.Image.new_from_icon_name("edit-redo-symbolic", Gtk.IconSize.SMALL_TOOLBAR))
        self._redo_btn.set_tooltip_text("Redo (Ctrl+Shift+Z)")
        self._redo_btn.connect("clicked", lambda w: self._on_redo() if self._on_redo else None)
        right_box.pack_start(self._redo_btn, False, False, 0)
        
        # Separator
        # header_box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 4)
        
        # Copy button
        copy_btn = Gtk.Button()
        copy_btn.set_image(Gtk.Image.new_from_icon_name("edit-copy-symbolic", Gtk.IconSize.SMALL_TOOLBAR))
        copy_btn.set_tooltip_text("Copy all")
        copy_btn.connect("clicked", lambda w: self._on_copy() if self._on_copy else None)
        right_box.pack_start(copy_btn, False, False, 0)
        
        # Export button
        export_btn = Gtk.Button()
        export_btn.set_image(Gtk.Image.new_from_icon_name("document-save-as-symbolic", Gtk.IconSize.SMALL_TOOLBAR))
        export_btn.set_tooltip_text("Export to PDF")
        export_btn.connect("clicked", lambda w: self._on_export() if self._on_export else None)
        right_box.pack_start(export_btn, False, False, 0)
        
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
        for child in self._preview_box.get_children():
            self._preview_box.remove(child)

        try:
            from markup_utils import format_response
        except ImportError as e:
            label = Gtk.Label(label=f"Preview unavailable: {e}")
            label.set_xalign(0)
            self._preview_box.pack_start(label, False, False, 0)
            self._preview_box.show_all()
            return

        content = self._current_content
        if not content.strip():
            label = Gtk.Label(label="(empty document)")
            label.set_xalign(0)
            self._preview_box.pack_start(label, False, False, 0)
            self._preview_box.show_all()
            return

        if not self._message_renderer:
            label = Gtk.Label(label="Preview renderer unavailable.")
            label.set_xalign(0)
            self._preview_box.pack_start(label, False, False, 0)
            self._preview_box.show_all()
            return

        processed = format_response(content)
        content_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        css_container = """
            box {
                background-color: @theme_base_color;
                padding: 12px;
                border-radius: 12px;
            }
        """
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(css_container.encode())
        content_container.get_style_context().add_provider(
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self._preview_box.pack_start(content_container, False, False, 0)
        self._message_renderer.render_rich_content(
            content_container,
            processed,
            self._preview_text_color,
        )
        self._preview_box.show_all()
    
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

    def _on_key_press(self, widget, event) -> bool:
        """Handle key presses for document editor behaviors."""
        if self._in_preview_mode:
            return False
        if self._maybe_continue_list(event):
            return True
        return self._handle_markdown_shortcuts(event)

    def _on_button_press(self, widget, event) -> bool:
        """Handle button press events for context menu."""
        # Right-click (button 3)
        if event.button == 3 and not self._in_preview_mode:
            self._show_context_menu(event)
            return True
        return False

    def _show_context_menu(self, event):
        """Show the document editor context menu."""
        menu = Gtk.Menu()
        
        # Insert Image item
        insert_image_item = Gtk.MenuItem(label="Insert Image...")
        insert_image_item.connect("activate", self._on_insert_image_activated)
        menu.append(insert_image_item)
        
        menu.append(Gtk.SeparatorMenuItem())
        
        # Standard edit items
        cut_item = Gtk.MenuItem(label="Cut")
        cut_item.connect("activate", lambda w: self._text_view.emit("cut-clipboard"))
        menu.append(cut_item)
        
        copy_item = Gtk.MenuItem(label="Copy")
        copy_item.connect("activate", lambda w: self._text_view.emit("copy-clipboard"))
        menu.append(copy_item)
        
        paste_item = Gtk.MenuItem(label="Paste")
        paste_item.connect("activate", lambda w: self._text_view.emit("paste-clipboard"))
        menu.append(paste_item)
        
        menu.show_all()
        menu.popup_at_pointer(event)

    def _on_insert_image_activated(self, menu_item):
        """Handle Insert Image menu item activation."""
        if self._on_insert_image:
            self._on_insert_image()


    def _handle_markdown_shortcuts(self, event) -> bool:
        """Handle markdown formatting shortcuts."""
        if not self._get_shortcuts:
            return False

        shortcuts = self._get_shortcuts() or {}

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

        action_handlers = {
            'editor_bold': lambda: self._markdown_actions.wrap_selection("**", "**"),
            'editor_italic': lambda: self._markdown_actions.wrap_selection("*", "*"),
            'editor_code': lambda: self._markdown_actions.wrap_selection("`", "`"),
            'editor_h1': lambda: self._markdown_actions.prefix_lines("# "),
            'editor_h2': lambda: self._markdown_actions.prefix_lines("## "),
            'editor_h3': lambda: self._markdown_actions.prefix_lines("### "),
            'editor_bullet_list': lambda: self._markdown_actions.prefix_lines("- "),
            'editor_numbered_list': self._markdown_actions.make_numbered_list,
            'editor_code_block': lambda: self._markdown_actions.wrap_selection("```\n", "\n```"),
            'editor_quote': lambda: self._markdown_actions.prefix_lines("> "),
            'editor_emoji': self._markdown_actions.insert_emoji,
        }

        for action, shortcut in shortcuts.items():
            if shortcut and shortcut.lower() == current_combo.lower():
                handler = action_handlers.get(action)
                if handler:
                    handler()
                    return True

        return False

    def _maybe_continue_list(self, event) -> bool:
        """Insert the next list marker on Return when in a list line."""
        if event.keyval not in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            return False
        if event.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK):
            return False

        buf = self._text_view.get_buffer()
        if buf.get_has_selection():
            return False

        insert_iter = buf.get_iter_at_mark(buf.get_insert())
        line_start = insert_iter.copy()
        line_start.set_line_offset(0)
        line_end = insert_iter.copy()
        line_end.forward_to_line_end()
        line_text = buf.get_text(line_start, line_end, True)

        bullet_match = re.match(r'^(\s*)([-*+])\s+', line_text)
        number_match = re.match(r'^(\s*)(\d+)([.)])\s+', line_text)
        prefix = None

        if bullet_match:
            indent, bullet = bullet_match.groups()
            prefix = f"{indent}{bullet} "
        elif number_match:
            indent, number, delimiter = number_match.groups()
            prefix = f"{indent}{int(number) + 1}{delimiter} "

        if not prefix:
            return False

        if line_text[len(prefix):].strip() == "":
            buf.delete(line_start, line_end)
            buf.place_cursor(line_start)
            return True

        buf.insert_at_cursor(f"\n{prefix}")
        return True
    
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
        base_width = anchor.get_allocated_width() or self._text_view.get_allocated_width()
        popover_width = int(base_width * 0.7) if base_width else 420

        popover = Gtk.Popover()
        popover.set_relative_to(anchor)
        popover.set_position(Gtk.PositionType.TOP)
        popover.set_size_request(popover_width, -1)
        
        event_box = Gtk.EventBox()
        event_box.connect("button-press-event", lambda w, e: popover.popdown())
        
        label = Gtk.Label(label=f"✓ {summary}")
        label.set_line_wrap(True)
        label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        label.set_xalign(0.0)
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

    def insert_text_at_cursor(self, text: str) -> None:
        """Insert text at the current cursor position."""
        self._buffer.insert_at_cursor(text)
    
    def cleanup(self) -> None:
        """Clean up event subscriptions."""
        if self._event_bus:
            self._event_bus.unsubscribe(EventType.DOCUMENT_UPDATED, self._on_document_updated)
            self._event_bus.unsubscribe(EventType.DOCUMENT_UNDO, self._on_document_undo_redo)
            self._event_bus.unsubscribe(EventType.DOCUMENT_REDO, self._on_document_undo_redo)
