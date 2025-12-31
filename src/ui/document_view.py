"""
Document view UI component for Document Mode.

This component provides a focused document editing interface with:
- Toggle between edit (raw markdown) and preview (rendered) modes
- Toolbar with undo/redo/export actions
- Summary popover for edit feedback
"""

from typing import Optional, Callable, Any, Dict
from urllib.parse import unquote
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
        self._preview_anchor_widgets = {}
        self._preview_anchor_aliases = {}
        self._preview_anchor_counts = {}
        
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
        self._edit_scrolled = edit_scrolled
        
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
        self._buffer.connect('notify::can-undo', lambda *_args: self._refresh_undo_redo_state())
        self._buffer.connect('notify::can-redo', lambda *_args: self._refresh_undo_redo_state())
        self._markdown_actions = MarkdownActions(self._text_view)
        
        edit_scrolled.add(self._text_view)
        self._mode_stack.add_named(edit_scrolled, "edit")
        
        # Preview view (rendered content)
        preview_scrolled = Gtk.ScrolledWindow()
        preview_scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        preview_scrolled.set_vexpand(True)
        preview_scrolled.set_hexpand(True)
        self._preview_scrolled = preview_scrolled

        self._preview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._preview_box.set_margin_start(0)
        self._preview_box.set_margin_end(5)
        self._preview_box.set_margin_top(0)
        self._preview_box.set_margin_bottom(5)
        preview_scrolled.add(self._preview_box)
        self._mode_stack.add_named(preview_scrolled, "preview")
        
        # Toolbar + find bar (built after text view so actions can bind to it)
        toolbar = self._build_toolbar()
        find_bar = self._build_find_bar()
        container.pack_start(toolbar, False, False, 0)
        container.pack_start(find_bar, False, False, 0)
        container.pack_start(self._mode_stack, True, True, 0)

        self._refresh_undo_redo_state()
        
        return container

    def _build_find_bar(self) -> Gtk.Revealer:
        """Build the find/replace bar."""
        self._search_settings = GtkSource.SearchSettings()
        self._search_context = GtkSource.SearchContext.new(self._buffer, self._search_settings)

        self._find_revealer = Gtk.Revealer()
        self._find_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self._find_revealer.set_reveal_child(False)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_margin_start(6)
        box.set_margin_end(6)
        box.set_margin_top(4)
        box.set_margin_bottom(4)

        self._find_entry = Gtk.Entry()
        self._find_entry.set_placeholder_text("Find")
        self._find_entry.set_hexpand(True)
        self._find_entry.connect("key-press-event", self._on_find_entry_key_press)
        self._find_entry.connect("activate", self._on_find_next_activated)
        self._find_entry.connect("changed", self._on_find_text_changed)
        box.pack_start(self._find_entry, True, True, 0)

        self._replace_entry = Gtk.Entry()
        self._replace_entry.set_placeholder_text("Replace")
        self._replace_entry.set_hexpand(True)
        box.pack_start(self._replace_entry, True, True, 0)

        prev_btn = Gtk.Button.new_from_icon_name("go-up-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        prev_btn.set_tooltip_text("Find previous")
        prev_btn.connect("clicked", lambda _w: self._find_previous())
        box.pack_start(prev_btn, False, False, 0)

        next_btn = Gtk.Button.new_from_icon_name("go-down-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        next_btn.set_tooltip_text("Find next")
        next_btn.connect("clicked", lambda _w: self._find_next())
        box.pack_start(next_btn, False, False, 0)

        replace_btn = Gtk.Button(label="Replace")
        replace_btn.set_tooltip_text("Replace selection")
        replace_btn.connect("clicked", lambda _w: self._replace_one())
        box.pack_start(replace_btn, False, False, 0)

        replace_all_btn = Gtk.Button(label="Replace all")
        replace_all_btn.set_tooltip_text("Replace all matches")
        replace_all_btn.connect("clicked", lambda _w: self._replace_all())
        box.pack_start(replace_all_btn, False, False, 0)

        close_btn = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        close_btn.set_tooltip_text("Close find")
        close_btn.connect("clicked", lambda _w: self._toggle_find_bar(False))
        box.pack_start(close_btn, False, False, 0)

        self._find_revealer.add(box)
        return self._find_revealer
    
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
        GLib.idle_add(self._set_preview_toggle_width)

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
        self._undo_btn.connect("clicked", lambda w: self._undo())
        right_box.pack_start(self._undo_btn, False, False, 0)
        
        # Redo button
        self._redo_btn = Gtk.Button()
        self._redo_btn.set_image(Gtk.Image.new_from_icon_name("edit-redo-symbolic", Gtk.IconSize.SMALL_TOOLBAR))
        self._redo_btn.set_tooltip_text("Redo (Ctrl+Shift+Z / Ctrl+Y)")
        self._redo_btn.connect("clicked", lambda w: self._redo())
        right_box.pack_start(self._redo_btn, False, False, 0)
        
        # Separator
        # header_box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 4)
        
        # Copy button
        copy_btn = Gtk.Button()
        copy_btn.set_image(Gtk.Image.new_from_icon_name("edit-copy-symbolic", Gtk.IconSize.SMALL_TOOLBAR))
        copy_btn.set_tooltip_text("Copy all")
        copy_btn.connect("clicked", lambda w: self._on_copy() if self._on_copy else None)
        right_box.pack_start(copy_btn, False, False, 0)

        # Find button
        find_btn = Gtk.Button()
        find_btn.set_image(Gtk.Image.new_from_icon_name("system-search-symbolic", Gtk.IconSize.SMALL_TOOLBAR))
        find_btn.set_tooltip_text("Find / Replace (Ctrl+F)")
        find_btn.connect("clicked", lambda _w: self._toggle_find_bar())
        right_box.pack_start(find_btn, False, False, 0)
        
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

    def _set_preview_toggle_width(self) -> bool:
        """Lock the preview toggle width to the wider of its labels."""
        if not hasattr(self, "_preview_toggle") or not self._preview_toggle:
            return False
        current_label = self._preview_toggle.get_label() or "Preview"
        widths = []
        for label in ("Preview", "Edit"):
            self._preview_toggle.set_label(label)
            widths.append(self._preview_toggle.get_preferred_width()[1])
        self._preview_toggle.set_label(current_label)
        if widths:
            self._preview_toggle.set_size_request(max(widths), -1)
        return False
    
    def _on_preview_toggled(self, button: Gtk.ToggleButton) -> None:
        """Handle preview toggle."""
        if self._updating_preview_state:
            return
        self._in_preview_mode = button.get_active()
        self._preview_toggle.set_label("Edit" if self._in_preview_mode else "Preview")
        if self._in_preview_mode:
            self._pending_preview_scroll_percent = self._get_scroll_percent(self._edit_scrolled)
            # Save current content and render preview
            self._current_content = self.get_content()
            self._render_preview()
            self._mode_stack.set_visible_child_name("preview")
        else:
            self._cancel_preview_scroll_sync()
            self._mode_stack.set_visible_child_name("edit")
            self._text_view.grab_focus()
            preview_percent = self._get_scroll_percent(self._preview_scrolled)
            GLib.idle_add(self._apply_scroll_percent, self._edit_scrolled, preview_percent)
        if self._preview_toggled_callback:
            self._preview_toggled_callback(self._in_preview_mode)
    
    def _render_preview(self) -> None:
        """Render the document content as formatted output."""
        for child in self._preview_box.get_children():
            self._preview_box.remove(child)
        self._preview_anchor_widgets = {}
        self._preview_anchor_aliases = {}
        self._preview_anchor_counts = {}

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

        content = self._apply_document_line_breaks(content)
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
            raw_text=content,
            message_index=-1,
            on_update_message_text=self._on_preview_block_updated,
            link_handler=self._on_preview_link_clicked,
            on_block_rendered=self._register_preview_anchor,
        )
        self._preview_box.show_all()
        self._sync_preview_scroll()

    def _sync_preview_scroll(self) -> None:
        """Apply the pending edit scroll percent to the preview and resync after layout."""
        percent = getattr(self, "_pending_preview_scroll_percent", None)
        if percent is None:
            return
        self._apply_scroll_percent(self._preview_scrolled, percent)
        if not hasattr(self, "_preview_size_allocate_handler_id"):
            self._preview_size_allocate_handler_id = None
        if not self._preview_size_allocate_handler_id:
            self._preview_size_allocate_handler_id = self._preview_box.connect(
                "size-allocate", self._on_preview_size_allocate
            )
        if not hasattr(self, "_preview_scroll_sync_timeout"):
            self._preview_scroll_sync_timeout = None
        if not self._preview_scroll_sync_timeout:
            self._preview_scroll_sync_timeout = GLib.timeout_add(1500, self._cancel_preview_scroll_sync)

    def _on_preview_size_allocate(self, _widget, _allocation) -> None:
        """Re-apply preview scroll during layout changes (e.g., image load)."""
        percent = getattr(self, "_pending_preview_scroll_percent", None)
        if percent is None:
            return
        self._apply_scroll_percent(self._preview_scrolled, percent)

    def _cancel_preview_scroll_sync(self) -> bool:
        """Stop resyncing preview scroll after layout settles."""
        if hasattr(self, "_preview_size_allocate_handler_id") and self._preview_size_allocate_handler_id:
            self._preview_box.disconnect(self._preview_size_allocate_handler_id)
            self._preview_size_allocate_handler_id = None
        if hasattr(self, "_preview_scroll_sync_timeout") and self._preview_scroll_sync_timeout:
            GLib.source_remove(self._preview_scroll_sync_timeout)
            self._preview_scroll_sync_timeout = None
        self._pending_preview_scroll_percent = None
        return False

    def _get_scroll_percent(self, scrolled: Gtk.ScrolledWindow) -> float:
        """Return the current vertical scroll position as a percent."""
        if not scrolled:
            return 0.0
        adj = scrolled.get_vadjustment()
        upper = adj.get_upper()
        page_size = adj.get_page_size()
        denom = max(upper - page_size, 1.0)
        return max(0.0, min(1.0, (adj.get_value() - adj.get_lower()) / denom))

    def _apply_scroll_percent(self, scrolled: Gtk.ScrolledWindow, percent: float) -> bool:
        """Apply a vertical scroll percent to a scrolled window."""
        if not scrolled:
            return False
        adj = scrolled.get_vadjustment()
        upper = adj.get_upper()
        page_size = adj.get_page_size()
        lower = adj.get_lower()
        denom = max(upper - page_size, 1.0)
        value = lower + (percent * denom)
        adj.set_value(max(lower, min(value, upper - page_size)))
        return False

    def _on_preview_block_updated(self, _message_index: int, new_text: str) -> None:
        """Apply a preview block edit back into the document content."""
        self.set_content(new_text)
        if self._on_content_changed:
            self._on_content_changed(new_text)

    def _apply_document_line_breaks(self, content: str) -> str:
        """Convert <br> lines to blank lines outside code blocks."""
        if not content:
            return content
        lines = content.splitlines()
        output = []
        in_code_block = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code_block = not in_code_block
                output.append(line)
                continue
            if not in_code_block and re.match(r'^\s*<br\s*/?>\s*$', line, re.IGNORECASE):
                output.append("---DOC-PREVIEW-BR---")
                continue
            output.append(line)
        return "\n".join(output)

    def _register_preview_anchor(self, block_text: str, widget: Gtk.Widget) -> None:
        """Register a heading anchor for preview scrolling."""
        if not block_text:
            return
        for line_index, line in enumerate(block_text.splitlines()):
            line = line.strip()
            match = re.match(r'^\s{0,3}(#{1,6})\s+(.+)$', line)
            if not match:
                continue
            heading = match.group(2).strip()
            heading = re.sub(r'\s+#+\s*$', '', heading).strip()
            slug = self._slugify_heading(heading)
            if not slug:
                continue
            count = self._preview_anchor_counts.get(slug, 0)
            self._preview_anchor_counts[slug] = count + 1
            if count:
                slug = f"{slug}-{count}"
            if slug not in self._preview_anchor_widgets:
                self._preview_anchor_widgets[slug] = {
                    "widget": widget,
                    "line_index": line_index,
                }
            normalized = self._normalize_anchor_slug(slug)
            if normalized and normalized not in self._preview_anchor_aliases:
                self._preview_anchor_aliases[normalized] = slug

    def _slugify_heading(self, heading: str) -> str:
        """Convert a heading into a GitHub-style anchor slug."""
        heading = heading.strip().lower()
        heading = re.sub(r'[^\w\s-]', '', heading)
        heading = re.sub(r'\s+', '-', heading)
        heading = re.sub(r'-{2,}', '-', heading)
        return heading.strip('-')

    def _normalize_anchor_slug(self, slug: str) -> str:
        """Normalize a slug for loose matching (e.g., place-2 vs place2)."""
        slug = slug.strip().lower()
        return re.sub(r'[^a-z0-9]', '', slug)

    def _on_preview_link_clicked(self, url: str) -> bool:
        """Handle internal anchor links in preview mode."""
        if not url or not url.startswith("#"):
            return False
        anchor = unquote(url[1:]).strip().lower()
        if not anchor:
            return False
        if self._scroll_to_anchor(anchor):
            return True
        normalized = self._normalize_anchor_slug(anchor)
        mapped = self._preview_anchor_aliases.get(normalized)
        if mapped:
            return self._scroll_to_anchor(mapped)
        return False

    def _scroll_to_anchor(self, slug: str) -> bool:
        anchor = self._preview_anchor_widgets.get(slug)
        if not anchor:
            return False
        widget = anchor.get("widget")
        line_index = anchor.get("line_index")
        if not widget:
            return False
        if not self._preview_scrolled:
            return False
        def do_scroll():
            coords = widget.translate_coordinates(self._preview_box, 0, 0)
            if coords is None:
                base_y = widget.get_allocation().y
                parent = widget.get_parent()
                while parent and parent is not self._preview_box:
                    base_y += parent.get_allocation().y
                    parent = parent.get_parent()
            elif len(coords) == 2:
                _x, base_y = coords
            else:
                success, _x, base_y = coords
                if not success:
                    return False
            y = base_y
            if isinstance(widget, Gtk.TextView) and isinstance(line_index, int):
                buffer = widget.get_buffer()
                line_count = buffer.get_line_count()
                if line_count > 0:
                    target_line = min(line_index, line_count - 1)
                    iter_at_line = buffer.get_iter_at_line(target_line)
                    rect = widget.get_iter_location(iter_at_line)
                    _wx, wy = widget.buffer_to_window_coords(Gtk.TextWindowType.TEXT, rect.x, rect.y)
                    y = base_y + wy
            adj = self._preview_scrolled.get_vadjustment()
            target = max(adj.get_lower(), min(y, adj.get_upper() - adj.get_page_size()))
            adj.set_value(target)
            return False
        GLib.idle_add(do_scroll)
        return True
    
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
        self._refresh_undo_redo_state()

    def _undo(self) -> None:
        """Undo using GtkSourceView's buffer history."""
        if self._buffer.can_undo():
            self._buffer.undo()
            self._text_view.grab_focus()
        self._refresh_undo_redo_state()

    def _redo(self) -> None:
        """Redo using GtkSourceView's buffer history."""
        if self._buffer.can_redo():
            self._buffer.redo()
            self._text_view.grab_focus()
        self._refresh_undo_redo_state()

    def _on_key_press(self, widget, event) -> bool:
        """Handle key presses for document editor behaviors."""
        if self._in_preview_mode:
            return False
        if self._handle_undo_redo_shortcuts(event):
            return True
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

    def _handle_undo_redo_shortcuts(self, event) -> bool:
        """Handle undo/redo keyboard shortcuts."""
        if not (event.state & Gdk.ModifierType.CONTROL_MASK):
            return False
        key_name = Gdk.keyval_name(event.keyval)
        if not key_name:
            return False
        key_name = key_name.lower()
        if key_name == "z":
            if event.state & Gdk.ModifierType.SHIFT_MASK:
                self._redo()
            else:
                self._undo()
            return True
        if key_name == "y":
            self._redo()
            return True
        if key_name == "f" and not (event.state & Gdk.ModifierType.SHIFT_MASK):
            if hasattr(self, "_find_revealer") and self._find_revealer.get_reveal_child():
                self._toggle_find_bar(False)
                self._text_view.grab_focus()
            else:
                self._toggle_find_bar(True)
            return True
        return False

    def _toggle_find_bar(self, enabled: Optional[bool] = None) -> None:
        """Show or hide the find/replace bar."""
        if not hasattr(self, "_find_revealer") or not self._find_revealer:
            return
        current = self._find_revealer.get_reveal_child()
        target = (not current) if enabled is None else bool(enabled)
        self._find_revealer.set_reveal_child(target)
        if target:
            self._find_entry.grab_focus()
            if self._search_settings.get_search_text():
                self._find_from_iter(self._buffer.get_start_iter(), focus_editor=False)
        else:
            self._search_context.set_highlight(False)
            self._text_view.grab_focus()

    def _on_find_entry_key_press(self, _widget, event) -> bool:
        """Handle shortcuts when the find entry has focus."""
        if not (event.state & Gdk.ModifierType.CONTROL_MASK):
            return False
        key_name = Gdk.keyval_name(event.keyval)
        if not key_name:
            return False
        if key_name.lower() == "f":
            self._toggle_find_bar(False)
            return True
        return False

    def _on_find_text_changed(self, entry: Gtk.Entry) -> None:
        """Update search settings when the find text changes."""
        text = entry.get_text()
        self._search_settings.set_search_text(text)
        self._search_context.set_highlight(bool(text))
        if text:
            self._find_from_iter(self._buffer.get_start_iter(), focus_editor=False)

    def _on_find_next_activated(self, _entry: Gtk.Entry) -> None:
        """Jump to next match when pressing Enter in find entry."""
        self._find_next()

    def _get_search_start_iter(self, forward: bool = True):
        buf = self._buffer
        if buf.get_has_selection():
            sel_start, sel_end = buf.get_selection_bounds()
            return sel_end if forward else sel_start
        return buf.get_iter_at_mark(buf.get_insert())

    def _find_next(self) -> None:
        """Find the next match."""
        if not self._search_settings.get_search_text():
            return
        start = self._get_search_start_iter(True)
        self._find_from_iter(start, forward=True)

    def _find_previous(self) -> None:
        """Find the previous match."""
        if not self._search_settings.get_search_text():
            return
        start = self._get_search_start_iter(False)
        self._find_from_iter(start, forward=False)

    def _find_from_iter(self, start, forward: bool = True, focus_editor: bool = True) -> None:
        """Find a match from a starting iterator and select it."""
        if forward:
            match, match_start, match_end, _wrapped = self._search_context.forward(start)
        else:
            match, match_start, match_end, _wrapped = self._search_context.backward(start)
        if match:
            self._buffer.select_range(match_start, match_end)
            self._text_view.scroll_to_iter(match_start, 0.1, False, 0, 0)
            if focus_editor:
                self._text_view.grab_focus()

    def _replace_one(self) -> None:
        """Replace the current selection if it matches."""
        if not self._search_settings.get_search_text():
            return
        if not self._buffer.get_has_selection():
            self._find_next()
            return
        sel_start, sel_end = self._buffer.get_selection_bounds()
        replacement = self._replace_entry.get_text()
        if self._search_context.replace(sel_start, sel_end, replacement, len(replacement)):
            self._refresh_undo_redo_state()
            self._find_next()

    def _replace_all(self) -> None:
        """Replace all matches in the buffer."""
        if not self._search_settings.get_search_text():
            return
        replacement = self._replace_entry.get_text()
        self._search_context.replace_all(replacement, len(replacement))
        self._refresh_undo_redo_state()

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
        self._refresh_undo_redo_state()
    
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
            self._preview_toggle.set_label("Edit" if self._in_preview_mode else "Preview")
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

    def refresh_undo_redo_state(self) -> None:
        """Sync undo/redo button states from the GtkSource buffer."""
        self._refresh_undo_redo_state()

    def _refresh_undo_redo_state(self) -> None:
        """Internal helper to update undo/redo button sensitivity."""
        if not hasattr(self, "_buffer") or not self._buffer:
            return
        self._undo_btn.set_sensitive(self._buffer.can_undo())
        self._redo_btn.set_sensitive(self._buffer.can_redo())
    
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
