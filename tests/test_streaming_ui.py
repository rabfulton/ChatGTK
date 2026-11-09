"""GTK smoke coverage; skipped when a display is unavailable."""

import sys
from pathlib import Path
from unittest.mock import Mock

import gi
import pytest

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from events import Event, EventType
from message_renderer import MessageRenderer, RenderCallbacks, RenderSettings
from ui.chat_view import ChatView
from ui.reasoning_view import ReasoningPreview, ReasoningView


@pytest.fixture(autouse=True)
def require_display():
    if not Gtk.init_check([])[0]:
        pytest.skip("GTK display unavailable")


def buffer_text(view):
    buffer = view.get_buffer()
    return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)


def test_reasoning_is_collapsed_selectable_and_keeps_expansion():
    view = ReasoningView("<b>Literal markup</b>")
    try:
        view.show_all()
        assert not view.get_expanded()
        assert not view.preview.get_visible()
        view.set_expanded(True)
        assert view.preview.get_visible()
        view.set_text("<b>Literal markup</b> 🙂")
        assert view.get_expanded()
        assert buffer_text(view.text_view) == "<b>Literal markup</b> 🙂"
        assert not view.text_view.get_editable()
        assert view.get_child().get_max_content_height() > 260
        view.set_expanded(False)
        view.show_all()
        assert not view.preview.get_visible()
    finally:
        view.destroy()


def test_stream_preview_updates_in_place_and_is_removed_on_finalization():
    view = ChatView(ai_name="Assistant & <model>")
    try:
        view._show_thinking_impl()
        event = Event(
            EventType.MESSAGE_STREAMING,
            {
                "reasoning": "Thought",
                "text": "",
                "is_current": lambda: True,
            },
        )
        view._stream_pending = event
        view._flush_stream()
        preview = view._stream_preview
        assert not view._stream_preview.get_visible()
        assert not view._thinking_toggle.get_active()
        view.conversation_box.show_all()
        assert not view._stream_preview.get_visible()
        view._thinking_toggle.clicked()
        assert view._stream_preview.get_visible()
        assert view._stream_preview.get_max_content_height() > 260
        event.data.update(text="Answer", reasoning="Thought continued")
        view._stream_pending = event
        view._flush_stream()
        assert view._stream_preview is preview
        assert buffer_text(preview.text_view) == (
            "Reasoning\n\nThought continued\n\nResponse preview\n\nAnswer"
        )
        assert view.conversation_box.get_children() == [view._thinking_container]
        assert view._stream_preview.get_visible()
        view._thinking_toggle.clicked()
        assert not view._stream_preview.get_visible()
        view._thinking_toggle.clicked()
        assert view.finish_stream() is True
        assert not view._stream_preview.get_visible()
        assert not view._thinking_toggle.get_active()
    finally:
        view.clear()
        view.widget.destroy()


def test_destroyed_chat_preview_can_be_recreated_without_stale_widgets():
    view = ChatView()
    try:
        event = Event(EventType.MESSAGE_STREAMING, {"text": "First"})
        view._stream_pending = event
        view._flush_stream()
        for child in view.conversation_box.get_children():
            child.destroy()
        assert view._stream_preview is None
        view._stream_pending = Event(EventType.MESSAGE_STREAMING, {"text": "Second"})
        view._flush_stream()
        assert (
            buffer_text(view._stream_preview.text_view) == "Response preview\n\nSecond"
        )
        assert not view._stream_preview.get_visible()
    finally:
        view.clear()
        view.widget.destroy()


def test_old_completion_cannot_remove_a_new_request_preview():
    view = ChatView()
    current = object()
    try:
        view._stream_pending = Event(
            EventType.MESSAGE_STREAMING,
            {
                "text": "New response",
                "request_id": current,
            },
        )
        view._flush_stream()
        view.finish_stream(object())
        assert (
            buffer_text(view._stream_preview.text_view)
            == "Response preview\n\nNew response"
        )
        view.finish_stream(current)
        assert buffer_text(view._stream_preview.text_view) == "Waiting for response…"
    finally:
        view.clear()
        view.widget.destroy()


def test_opening_before_reasoning_arrives_keeps_the_preview_open():
    view = ChatView()
    try:
        view._show_thinking_impl()
        view._thinking_toggle.clicked()
        assert view._stream_preview.get_visible()
        view._stream_pending = Event(
            EventType.MESSAGE_STREAMING,
            {
                "reasoning": "Now available",
                "text": "",
            },
        )
        view._flush_stream()
        assert view._thinking_toggle.get_active()
        assert view._stream_preview.get_visible()
        assert (
            buffer_text(view._stream_preview.text_view) == "Reasoning\n\nNow available"
        )
        assert view.conversation_box.get_children() == [view._thinking_container]
    finally:
        view.clear()
        view.widget.destroy()


def test_reasoning_preview_stops_following_when_reader_scrolls_up(monkeypatch):
    preview = ReasoningPreview(max_lines=8)
    try:
        monkeypatch.setattr(preview, "get_mapped", lambda: True)
        follow = Mock()
        monkeypatch.setattr(preview, "scroll_to_bottom", follow)
        adjustment = Gtk.Adjustment(
            value=100,
            lower=0,
            upper=1000,
            step_increment=10,
            page_increment=100,
            page_size=120,
        )
        monkeypatch.setattr(preview, "get_vadjustment", lambda: adjustment)
        preview.set_text("First chunk")
        follow.assert_not_called()
        assert adjustment.get_value() == 100
        adjustment.set_value(880)
        preview.set_text("First chunk and next chunk")
        follow.assert_called_once()
    finally:
        preview.destroy()


def test_response_without_reasoning_is_only_visible_inside_the_dropdown():
    view = ChatView()
    try:
        view._stream_pending = Event(
            EventType.MESSAGE_STREAMING,
            {
                "text": "# A heading\n\n**Streaming answer**",
                "reasoning": "",
            },
        )
        view._flush_stream()
        view.conversation_box.show_all()
        assert not view._stream_preview.get_visible()
        assert view.conversation_box.get_children() == [view._thinking_container]
        view._thinking_toggle.clicked()
        assert view._stream_preview.get_visible()
        assert buffer_text(view._stream_preview.text_view) == (
            "Response preview\n\n# A heading\n\n**Streaming answer**"
        )
        assert "when available" not in buffer_text(view._stream_preview.text_view)
        view._stream_pending = Event(
            EventType.MESSAGE_STREAMING, {"text": "", "reasoning": ""}
        )
        view._flush_stream()
        assert buffer_text(view._stream_preview.text_view) == "Waiting for response…"
        assert view._thinking_toggle.get_active()
    finally:
        view.clear()
        view.widget.destroy()


def test_thinking_text_is_unmapped_until_clicked_and_stays_bounded():
    view = ChatView()
    window = Gtk.Window()
    window.set_default_size(640, 700)
    window.add(view.widget)

    def layout():
        context = GLib.MainContext.default()
        while context.pending():
            context.iteration(False)

    try:
        view._show_thinking_impl()
        view._stream_pending = Event(
            EventType.MESSAGE_STREAMING,
            {
                "reasoning": "\n".join(
                    f"Thinking line {index}" for index in range(100)
                ),
            },
        )
        view._flush_stream()
        window.show_all()
        layout()
        assert not view._stream_preview.get_mapped()
        view._thinking_toggle.clicked()
        layout()
        assert view._stream_preview.get_mapped()
        assert view._stream_preview.get_allocated_height() <= (
            view._stream_preview.get_max_content_height()
        )
        adjustment = view._stream_preview.get_vadjustment()
        assert adjustment.get_upper() > adjustment.get_page_size()
        view._thinking_toggle.clicked()
        layout()
        assert not view._stream_preview.get_mapped()
    finally:
        view.clear()
        window.destroy()


def test_saved_reasoning_restores_without_becoming_answer_or_speech():
    container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    speech = Mock(return_value=Gtk.Button())
    callbacks = RenderCallbacks(
        on_context_menu=Mock(),
        on_delete=Mock(),
        create_speech_button=speech,
        get_message_metadata=lambda index: {
            "reasoning": {"text": "Saved reasoning"},
            "stream_status": "interrupted",
            "stream_error": "Connection lost",
        },
    )
    renderer = MessageRenderer(
        RenderSettings(
            12, "Sans", "#224466", "#446622", "Assistant", "classic", "#000000", 100
        ),
        callbacks,
        container,
        [],
        None,
    )
    renderer.set_scroll_suppressed(True)
    try:
        renderer.append_ai_message("Final answer", 1)
        widget = renderer.message_widgets[0]
        assert widget.reasoning_expander is not None
        assert buffer_text(widget.reasoning_expander.text_view) == "Saved reasoning"
        assert not widget.reasoning_expander.get_expanded()
        assert "Saved reasoning" not in str(speech.call_args)
        assert renderer._raw_message_text_by_index[1] == "Final answer"
    finally:
        container.destroy()


@pytest.mark.parametrize("height", [700, 260])
@pytest.mark.parametrize("kind", ["live", "saved"])
def test_opened_preview_scrolls_fully_into_conversation_view(height, kind):
    view = ChatView()
    window = Gtk.Window()
    window.set_default_size(640, height)
    window.add(view.widget)
    text = "\n".join(f"Preview line {index}" for index in range(100))

    def layout():
        # Resizing is driven by the next GTK frame, beyond pending idle work.
        loop = GLib.MainLoop()
        GLib.timeout_add(50, loop.quit)
        loop.run()

    try:
        for index in range(30):
            label = Gtk.Label(label=f"Earlier message {index}")
            label.set_size_request(-1, 38)
            view.conversation_box.pack_start(label, False, False, 0)
        if kind == "live":
            view._show_thinking_impl()
            view._stream_pending = Event(EventType.MESSAGE_STREAMING, {"text": text})
            view._flush_stream()
            target = view._thinking_container
            preview = view._stream_preview
            expand = view._thinking_toggle.clicked
        else:
            target = ReasoningView(text)
            preview = target.preview
            view.conversation_box.pack_start(target, False, False, 0)
            expand = lambda: target.set_expanded(True)
        window.show_all()
        layout()
        adjustment = view.widget.get_vadjustment()
        adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
        previous_position = adjustment.get_value()
        expand()
        layout()
        assert preview.get_mapped()
        assert adjustment.get_value() > previous_position
        top = target.translate_coordinates(view.conversation_box, 0, 0)[1]
        bottom = top + target.get_allocated_height()
        assert top >= adjustment.get_value() - 1
        assert bottom <= adjustment.get_value() + adjustment.get_page_size() + 1
        assert preview.get_allocated_height() <= preview.get_max_content_height()
        if height == 700:
            assert preview.get_allocated_height() > 260
    finally:
        view.clear()
        window.destroy()
