"""Tests for the reusable text edit tool handlers."""

import os
import sys
import shutil
import pytest

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from controller import ChatController, TextTarget


def test_text_get_returns_target_text():
    controller = ChatController()
    storage = {"text": "Hello"}

    target = TextTarget(
        get_text=lambda: storage["text"],
        apply_tool_edit=lambda text, summary=None: storage.__setitem__("text", text),
    )
    controller.register_text_target("doc", target)

    assert controller.handle_text_get("doc") == "Hello"


def test_apply_text_edit_replaces_target():
    controller = ChatController()
    storage = {"text": "Old"}

    target = TextTarget(
        get_text=lambda: storage["text"],
        apply_tool_edit=lambda text, summary=None: storage.__setitem__("text", text),
    )
    controller.register_text_target("doc", target)

    result = controller.handle_apply_text_edit("doc", "replace", "New", "Updated text")
    assert result == "Updated text"
    assert storage["text"] == "New"


def test_apply_text_edit_diff_applies_patch():
    if shutil.which("patch") is None:
        pytest.skip("patch utility not available")

    controller = ChatController()
    storage = {"text": "Hello\nWorld\n"}

    target = TextTarget(
        get_text=lambda: storage["text"],
        apply_tool_edit=lambda text, summary=None: storage.__setitem__("text", text),
    )
    controller.register_text_target("doc", target)

    diff = (
        "--- a/text\n"
        "+++ b/text\n"
        "@@ -1,2 +1,2 @@\n"
        " Hello\n"
        "-World\n"
        "+ChatGTK\n"
    )

    result = controller.handle_apply_text_edit("doc", "diff", diff, "Updated line")
    assert result == "Updated line"
    assert storage["text"] == "Hello\nChatGTK\n"
