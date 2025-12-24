"""
Reusable markdown formatting toolbar for text views.
"""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk


class MarkdownActions:
    """Formatting actions that operate on a Gtk.TextView-like widget."""

    def __init__(self, textview: Gtk.TextView):
        self._textview = textview

    def wrap_selection(self, prefix: str, suffix: str) -> None:
        """Wrap the current selection with prefix/suffix or insert template."""
        buf = self._textview.get_buffer()
        if buf.get_has_selection():
            start, end = buf.get_selection_bounds()
            text = buf.get_text(start, end, True)

            if text.startswith(prefix) and text.endswith(suffix) and len(text) >= len(prefix) + len(suffix):
                new_text = text[len(prefix):len(text) - len(suffix)]
                buf.delete(start, end)
                buf.insert(start, new_text)
            else:
                buf.delete(start, end)
                buf.insert(start, f"{prefix}{text}{suffix}")
        else:
            buf.insert_at_cursor(f"{prefix}{suffix}")
            cursor = buf.get_iter_at_mark(buf.get_insert())
            cursor.backward_chars(len(suffix))
            buf.place_cursor(cursor)

        self._textview.grab_focus()

    def prefix_lines(self, prefix: str) -> None:
        """Add (or remove) prefix to start of selected lines or current line."""
        buf = self._textview.get_buffer()
        if buf.get_has_selection():
            start, end = buf.get_selection_bounds()
            start.set_line_offset(0)
            if not end.ends_line():
                end.forward_to_line_end()
        else:
            start = buf.get_iter_at_mark(buf.get_insert())
            start.set_line_offset(0)
            end = start.copy()
            end.forward_to_line_end()

        text = buf.get_text(start, end, True)
        lines = text.split('\n')
        is_single_line = len(lines) == 1
        relevant_lines = [l for l in lines if l] if not is_single_line else lines

        if relevant_lines:
            all_have_prefix = all(line.startswith(prefix) for line in relevant_lines)
        else:
            all_have_prefix = False

        new_lines = []
        for line in lines:
            if not line and not is_single_line:
                new_lines.append(line)
                continue

            if all_have_prefix and line.startswith(prefix):
                new_lines.append(line[len(prefix):])
            elif all_have_prefix:
                new_lines.append(line)
            else:
                new_lines.append(f"{prefix}{line}")

        result_text = '\n'.join(new_lines)
        buf.delete(start, end)
        buf.insert(start, result_text)
        self._textview.grab_focus()

    def make_numbered_list(self) -> None:
        """Convert selected lines to a numbered list (1. 2. 3...)"""
        buf = self._textview.get_buffer()
        if buf.get_has_selection():
            start, end = buf.get_selection_bounds()
            start.set_line_offset(0)
            if not end.ends_line():
                end.forward_to_line_end()
        else:
            start = buf.get_iter_at_mark(buf.get_insert())
            start.set_line_offset(0)
            end = start.copy()
            end.forward_to_line_end()

        text = buf.get_text(start, end, True)
        lines = text.split('\n')

        new_lines = []
        count = 1
        for line in lines:
            if not line and len(lines) > 1:
                new_lines.append(line)
                continue
            new_lines.append(f"{count}. {line}")
            count += 1

        result_text = '\n'.join(new_lines)
        buf.delete(start, end)
        buf.insert(start, result_text)
        self._textview.grab_focus()

    def insert_emoji(self) -> None:
        """Trigger GTK emoji chooser and insert selected emoji."""
        self._textview.emit("insert-emoji")


class MarkdownToolbar:
    """Toolbar widget providing markdown formatting actions."""

    def __init__(
        self,
        actions: MarkdownActions,
        on_help=None,
        show_help: bool = True,
        use_spacer: bool = True,
    ):
        self.actions = actions
        self._on_help = on_help
        self._show_help = bool(show_help)
        self._use_spacer = bool(use_spacer)
        self.widget = self._build_toolbar()

    def _build_toolbar(self) -> Gtk.Box:
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        toolbar.get_style_context().add_class("toolbar")

        btn_bold = Gtk.Button()
        btn_bold.set_tooltip_text("Bold (Ctrl+B)")
        btn_bold.add(Gtk.Image.new_from_icon_name("format-text-bold-symbolic", Gtk.IconSize.SMALL_TOOLBAR))
        btn_bold.connect("clicked", lambda w: self.actions.wrap_selection("**", "**"))
        toolbar.pack_start(btn_bold, False, False, 0)

        btn_italic = Gtk.Button()
        btn_italic.set_tooltip_text("Italic (Ctrl+I)")
        btn_italic.add(Gtk.Image.new_from_icon_name("format-text-italic-symbolic", Gtk.IconSize.SMALL_TOOLBAR))
        btn_italic.connect("clicked", lambda w: self.actions.wrap_selection("*", "*"))
        toolbar.pack_start(btn_italic, False, False, 0)

        btn_code = Gtk.Button()
        btn_code.set_tooltip_text("Inline Code (Ctrl+`)")
        btn_code.add(Gtk.Image.new_from_icon_name("applications-development-symbolic", Gtk.IconSize.SMALL_TOOLBAR))
        btn_code.connect("clicked", lambda w: self.actions.wrap_selection("`", "`"))
        toolbar.pack_start(btn_code, False, False, 0)

        sep1 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep1.set_margin_start(4)
        sep1.set_margin_end(4)
        toolbar.pack_start(sep1, False, False, 0)

        btn_h1 = Gtk.Button(label="H1")
        btn_h1.set_tooltip_text("Heading 1 (Ctrl+1)")
        btn_h1.connect("clicked", lambda w: self.actions.prefix_lines("# "))
        toolbar.pack_start(btn_h1, False, False, 0)

        btn_h2 = Gtk.Button(label="H2")
        btn_h2.set_tooltip_text("Heading 2 (Ctrl+2)")
        btn_h2.connect("clicked", lambda w: self.actions.prefix_lines("## "))
        toolbar.pack_start(btn_h2, False, False, 0)

        btn_h3 = Gtk.Button(label="H3")
        btn_h3.set_tooltip_text("Heading 3 (Ctrl+3)")
        btn_h3.connect("clicked", lambda w: self.actions.prefix_lines("### "))
        toolbar.pack_start(btn_h3, False, False, 0)

        sep2 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep2.set_margin_start(4)
        sep2.set_margin_end(4)
        toolbar.pack_start(sep2, False, False, 0)

        btn_ul = Gtk.Button()
        btn_ul.set_tooltip_text("Bullet List (Ctrl+Shift+8)")
        btn_ul.add(Gtk.Image.new_from_icon_name("view-list-bullet-symbolic", Gtk.IconSize.SMALL_TOOLBAR))
        btn_ul.connect("clicked", lambda w: self.actions.prefix_lines("- "))
        toolbar.pack_start(btn_ul, False, False, 0)

        btn_ol = Gtk.Button()
        btn_ol.set_tooltip_text("Numbered List (Ctrl+Shift+7)")
        btn_ol.add(Gtk.Image.new_from_icon_name("view-list-ordered-symbolic", Gtk.IconSize.SMALL_TOOLBAR))
        btn_ol.connect("clicked", lambda w: self.actions.make_numbered_list())
        toolbar.pack_start(btn_ol, False, False, 0)

        sep3 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep3.set_margin_start(4)
        sep3.set_margin_end(4)
        toolbar.pack_start(sep3, False, False, 0)

        btn_codeblock = Gtk.Button()
        btn_codeblock.set_tooltip_text("Code Block (Ctrl+Shift+C)")
        btn_codeblock.add(Gtk.Image.new_from_icon_name("text-x-script-symbolic", Gtk.IconSize.SMALL_TOOLBAR))
        btn_codeblock.connect("clicked", lambda w: self.actions.wrap_selection("```\n", "\n```"))
        toolbar.pack_start(btn_codeblock, False, False, 0)

        btn_quote = Gtk.Button()
        btn_quote.set_tooltip_text("Quote (Ctrl+Shift+.)")
        btn_quote.add(Gtk.Image.new_from_icon_name("format-indent-more-symbolic", Gtk.IconSize.SMALL_TOOLBAR))
        btn_quote.connect("clicked", lambda w: self.actions.prefix_lines("> "))
        toolbar.pack_start(btn_quote, False, False, 0)

        if self._use_spacer:
            spacer = Gtk.Box()
            spacer.set_hexpand(True)
            toolbar.pack_start(spacer, True, True, 0)

        btn_emoji = Gtk.Button()
        btn_emoji.set_tooltip_text("Insert Emoji (Ctrl+.)")
        btn_emoji.add(Gtk.Image.new_from_icon_name("face-smile-symbolic", Gtk.IconSize.SMALL_TOOLBAR))
        btn_emoji.connect("clicked", lambda w: self.actions.insert_emoji())
        toolbar.pack_start(btn_emoji, False, False, 0)

        if self._show_help:
            btn_help = Gtk.Button()
            btn_help.set_tooltip_text("Keyboard Shortcuts")
            btn_help.add(Gtk.Image.new_from_icon_name("help-about-symbolic", Gtk.IconSize.SMALL_TOOLBAR))
            if self._on_help:
                btn_help.connect("clicked", lambda w: self._on_help())
            toolbar.pack_start(btn_help, False, False, 0)

        return toolbar
