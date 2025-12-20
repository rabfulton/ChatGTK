"""
message_renderer.py – Message rendering for the GTK chat interface.

This module extracts the complex message rendering logic from ChatGTK.py
to improve code organization and testability.
"""

from dataclasses import dataclass
from typing import Callable, List, Optional, Any
import re
import getpass

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GtkSource', '4')
from gi.repository import Gtk, GtkSource, Gdk, GLib, Pango

from markup_utils import process_inline_markup, process_text_formatting
from latex_utils import process_tex_markup, insert_tex_image
from gtk_utils import insert_resized_image


@dataclass
class RenderSettings:
    """Styling settings for message rendering."""
    font_size: int
    font_family: str
    ai_color: str
    user_color: str
    ai_name: str
    source_theme: str
    latex_color: str
    latex_dpi: int


@dataclass  
class RenderCallbacks:
    """Callbacks for message rendering interactions."""
    on_context_menu: Callable[[Any, int, Any], None]  # (widget, index, event)
    on_delete: Callable[[Any, int], None]              # (widget, index)
    create_speech_button: Callable[[List[str]], Gtk.Widget]  # (text) -> button
    create_edit_button: Optional[Callable[[str, int], Gtk.Widget]] = None  # (image_path, msg_index) -> button


class MessageRenderer:
    """Handles rendering of chat messages to GTK widgets."""
    
    def __init__(
        self,
        settings: RenderSettings,
        callbacks: RenderCallbacks,
        conversation_box: Gtk.Box,
        message_widgets: List,
        window: Any,  # For GLib.idle_add and show_uri_on_window
        current_chat_id: str = None,
    ):
        self.settings = settings
        self.callbacks = callbacks
        self.conversation_box = conversation_box
        self.message_widgets = message_widgets
        self.window = window
        self.current_chat_id = current_chat_id

    def update_chat_id(self, chat_id: str):
        """Update the current chat ID for image paths."""
        self.current_chat_id = chat_id

    def _scroll_to_widget(self, widget: Gtk.Widget):
        """Scroll so the widget is at the top of the visible area."""
        def do_scroll():
            # Find the ScrolledWindow ancestor
            sw = self.conversation_box
            while sw and not isinstance(sw, Gtk.ScrolledWindow):
                sw = sw.get_parent()
            if not sw:
                return False
            
            adj = sw.get_vadjustment()
            # Get widget's position relative to conversation_box
            result = widget.translate_coordinates(self.conversation_box, 0, 0)
            if result:
                x, y = result
                # Only scroll if content exceeds visible area
                if adj.get_upper() > adj.get_page_size():
                    adj.set_value(y)
            return False
        
        # Wait for layout to complete
        GLib.timeout_add(50, do_scroll)

    def _apply_css_override(self, widget, css_string: str):
        """Apply CSS with APPLICATION priority to override existing styles."""
        style_provider = Gtk.CssProvider()
        style_provider.load_from_data(css_string.encode("utf-8"))
        Gtk.StyleContext.add_provider(
            widget.get_style_context(),
            style_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def update_existing_message_colors(self):
        """Update colors of existing messages to reflect current settings."""
        for widget in self.message_widgets:
            # User messages: EventBox containing a Label
            if isinstance(widget, Gtk.EventBox):
                child = widget.get_child()
                if isinstance(child, Gtk.Label):
                    # Update user message color
                    css = (
                        f"label {{ color: {self.settings.user_color}; "
                        f"font-family: {self.settings.font_family}; "
                        f"font-size: {self.settings.font_size}pt; "
                        f"background-color: @theme_base_color; border-radius: 12px; padding: 10px; }}"
                    )
                    self._apply_css_override(child, css)
            
            # AI messages: Box containing content_container
            elif isinstance(widget, Gtk.Box):
                # Find all labels and text views in the AI message
                def update_widget_colors(container):
                    """Recursively update colors in a container."""
                    if isinstance(container, Gtk.Label):
                        # Update all labels in AI messages to use AI color
                        # Check if it's the AI name label (needs background-color)
                        text = container.get_text() or ""
                        if text.startswith(f"{self.settings.ai_name}:"):
                            # AI name label
                            css = (
                                f"label {{ color: {self.settings.ai_color}; "
                                f"font-family: {self.settings.font_family}; "
                                f"font-size: {self.settings.font_size}pt; "
                                f"background-color: @theme_base_color;}}"
                            )
                        else:
                            # Other AI message labels (table cells, fallback labels, etc.)
                            css = (
                                f"label {{ color: {self.settings.ai_color}; "
                                f"font-family: {self.settings.font_family}; "
                                f"font-size: {self.settings.font_size}pt; }}"
                            )
                        self._apply_css_override(container, css)
                    elif isinstance(container, Gtk.TextView):
                        # Update text view color
                        css = f"""
                            textview {{
                                font-family: {self.settings.font_family};
                                font-size: {self.settings.font_size}pt;
                            }}
                            textview text {{
                                color: {self.settings.ai_color};
                            }}
                        """
                        css_provider = Gtk.CssProvider()
                        css_provider.load_from_data(css.encode())
                        container.get_style_context().add_provider(
                            css_provider,
                            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                        )
                    elif isinstance(container, Gtk.Separator):
                        # Update separator color
                        separator_css = f"""
                            separator {{
                                background-color: {self.settings.ai_color};
                                color: {self.settings.ai_color};
                                min-height: 2px;
                                margin-top: 8px;
                                margin-bottom: 8px;
                            }}
                        """
                        css_provider = Gtk.CssProvider()
                        css_provider.load_from_data(separator_css.encode())
                        container.get_style_context().add_provider(
                            css_provider, 
                            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                        )
                    elif isinstance(container, Gtk.Container):
                        # Recursively process children
                        for child in container.get_children():
                            update_widget_colors(child)
                
                update_widget_colors(widget)

    def append_message(self, sender: str, text: str, index: int):
        """Append a message to the conversation box."""
        if sender == 'user':
            self.append_user_message(text, index)
        else:
            self.append_ai_message(text, index)

    def append_user_message(self, text: str, message_index: int):
        """Add a user message as a styled box with markdown support."""
        # Wrap in EventBox to receive button events
        event_box = Gtk.EventBox()
        event_box.set_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        event_box.message_index = message_index

        # Create vertical box for content with similar styling to AI messages but simplified
        content_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        
        css = (
            f"box {{ color: {self.settings.user_color}; "
            f"font-family: {self.settings.font_family}; "
            f"font-size: {self.settings.font_size}pt; "
            f"background-color: @theme_base_color; border-radius: 12px; padding: 10px; }}"
        )
        self._apply_css_override(content_container, css)

        # Username label
        username = getpass.getuser()
        lbl_name = self._create_header_widget(username, is_user=True)
        
        content_container.pack_start(lbl_name, False, False, 0)
        
        # Render markdown content
        self._render_message_content(text, message_index, content_container, self.settings.user_color)

        event_box.add(content_container)

        def on_button_press(widget, event):
            if event.button == 3:  # Right click
                target_index = getattr(widget, "message_index", None)
                if target_index is None and widget.get_parent():
                    target_index = getattr(widget.get_parent(), "message_index", None)
                if target_index is not None:
                    self.callbacks.on_context_menu(widget, target_index, event)
                return True
            return False

        event_box.connect("button-press-event", on_button_press)
        
        self.conversation_box.pack_start(event_box, False, False, 0)
        self.message_widgets.append(event_box)
        self.conversation_box.show_all()
        
        self._scroll_to_widget(event_box)

    def append_ai_message(self, message_text: str, message_index: int):
        """Add an AI message with code blocks, tables, and images."""
        # Container for the entire AI response
        response_container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        response_container.set_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        response_container.message_index = message_index
        
        # Container for the text content
        content_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        
        # Style the container
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
        
        # AI name label (header box)
        header_box = self._create_header_widget(f"{self.settings.ai_name}", is_user=False)
        content_container.pack_start(header_box, False, False, 0)
        
        # Render markdown content
        full_text_segments = self._render_message_content(
            message_text, message_index, content_container, self.settings.ai_color
        )
                    
        # Create speech button and add to header
        speech_btn = self.callbacks.create_speech_button(full_text_segments)
        header_box.pack_end(speech_btn, False, False, 0)
        
        # Add edit button if message contains a generated image (not LaTeX math)
        if self.callbacks.create_edit_button:
            img_matches = re.findall(r'<img src="([^"]+)"/>', message_text)
            for img_path in img_matches:
                if not self._is_latex_math_image(img_path):
                    edit_btn = self.callbacks.create_edit_button(img_path, message_index)
                    header_box.pack_end(edit_btn, False, False, 0)
                    break  # Only add one edit button per message
        
        # Pack containers
        response_container.pack_start(content_container, True, True, 0)

        def on_response_button_press(widget, event):
            if event.button == 3:
                try:
                    source_widget = event.window.get_user_data()
                except Exception:
                    source_widget = None

                if isinstance(source_widget, Gtk.TextView):
                    return False
                self.callbacks.on_context_menu(widget, widget.message_index, event)
                return True
            return False

        response_container.connect("button-press-event", on_response_button_press)

        self.conversation_box.pack_start(response_container, False, False, 0)
        self.message_widgets.append(response_container)
        self.conversation_box.show_all()
        
        self._scroll_to_widget(response_container)

    def _attach_popup_to_text_view(self, text_view: Gtk.TextView, message_index: int):
        """Attach right-click popup menu to text view."""
        text_view.message_index = message_index

        def on_text_view_populate_popup(view, menu):
            if menu is None:
                return
            separator = Gtk.SeparatorMenuItem()
            delete_item = Gtk.MenuItem(label="Delete Message")
            delete_item.connect("activate", lambda w: self.callbacks.on_delete(w, view.message_index))
            menu.append(separator)
            menu.append(delete_item)
            menu.show_all()

        text_view.connect("populate-popup", on_text_view_populate_popup)

    def _render_message_content(self, message_text: str, message_index: int, 
                              container: Gtk.Box, text_color: str) -> List[str]:
        """Render message text into a container, supporting code blocks, tables, etc."""
        full_text = [] # To accumulate text for speech synthesis
        
        pattern = r'(--- Code Block Start \(.*?\) ---\n.*?\n--- Code Block End ---|--- Table Start ---\n.*?\n--- Table End ---|---HORIZONTAL-LINE---)'
        segments = re.split(pattern, message_text, flags=re.DOTALL)
        
        for seg in segments:
            if seg.startswith('--- Code Block Start ('):
                lang_match = re.search(r'^--- Code Block Start \((.*?)\) ---', seg)
                code_lang = lang_match.group(1) if lang_match else "plaintext"
                code_content = re.sub(r'^--- Code Block Start \(.*?\) ---', '', seg)
                code_content = re.sub(r'--- Code Block End ---$', '', code_content).strip('\n')
                source_view = create_source_view(
                    code_content, code_lang, 
                    self.settings.font_size, self.settings.source_theme
                )
                
                scrolled_sw = Gtk.ScrolledWindow()
                scrolled_sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
                scrolled_sw.set_propagate_natural_height(True)
                scrolled_sw.set_shadow_type(Gtk.ShadowType.NONE)
                scrolled_sw.add(source_view)
                
                frame = Gtk.Frame()
                frame.add(scrolled_sw)
                container.pack_start(frame, False, False, 5)
                full_text.append("Code block follows.")
                
            elif seg.startswith('--- Table Start ---'):
                table_content = re.sub(r'^--- Table Start ---\n?', '', seg)
                table_content = re.sub(r'\n?--- Table End ---$', '', table_content).strip()
                table_widget = self.create_table_widget(table_content)
                if table_widget:
                    container.pack_start(table_widget, False, False, 0)
                else:
                    fallback_label = Gtk.Label()
                    fallback_label.set_selectable(True)
                    fallback_label.set_line_wrap(True)
                    fallback_label.set_line_wrap_mode(Gtk.WrapMode.WORD)
                    fallback_label.set_xalign(0)
                    css = (
                        f"label {{ color: {text_color}; "
                        f"font-family: {self.settings.font_family}; "
                        f"font-size: {self.settings.font_size}pt; }}"
                    )
                    self._apply_css(fallback_label, css)
                    fallback_label.set_text(table_content)
                    container.pack_start(fallback_label, False, False, 0)
                full_text.append(table_content)
                
            elif seg.strip() == '---HORIZONTAL-LINE---':
                separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
                separator_css = f"""
                    separator {{
                        background-color: {text_color};
                        color: {text_color};
                        min-height: 2px;
                        margin-top: 8px;
                        margin-bottom: 8px;
                    }}
                """
                css_provider = Gtk.CssProvider()
                css_provider.load_from_data(separator_css.encode())
                separator.get_style_context().add_provider(
                    css_provider, 
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )
                container.pack_start(separator, False, False, 10)
                full_text.append("Horizontal line.")
                
            else:
                # Text segment
                if seg.startswith('\n'):
                    seg = seg[1:]
                if seg.endswith('\n'):
                    seg = seg[:-1]
                    
                if seg.strip():
                    processed = process_tex_markup(
                        seg, self.settings.latex_color, 
                        self.current_chat_id, self.settings.source_theme,
                        self.settings.latex_dpi
                    )
                    
                    if "<img" in processed:
                        text_view = self._create_text_view("", text_color)
                        self._attach_popup_to_text_view(text_view, message_index)
                        buffer = text_view.get_buffer()
                        parts = re.split(r'(<img src="[^"]+"/>)', processed)
                        for part in parts:
                            if part.startswith('<img src="'):
                                img_path = re.search(r'src="([^"]+)"', part).group(1)
                                insert_iter = buffer.get_end_iter()
                                if self._is_latex_math_image(img_path):
                                    insert_tex_image(buffer, insert_iter, img_path, text_view, self.window, is_math_image=True)
                                else:
                                    insert_resized_image(buffer, insert_iter, img_path, text_view, self.window)
                            else:
                                text = process_text_formatting(part, self.settings.font_size)
                                self._insert_markup_with_links(buffer, text, getattr(buffer, "link_rgba", None))
                        self._apply_bullet_hanging_indent(buffer)
                        container.pack_start(text_view, False, False, 0)
                    else:
                        processed = process_inline_markup(processed, self.settings.font_size)
                        text_view = self._create_text_view(processed, text_color)
                        self._attach_popup_to_text_view(text_view, message_index)
                        container.pack_start(text_view, False, False, 0)
                    full_text.append(seg)
        
        return full_text

    # -------------------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------------------

    def _create_header_widget(self, name: str, is_user: bool) -> Gtk.Box:
        """Create a styled header widget for message names."""
        container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        
        label = Gtk.Label()
        label.set_xalign(0.0)  # Center alignment
        label.set_markup(f"<b>{name}</b>")
        
        # Determine color based on role
        color = self.settings.user_color if is_user else self.settings.ai_color
        
        # Apply styling: font, size, color, and opacity
        css = (
            f"label {{ "
            f"  color: {color}; "
            f"  font-family: {self.settings.font_family}; "
            f"  font-size: {self.settings.font_size}pt; "
            f"  opacity: 0.7; "
            f"}}"
        )
        self._apply_css(label, css)
        
        # Pack label with True/True to let it take available space and center itself
        container.pack_start(label, True, True, 0)
        
        return container

    def _apply_css(self, widget, css_string: str):
        """Apply CSS to a widget."""
        style_provider = Gtk.CssProvider()
        style_provider.load_from_data(css_string.encode("utf-8"))
        Gtk.StyleContext.add_provider(
            widget.get_style_context(),
            style_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_USER
        )

    def _is_latex_math_image(self, path: str) -> bool:
        """Check if an image path is a LaTeX math rendering."""
        # LaTeX images are named math_inline_* or math_display_*
        return "math_inline_" in path or "math_display_" in path

    def _create_text_view(self, markup_text: str, text_color: str) -> Gtk.TextView:
        """Create a styled, read-only TextView with markup."""
        text_view = Gtk.TextView()
        text_view.set_wrap_mode(Gtk.WrapMode.WORD)
        text_view.set_editable(False)
        text_view.set_cursor_visible(False)
        text_view.set_can_focus(False)
        text_view.set_hexpand(True)
        text_view.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK)

        css = f"""
            textview {{
                font-family: {self.settings.font_family};
                font-size: {self.settings.font_size}pt;
            }}
            textview text {{
                color: {text_color};
            }}
        """
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(css.encode())
        text_view.get_style_context().add_provider(
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        buffer = text_view.get_buffer()
        link_rgba = self._get_link_color(text_view)
        if link_rgba:
            buffer.link_rgba = link_rgba
        if markup_text:
            # Fix any unclosed tags before inserting
            markup_text = self._fix_unclosed_tags(markup_text)
            self._insert_markup_with_links(buffer, markup_text, link_rgba)
            self._apply_bullet_hanging_indent(buffer)

        # Link click handling
        def on_button_press(view, event):
            if event.button == 1:
                window_type = view.get_window_type(event.window)
                if window_type is None:
                    return False

                x, y = view.window_to_buffer_coords(window_type, int(event.x), int(event.y))
                success, iter_at_click = view.get_iter_at_location(x, y)
                if not success or iter_at_click is None:
                    return False

                for tag in iter_at_click.get_tags():
                    url = getattr(tag, "href", None)
                    if url:
                        Gtk.show_uri_on_window(self.window, url, Gdk.CURRENT_TIME)
                        return True
            return False

        text_view.connect("button-press-event", on_button_press)
        
        # Size correction
        def on_size_allocate(view, allocation):
            if allocation.width > 0 and not hasattr(view, '_size_corrected'):
                view._size_corrected = True
                def recalculate_size():
                    if view.get_parent() and view.get_allocated_width() > 0:
                        view.queue_resize()
                    return False
                GLib.idle_add(recalculate_size)
        
        text_view.connect("size-allocate", on_size_allocate)
        return text_view

    def _get_link_color(self, widget: Gtk.Widget):
        """Return the theme-provided link color."""
        context = widget.get_style_context()
        link_rgba = context.get_color(Gtk.StateFlags.LINK)
        if link_rgba:
            return link_rgba
        found, resolved = context.lookup_color("link_color")
        if found:
            return resolved
        return None

    def _register_link_tag(self, tag: Gtk.TextTag, url: str):
        """Attach link metadata to a tag."""
        tag.href = url

    def _insert_markup_with_links(self, buffer: Gtk.TextBuffer, markup_text: str, link_rgba=None):
        """Insert markup with clickable links.

        Handles cases where links sit inside other markup (e.g., bold) by
        ensuring each inserted chunk is balanced. We temporarily close any
        open tags around the link, insert the link label with the same open
        tags reapplied, and then continue with the remaining content.
        """
        if link_rgba is None:
            link_rgba = getattr(buffer, "link_rgba", None)

        link_pattern = re.compile(r'<a href="([^"]+)">(.*?)</a>', re.DOTALL)
        tag_pattern = re.compile(r'<(/?)(\w+)([^>]*)>')

        def _reopen_tags(stack):
            parts = []
            for name, attrs in stack:
                attrs = attrs.strip()
                parts.append(f"<{name}{(' ' + attrs) if attrs else ''}>")
            return "".join(parts)

        def _close_tags(stack):
            return "".join(f"</{name}>" for name, _ in reversed(stack))

        def _update_stack(text, stack):
            """Return a copy of stack after applying tags found in text."""
            new_stack = stack.copy()
            for m in tag_pattern.finditer(text):
                is_close = m.group(1) == '/'
                tag_name = m.group(2)
                attrs = m.group(3)
                if tag_name == "a":
                    # Links are handled separately; ignore here to avoid confusion.
                    continue
                if is_close:
                    for i in range(len(new_stack) - 1, -1, -1):
                        if new_stack[i][0] == tag_name:
                            new_stack.pop(i)
                            break
                else:
                    new_stack.append((tag_name, attrs))
            return new_stack

        current_stack = []
        pos = 0

        for match in link_pattern.finditer(markup_text):
            before = markup_text[pos:match.start()]
            if before:
                new_stack = _update_stack(before, current_stack)
                balanced_before = _reopen_tags(current_stack) + before + _close_tags(new_stack)
                try:
                    buffer.insert_markup(buffer.get_end_iter(), balanced_before, -1)
                except Exception as e:
                    print(f"Markup error (before): {e}")
                    buffer.insert(buffer.get_end_iter(), self._strip_markup(before))
                current_stack = new_stack

            url = match.group(1)
            label_markup = match.group(2)

            start_offset = buffer.get_char_count()
            wrapped_label = _reopen_tags(current_stack) + label_markup + _close_tags(current_stack)
            try:
                buffer.insert_markup(buffer.get_end_iter(), wrapped_label, -1)
            except Exception as e:
                print(f"Markup error (link): {e}")
                buffer.insert(buffer.get_end_iter(), self._strip_markup(label_markup))
            end_offset = buffer.get_char_count()

            start_iter = buffer.get_iter_at_offset(start_offset)
            end_iter = buffer.get_iter_at_offset(end_offset)

            link_tag = buffer.create_tag(
                None,
                underline=Pango.Underline.SINGLE,
            )
            if link_rgba:
                link_tag.set_property("foreground_rgba", link_rgba)
            buffer.apply_tag(link_tag, start_iter, end_iter)
            self._register_link_tag(link_tag, url)

            pos = match.end()

        if pos < len(markup_text):
            tail = markup_text[pos:]
            new_stack = _update_stack(tail, current_stack)
            balanced_tail = _reopen_tags(current_stack) + tail + _close_tags(new_stack)
            try:
                buffer.insert_markup(buffer.get_end_iter(), balanced_tail, -1)
            except Exception as e:
                print(f"Markup error (after): {e}")
                buffer.insert(buffer.get_end_iter(), self._strip_markup(tail))

    def _strip_markup(self, text: str) -> str:
        """Remove Pango markup tags from text, keeping only the content."""
        # Remove common Pango tags
        text = re.sub(r'</?(?:b|i|u|s|sub|sup|small|big|tt|span)[^>]*>', '', text)
        return text

    def _fix_unclosed_tags(self, markup: str) -> str:
        """Fix unclosed Pango markup tags by stripping markup if invalid."""
        # Simple approach: try to parse with a stack and strip if unbalanced
        tag_pattern = re.compile(r'<(/?)(\w+)([^>]*)>')
        stack = []
        
        for match in tag_pattern.finditer(markup):
            is_close = match.group(1) == '/'
            tag_name = match.group(2)
            
            if is_close:
                if stack and stack[-1] == tag_name:
                    stack.pop()
                else:
                    # Unbalanced - strip all markup
                    return self._strip_markup(markup)
            else:
                stack.append(tag_name)
        
        if stack:
            # Unclosed tags - strip all markup
            return self._strip_markup(markup)
        
        return markup

    def _apply_bullet_hanging_indent(self, buffer: Gtk.TextBuffer):
        """Apply hanging indent to bullet and numbered list lines, including continuations."""
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
        
        # Check if there are any list items
        if "•" not in text and not re.search(r'^\s*\d+\.', text, re.MULTILINE):
            return

        tag_table = buffer.get_tag_table()
        
        # Measure actual character width using Pango
        pango_ctx = self.conversation_box.get_pango_context()
        font_desc = Pango.FontDescription.from_string(f"{self.settings.font_family} {self.settings.font_size}")
        metrics = pango_ctx.get_metrics(font_desc, None)
        char_width = metrics.get_approximate_char_width() / Pango.SCALE
        
        offset = 0
        # Stack of (source_leading_spaces, prefix_width) for continuation tracking
        list_stack = []
        
        for line in text.splitlines(True):
            line_start = buffer.get_iter_at_offset(offset)
            line_end = buffer.get_iter_at_offset(offset + len(line.rstrip("\n")))
            stripped = line.lstrip()
            leading_spaces = len(line) - len(stripped)
            
            # Detect bullet or numbered line, capturing the prefix
            # Bullets may have zero-width space markers for nesting level
            bullet_match = re.match(r'^(\u200B*)(•\s+)', stripped)
            number_match = re.match(r'^(\d+\.\s+)', stripped)
            
            if bullet_match or number_match:
                if bullet_match:
                    level_markers = bullet_match.group(1)
                    nesting_level = len(level_markers)
                    prefix_text = bullet_match.group(2)
                else:
                    nesting_level = leading_spaces // 3  # numbered lists use 3 spaces per level
                    prefix_text = number_match.group(1)
                
                # Pop stack to find parent (strictly lower level)
                while list_stack and nesting_level <= list_stack[-1][0]:
                    list_stack.pop()
                
                prefix_width = int(len(prefix_text) * char_width)
                indent_per_level = int(char_width * 2)  # visual indent per nesting level
                
                # For top-level numbered lists, no margin/indent at all
                if number_match and nesting_level == 0 and not list_stack:
                    # Don't apply any tag - let it render naturally
                    list_stack.append((nesting_level, prefix_width))  # Still track for nested items
                    offset += len(line)
                    continue
                
                # For top-level bullets, just hanging indent
                if nesting_level == 0 and not list_stack:
                    left_margin = prefix_width
                    indent_val = -prefix_width
                else:
                    # Calculate margin based on nesting level
                    parent_margin = list_stack[-1][1] if list_stack else 0
                    left_margin = parent_margin + prefix_width + indent_per_level
                    indent_val = -prefix_width
                
                list_stack.append((nesting_level, left_margin))
                
                tag_name = f"list_item_{left_margin}_{indent_val}"
                tag = tag_table.lookup(tag_name)
                if tag is None:
                    tag = buffer.create_tag(tag_name, left_margin=left_margin, indent=indent_val)
                buffer.apply_tag(tag, line_start, line_end)
                
            elif list_stack and stripped:
                # Find which level this continuation belongs to
                while list_stack and leading_spaces <= list_stack[-1][0]:
                    list_stack.pop()
                
                if list_stack:
                    # Continuation uses same prefix_width as its parent bullet
                    prefix_width = list_stack[-1][1]
                    tag_name = f"list_cont_{prefix_width}"
                    tag = tag_table.lookup(tag_name)
                    if tag is None:
                        tag = buffer.create_tag(tag_name, left_margin=prefix_width)
                    buffer.apply_tag(tag, line_start, line_end)
                
            elif not stripped:
                # Empty line - keep stack
                pass
            else:
                # Non-indented line - clear stack
                list_stack.clear()
                
            offset += len(line)

    def create_table_widget(self, table_text: str) -> Optional[Gtk.Widget]:
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

    def _split_table_row(self, row: str) -> List[str]:
        """Split a markdown table row into cells."""
        row = row.strip()
        if row.startswith('|'):
            row = row[1:]
        if row.endswith('|'):
            row = row[:-1]
        return [cell.strip() for cell in row.split('|')]

    def _get_table_alignments(self, separator: str, num_cols: int) -> List[float]:
        """Parse column alignments from separator line."""
        cells = self._split_table_row(separator)
        alignments = []
        for cell in cells:
            cell = cell.strip()
            if cell.startswith(':') and cell.endswith(':'):
                alignments.append(0.5)  # center
            elif cell.endswith(':'):
                alignments.append(1.0)  # right
            else:
                alignments.append(0.0)  # left (default)
        while len(alignments) < num_cols:
            alignments.append(0.0)
        return alignments

    def _create_table_cell_widget(self, text: str, alignment: float, bold: bool = False) -> Gtk.Widget:
        """Create a widget for a table cell with LaTeX support."""
        # Process LaTeX first
        processed_text = process_tex_markup(
            text,
            self.settings.latex_color,
            self.current_chat_id,
            self.settings.source_theme,
            self.settings.latex_dpi
        )
        
        css = (
            f"label {{ color: {self.settings.ai_color}; "
            f"font-family: {self.settings.font_family}; "
            f"font-size: {self.settings.font_size}pt; }}"
        )
        
        # If there are LaTeX-rendered images, use a TextView
        if "<img" in processed_text:
            text_view = Gtk.TextView()
            text_view.set_wrap_mode(Gtk.WrapMode.WORD)
            text_view.set_editable(False)
            text_view.set_cursor_visible(False)
            text_view.set_can_focus(False)
            text_view.set_hexpand(True)
            text_view.set_vexpand(False)
            text_view.set_halign(Gtk.Align.FILL)
            
            css_provider = Gtk.CssProvider()
            css_text = f"""
                textview {{
                    font-family: {self.settings.font_family};
                    font-size: {self.settings.font_size}pt;
                }}
                textview text {{
                    color: {self.settings.ai_color};
                }}
            """
            css_provider.load_from_data(css_text.encode())
            text_view.get_style_context().add_provider(
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
            
            buffer = text_view.get_buffer()
            link_rgba = self._get_link_color(text_view)
            if link_rgba:
                buffer.link_rgba = link_rgba
            
            text_view.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK)
            parts = re.split(r'(<img src="[^"]+"/>)', processed_text)
            for part in parts:
                if part.startswith('<img src="'):
                    img_path = re.search(r'src="([^"]+)"', part).group(1)
                    iter_ = buffer.get_end_iter()
                    if self._is_latex_math_image(img_path):
                        insert_tex_image(buffer, iter_, img_path, text_view, self.window, is_math_image=True)
                    else:
                        insert_resized_image(buffer, iter_, img_path, text_view, self.window)
                else:
                    markup = process_text_formatting(part, self.settings.font_size)
                    markup = self._fix_unclosed_tags(markup)
                    self._insert_markup_with_links(buffer, markup, link_rgba)
            
            return text_view
        
        # No images - use a simple label
        lbl = Gtk.Label()
        lbl.set_use_markup(True)
        lbl.set_line_wrap(True)
        lbl.set_line_wrap_mode(Gtk.WrapMode.WORD)
        lbl.set_xalign(alignment)
        self._apply_css(lbl, css)
        
        processed = process_inline_markup(processed_text, self.settings.font_size)
        processed = self._fix_unclosed_tags(processed)
        if bold and processed.strip():
            processed = f"<b>{processed}</b>"
        lbl.set_markup(processed or ' ')
        return lbl


def create_source_view(code_content: str, code_lang: str, font_size: int, source_theme: str = 'solarized-dark') -> GtkSource.View:
    """Create a styled source view for code display."""
    source_view = GtkSource.View.new()
    
    css_provider = Gtk.CssProvider()
    css = f"""
        textview {{
            font-family: monospace;
            font-size: {font_size}pt;
        }}
    """
    css_provider.load_from_data(css.encode())
    source_view.get_style_context().add_provider(
        css_provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    
    source_view.set_editable(False)
    source_view.set_cursor_visible(False)
    source_view.set_show_line_numbers(False)
    source_view.set_wrap_mode(Gtk.WrapMode.WORD)
    
    buffer = GtkSource.Buffer.new()
    
    # Set language
    lang_manager = GtkSource.LanguageManager.get_default()
    language = lang_manager.get_language(code_lang)
    if language:
        buffer.set_language(language)
    
    # Set theme
    style_manager = GtkSource.StyleSchemeManager.get_default()
    scheme = style_manager.get_scheme(source_theme)
    if scheme:
        buffer.set_style_scheme(scheme)
    
    buffer.set_text(code_content)
    source_view.set_buffer(buffer)
    
    return source_view
