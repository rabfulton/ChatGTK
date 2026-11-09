"""Collapsible, selectable reasoning text for live and saved responses."""

from gi.repository import GLib, Gtk, Pango


class ReasoningPreview(Gtk.ScrolledWindow):
    """A bounded text preview that follows new text until the reader scrolls up."""

    def __init__(self, text="", max_lines=16):
        super().__init__()
        self._text = ""
        self._scroll_pending = False
        self._destroyed = False
        self._reveal_handler = None
        self.text_view = Gtk.TextView()
        self.text_view.set_editable(False)
        self.text_view.set_cursor_visible(False)
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.text_view.set_left_margin(8)
        self.text_view.set_right_margin(8)
        self.text_view.set_top_margin(6)
        self.text_view.set_bottom_margin(6)
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_propagate_natural_height(True)
        max_height = 260
        if max_lines is not None:
            metrics = self.text_view.get_pango_context().get_metrics(None, None)
            line_height = (
                metrics.get_ascent() + metrics.get_descent() + Pango.SCALE - 1
            ) // Pango.SCALE
            max_height = line_height * max_lines + 12
            self.set_min_content_height(max_height)
        self.set_max_content_height(max_height)
        self._preferred_max_height = max_height
        self._preferred_min_height = max(1, self.get_min_content_height())
        self.add(self.text_view)
        self.connect("destroy", self._on_destroy)
        self.set_text(text)

    def set_text(self, text):
        """Append new text without resetting selection or scroll position."""
        adjustment = self.get_vadjustment()
        follow = (
            adjustment.get_upper() - adjustment.get_page_size() - adjustment.get_value()
            < 24
        )
        buffer = self.text_view.get_buffer()
        if text.startswith(self._text):
            buffer.insert(buffer.get_end_iter(), text[len(self._text) :])
        else:
            buffer.set_text(text)
        self._text = text
        if follow and self.get_mapped():
            self.scroll_to_bottom()

    def scroll_to_bottom(self):
        """Follow the latest reasoning after GTK has laid out the new text."""
        if self._scroll_pending:
            return
        self._scroll_pending = True

        def scroll():
            self._scroll_pending = False
            if not self._destroyed:
                adjustment = self.get_vadjustment()
                adjustment.set_value(
                    adjustment.get_upper() - adjustment.get_page_size()
                )
            return False

        GLib.idle_add(scroll)

    def scroll_into_view(self):
        """Fit the expanded preview and reveal it after conversation layout."""
        target = self.get_parent()
        outer = target
        while outer is not None and not isinstance(outer, Gtk.ScrolledWindow):
            outer = outer.get_parent()
        if outer is None:
            return

        if self._reveal_handler is not None:
            widget, handler = self._reveal_handler
            widget.disconnect(handler)
            self._reveal_handler = None

        adjustment = outer.get_vadjustment()
        page_height = adjustment.get_page_size()
        if page_height > 0:
            header_height = max(
                72, target.get_allocated_height() - self.get_allocated_height()
            )
            max_height = min(
                self._preferred_max_height, max(1, int(page_height) - header_height)
            )
            self.set_min_content_height(1)
            self.set_max_content_height(max_height)
            self.set_min_content_height(min(self._preferred_min_height, max_height))

        def reveal():
            if self._destroyed or not self.get_mapped():
                return False
            content = outer.get_child()
            if isinstance(content, Gtk.Viewport):
                content = content.get_child()
            position = target.translate_coordinates(content, 0, 0)
            if position is not None:
                top = position[1]
                adjustment.clamp_page(top, top + target.get_allocated_height())
            return False

        def allocated(widget, allocation):
            if self._reveal_handler is not None:
                widget.disconnect(self._reveal_handler[1])
                self._reveal_handler = None
            GLib.idle_add(reveal)

        self._reveal_handler = (
            target,
            target.connect_after("size-allocate", allocated),
        )
        target.queue_resize()

    def _on_destroy(self, widget):
        self._destroyed = True
        if self._reveal_handler is not None:
            target, handler = self._reveal_handler
            target.disconnect(handler)
            self._reveal_handler = None


class ReasoningView(Gtk.Expander):
    """Show provider reasoning or summaries in a bounded scrollable view."""

    def __init__(self, text="", label="Reasoning"):
        super().__init__(label=label)
        self.set_expanded(False)
        self.preview = ReasoningPreview(text)
        self.text_view = self.preview.text_view
        self.preview.show_all()
        self.preview.set_no_show_all(True)
        self.preview.hide()
        self.add(self.preview)
        self.connect("notify::expanded", self._on_expanded)

    def _on_expanded(self, widget, param):
        self.preview.set_visible(self.get_expanded())
        if self.get_expanded():
            self.preview.scroll_into_view()

    def set_text(self, text):
        """Append new text without resetting selection or expansion state."""
        self.preview.set_text(text)
