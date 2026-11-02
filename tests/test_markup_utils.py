"""Regression tests for Markdown rendered as Pango markup."""

import os
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from markup_utils import (
    Gtk,
    Pango,
    fix_rgb_colors_in_markup,
    format_response,
    process_inline_markup,
)


@pytest.mark.parametrize("color, expected", [
    ("rgb(89, 174, 249)", "#59aef9"),
    ("rgba(89,174,249,0.25)", "#59aef9"),
    ("rgba(0, 0, 0, 0)", "#000000"),
    ("rgba(255, 255, 255, 1)", "#ffffff"),
    ("#59aef9", "#59aef9"),
    ("white", "white"),
    ("", ""),
])
def test_theme_colors_produce_valid_pango_markup(color, expected):
    converted = fix_rgb_colors_in_markup(color)
    assert converted == expected
    if converted:
        valid, _, text, _ = Pango.parse_markup(
            f'<span background="{converted}">code</span>', -1, "\0"
        )
        assert valid
        assert text == "code"


def test_color_conversion_inside_markup():
    markup = (
        '<span background="rgba(89,174,249,0.25)" '
        'foreground="rgb(255, 255, 255)">code</span>'
    )
    converted = fix_rgb_colors_in_markup(markup)
    valid, _, text, _ = Pango.parse_markup(converted, -1, "\0")
    assert valid
    assert text == "code"


@pytest.mark.parametrize("background, foreground", [
    ("rgba(89,174,249,0.25)", "rgb(255,255,255)"),
    ("rgb(89,174,249)", "rgba(255,255,255,0.8)"),
])
def test_issue_14_fork_vs_clone(monkeypatch, background, foreground):
    # Supply theme colors without requiring a display server.
    context = Mock()
    context.get_property.side_effect = lambda name, state: Mock(
        to_string=lambda: background if name == "background-color" else foreground
    )
    label = Mock()
    label.get_style_context.return_value = context
    monkeypatch.setattr(Gtk, "Label", lambda: label)

    markdown = """### Fork vs. Clone

It's important to distinguish between **forking** and **cloning**:

*   **Forking:** This is a **GitHub feature** that creates a *new repository* on GitHub under your account, copying the structure of the original.
*   **Cloning:** This is a **Git command** (`git clone <repository_url>`) that downloads a *copy* of a repository (either a public one or one you have access to) onto your local machine.
"""
    markup = process_inline_markup(format_response(markdown), 12)
    valid, _, text, _ = Pango.parse_markup(markup, -1, "\0")

    assert valid
    assert "• Forking: This is a GitHub feature" in text
    assert "• Cloning: This is a Git command (git clone <repository_url>)" in text
    assert text.endswith("onto your local machine.\n")
    assert "<b>forking</b>" in markup
    assert "<i>new repository</i>" in markup
    assert 'font_family="monospace"' in markup
