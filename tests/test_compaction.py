"""Regression coverage for background compaction and configured model IDs."""

from copy import deepcopy
from pathlib import Path
import sys
import threading
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from controller import ChatController
from conversation import ConversationHistory
from gi.repository import GLib


@pytest.fixture
def compaction_controller(monkeypatch):
    # Isolate compaction from GTK, disk storage, and unrelated startup services.
    controller = ChatController.__new__(ChatController)
    controller._chat_state_lock = threading.RLock()
    controller._chat_history_repo = Mock()
    controller.current_chat_id = "chat_test"
    settings = {"DEFAULT_MODEL": "GPT-5.2", "COMPACTION_KEEP_TURNS": 0}
    controller._settings_manager = Mock()
    controller._settings_manager.get.side_effect = lambda key, default=None: settings.get(key, default)
    controller.custom_models = {}
    controller.conversation_history = [
        {"role": "system", "content": "Be helpful."},
        {"role": "user", "content": "Remember the project deadline."},
        {"role": "assistant", "content": "The deadline is Friday."},
    ]
    controller._compaction_in_progress = True
    controller.get_provider_name_for_model = Mock(return_value="openai")
    provider = Mock()
    provider.generate_chat_completion.return_value = "Project deadline: Friday."
    controller._get_or_init_provider = Mock(return_value=provider)
    controller.save_current_chat = Mock()
    monkeypatch.setattr(GLib, "idle_add", lambda callback: callback())
    return controller, provider, settings


def test_compaction_resolves_display_label_and_uses_model_temperature_policy(compaction_controller):
    controller, provider, _ = compaction_controller
    history = ConversationHistory.from_list(controller.conversation_history)

    controller._run_compaction_background(history, "chat_test")

    controller.get_provider_name_for_model.assert_called_once_with("gpt-5.2")
    controller._get_or_init_provider.assert_called_once_with("gpt-5.2", "openai")
    params = provider.generate_chat_completion.call_args.kwargs
    assert params["model"] == "gpt-5.2"
    assert "temperature" not in params
    assert "Remember the project deadline." in params["messages"][0]["content"]
    data = controller.conversation_history[-1]["provider_meta"]["compacted_data"]
    assert data["model"] == "gpt-5.2"
    assert data["summary"] == "Project deadline: Friday."
    controller.save_current_chat.assert_called_once()
    assert controller._compaction_in_progress is False


def test_compaction_preserves_custom_model_id(compaction_controller):
    controller, provider, settings = compaction_controller
    controller.custom_models = {"Server/CaseSensitive": {"display_name": "Lab Model"}}
    controller.get_provider_name_for_model.return_value = "custom"
    settings["DEFAULT_MODEL"] = "Lab Model"

    controller._run_compaction_background(
        ConversationHistory.from_list(controller.conversation_history), "chat_test",
    )

    assert provider.generate_chat_completion.call_args.kwargs["model"] == "Server/CaseSensitive"


def test_compaction_with_no_eligible_messages_releases_flag(compaction_controller):
    controller, provider, settings = compaction_controller
    settings["COMPACTION_KEEP_TURNS"] = 1

    controller._run_compaction_background(
        ConversationHistory.from_list(controller.conversation_history), "chat_test",
    )

    assert controller._compaction_in_progress is False
    provider.generate_chat_completion.assert_not_called()
    controller.save_current_chat.assert_not_called()


def test_compaction_failure_releases_flag_without_changing_history(compaction_controller):
    controller, provider, _ = compaction_controller
    provider.generate_chat_completion.side_effect = RuntimeError("Model unavailable")
    original = deepcopy(controller.conversation_history)

    controller._run_compaction_background(
        ConversationHistory.from_list(original), "chat_test",
    )

    assert controller.conversation_history == original
    assert controller._compaction_in_progress is False
    controller.save_current_chat.assert_not_called()


def test_compaction_stays_in_progress_until_history_update(compaction_controller, monkeypatch):
    controller, _, _ = compaction_controller
    pending = []
    monkeypatch.setattr(GLib, "idle_add", lambda callback: pending.append(callback))

    controller._run_compaction_background(
        ConversationHistory.from_list(controller.conversation_history), "chat_test",
    )

    assert controller._compaction_in_progress is True
    assert len(pending) == 1
    pending[0]()
    assert controller._compaction_in_progress is False


def test_compaction_does_not_move_cutoff_when_new_turns_arrive(compaction_controller, monkeypatch):
    controller, _, settings = compaction_controller
    settings["COMPACTION_KEEP_TURNS"] = 1
    controller.conversation_history.extend([
        {"role": "user", "content": "Unsummarized question B"},
        {"role": "assistant", "content": "Unsummarized answer B"},
    ])
    pending = []
    monkeypatch.setattr(GLib, "idle_add", lambda callback: pending.append(callback))
    controller._run_compaction_background(
        ConversationHistory.from_list(controller.conversation_history), "chat_test",
    )
    controller.conversation_history.extend([
        {"role": "user", "content": "New question C"},
        {"role": "assistant", "content": "New answer C"},
    ])
    pending[0]()

    view, summary = controller._apply_compaction_view(controller.conversation_history)
    assert summary == "Project deadline: Friday."
    assert [message["content"] for message in view[1:]] == [
        "Unsummarized question B", "Unsummarized answer B", "New question C", "New answer C",
    ]
    assert "compacted_data" in controller.conversation_history[2]["provider_meta"]


@pytest.mark.parametrize("change", ["switch_chat", "switch_repository", "edit", "delete"])
def test_compaction_discards_summary_if_its_source_changes(
    compaction_controller, monkeypatch, change,
):
    controller, _, _ = compaction_controller
    pending = []
    monkeypatch.setattr(GLib, "idle_add", lambda callback: pending.append(callback))
    controller._run_compaction_background(
        ConversationHistory.from_list(controller.conversation_history), "chat_test",
    )
    if change == "switch_chat":
        controller.conversation_history = deepcopy(controller.conversation_history)
        controller.current_chat_id = "other_chat"
    elif change == "switch_repository":
        controller._chat_history_repo = Mock()
    elif change == "edit":
        controller.conversation_history[1]["content"] = "Edited question"
    else:
        del controller.conversation_history[1]

    pending[0]()
    assert all("compacted_data" not in msg.get("provider_meta", {})
               for msg in controller.conversation_history)
    controller.save_current_chat.assert_not_called()
    assert controller._compaction_in_progress is False


def test_compaction_releases_flag_if_history_save_raises(compaction_controller):
    controller, _, _ = compaction_controller
    controller.save_current_chat.side_effect = OSError("Disk full")
    # The fixture runs idle callbacks inline, so the worker catches this error.
    controller._run_compaction_background(
        ConversationHistory.from_list(controller.conversation_history), "chat_test",
    )
    assert controller._compaction_in_progress is False
