"""Background responses and UI callbacks must stay with their source chat."""

from copy import deepcopy
from pathlib import Path
import sys
import threading
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from controller import ChatController
from conversation import ConversationHistory
from events import Event, EventType


@pytest.fixture
def controller():
    instance = ChatController.__new__(ChatController)
    instance._chat_state_lock = threading.RLock()
    instance._active_request_token = None
    instance._chat_history_repo = Mock()
    instance._event_bus = Mock()
    instance.system_message = "Be helpful."
    instance.current_chat_id = "first_chat"
    instance.current_chat_metadata = {}
    instance.conversation_history = [
        {"role": "system", "content": "Be helpful."},
        {"role": "user", "content": "Question for the first chat"},
    ]
    instance.custom_models = {}
    instance._pending_text_edit_events = []
    instance._text_edit_history_by_message = {}
    instance._settings_manager = Mock()
    instance._settings_manager.get.side_effect = lambda key, default=None: default
    instance.get_provider_name_for_model = Mock(return_value="openai")
    instance._provider = Mock()
    instance._provider.generate_chat_completion.return_value = "Answer for the first chat"
    instance._get_or_init_provider = Mock(return_value=instance._provider)
    instance.messages_for_model = Mock(side_effect=lambda model: deepcopy(instance.conversation_history))
    instance.get_temperature_for_model = Mock(return_value=None)
    instance._normalize_image_tags = lambda text: text
    instance.add_to_memory = Mock()
    instance.save_current_chat = Mock()
    instance._check_and_perform_compaction = Mock()
    return instance


def received_events(controller):
    return [call.args[0] for call in controller._event_bus.publish.call_args_list
            if call.args[0].type == EventType.MESSAGE_RECEIVED]


@pytest.mark.parametrize("change", ["new_chat", "load_chat", "project"])
def test_reply_in_flight_cannot_write_into_another_chat(controller, change):
    started, release = threading.Event(), threading.Event()

    def delayed_reply(**kwargs):
        started.set()
        assert release.wait(3)
        return "Late response from the first chat"

    controller._provider.generate_chat_completion.side_effect = delayed_reply
    worker = threading.Thread(target=controller.send_message, args=("gpt-5.2",))
    worker.start()
    try:
        assert started.wait(3)
        if change == "new_chat":
            controller.new_chat()
        elif change == "load_chat":
            controller._chat_service = Mock()
            controller._chat_service.load_chat.return_value = ConversationHistory.from_list([
                {"role": "system", "content": "Other chat"},
                {"role": "user", "content": "Other question"},
            ])
            assert controller.load_chat("second_chat")
        else:
            controller._projects_repo = Mock()
            controller._init_history_repo_for_project = Mock(
                side_effect=lambda: setattr(controller, "_chat_history_repo", Mock())
            )
            controller.switch_project("other_project")
        expected = deepcopy(controller.conversation_history)
    finally:
        release.set()
        worker.join(3)

    assert not worker.is_alive()
    assert controller.conversation_history == expected
    controller.save_current_chat.assert_not_called()
    controller.add_to_memory.assert_not_called()
    controller._check_and_perform_compaction.assert_not_called()
    assert received_events(controller) == []


def test_queued_worker_is_rejected_after_chat_switch(controller):
    context = controller.capture_chat_context()
    controller.new_chat()
    controller.send_message("gpt-5.2", chat_context=context)
    controller._provider.generate_chat_completion.assert_not_called()
    assert received_events(controller) == []


def test_late_error_does_not_pollute_the_new_chat(controller):
    def fail_after_switch(**kwargs):
        controller.new_chat()
        raise RuntimeError("Old request failed")
    controller._provider.generate_chat_completion.side_effect = fail_after_switch
    controller.send_message("gpt-5.2")
    assert len(controller.conversation_history) == 1
    assert not any(call.args[0].type == EventType.ERROR_OCCURRED
                   for call in controller._event_bus.publish.call_args_list)


def test_stale_tool_handler_cannot_edit_the_new_chat(controller):
    edit = Mock()
    def call_tool_after_switch(**kwargs):
        controller.new_chat()
        result = kwargs["text_edit_handler"]("file", "replace", "Wrong content")
        assert "no longer active" in result
        return "Done"
    controller._provider.generate_chat_completion.side_effect = call_tool_after_switch
    controller.send_message("gpt-5.2", tool_handlers={"text_edit_handler": edit})
    edit.assert_not_called()


def test_committed_response_event_becomes_stale_after_switch(controller):
    controller.send_message("gpt-5.2")
    events = received_events(controller)
    assert len(events) == 1
    assert events[0].data["is_current"]()
    controller.save_current_chat.assert_called_once()
    assert controller.conversation_history[-1]["content"] == "Answer for the first chat"
    controller.new_chat()
    assert not events[0].data["is_current"]()


def test_newer_request_owns_the_reply_and_thinking_state(controller):
    started, release = threading.Event(), threading.Event()
    def reply(**kwargs):
        if kwargs["messages"][-1]["content"] == "Question for the first chat":
            started.set()
            assert release.wait(3)
            return "Outdated response"
        return "Response to the new question"
    controller._provider.generate_chat_completion.side_effect = reply
    worker = threading.Thread(target=controller.send_message, args=("gpt-5.2",))
    worker.start()
    try:
        assert started.wait(3)
        with controller._chat_state_lock:
            controller.conversation_history.append({"role": "user", "content": "New question"})
        controller.send_message("gpt-5.2")
    finally:
        release.set()
        worker.join(3)

    assert not worker.is_alive()
    assert controller.conversation_history[-1]["content"] == "Response to the new question"
    assert len(received_events(controller)) == 1
    stopped = [call.args[0] for call in controller._event_bus.publish.call_args_list
               if call.args[0].type == EventType.THINKING_STOPPED]
    assert len(stopped) == 1


def test_explicitly_disabled_handlers_remain_disabled(controller):
    controller.send_message("gpt-5.2", tool_handlers={"image_tool_handler": None})
    params = controller._provider.generate_chat_completion.call_args.kwargs
    assert params["image_tool_handler"] is None


def test_queued_thinking_callback_does_not_hide_new_request():
    from ui.chat_view import ChatView
    view = ChatView.__new__(ChatView)
    pending = []
    view.schedule_ui_update = lambda callback: pending.append(callback)
    view._hide_thinking_impl = Mock()
    state = {"current": True}
    event = Event(EventType.THINKING_STOPPED, {"is_current": lambda: state["current"]})
    view._on_thinking_stopped(event)
    state["current"] = False
    pending[0]()
    view._hide_thinking_impl.assert_not_called()
