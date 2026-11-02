"""Regression tests for Markdown rendered as Pango markup."""

import os
import sys
import re
from unittest.mock import Mock
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from markup_utils import (
    Gtk,
    Pango,
    fix_rgb_colors_in_markup,
    format_response,
    process_inline_markup,
    process_text_formatting,
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


@pytest.mark.parametrize("fence", ["```", "````", "~~~"])
def test_fenced_code_is_preserved_before_block_formatting(fence):
    code = (
        "\n    * literal list syntax\n---\n\\$currency\n"
        "| a | b |\n| --- | --- |\n\n  final indent\n"
    )
    source = f"Outside *emphasis*\n{fence}markdown\n{code}{fence}\n\n- Real bullet"
    formatted = format_response(source)
    match = re.search(
        r'--- Code Block Start \(markdown\) ---\n(.*?)\n--- Code Block End ---',
        formatted, flags=re.DOTALL,
    )
    assert match is not None
    assert match.group(1) == code
    assert "--- Table Start ---" not in formatted
    assert "---HORIZONTAL-LINE---" not in formatted
    assert "• Real bullet" in formatted


def test_longer_fence_can_contain_shorter_fences():
    source = "````markdown\n```python\n* literal\n```\n````"
    formatted = format_response(source)
    assert "```python\n* literal\n```\n" in formatted
    assert formatted.count("--- Code Block Start") == 1


def test_unclosed_fence_preserves_literal_contents():
    formatted = format_response("```python\n* literal\n---")
    assert "* literal\n---\n--- Code Block End ---" in formatted


@pytest.mark.parametrize("source, literal", [
    ("`**literal**`", "**literal**"),
    ("`*literal*`", "*literal*"),
    ("`<tag> & value`", "<tag> & value"),
    ("`https://example.com/`", "https://example.com/"),
    ("``a `backtick` b``", "a `backtick` b"),
    ("`<audio_file>literal</audio_file>`", "<audio_file>literal</audio_file>"),
])
def test_inline_code_stays_literal_in_both_rendering_paths(monkeypatch, source, literal):
    context = Mock()
    context.get_property.return_value.to_string.return_value = "#404040"
    label = Mock()
    label.get_style_context.return_value = context
    monkeypatch.setattr(Gtk, "Label", lambda: label)
    for render in (process_inline_markup, process_text_formatting):
        markup = render(source, 12)
        valid, _, text, _ = Pango.parse_markup(markup, -1, "\0")
        assert valid
        assert text == literal
        assert "<b>" not in markup and "<i>" not in markup and "<a " not in markup
        assert 'font_family="monospace"' in markup


def test_code_can_be_bold_without_interpreting_its_contents():
    markup = process_text_formatting("**`*literal*`** and *italic*", 12)
    assert '<b><span ' in markup
    assert '*literal*</span></b>' in markup
    assert '<i>italic</i>' in markup


def test_inline_code_separates_adjacent_url():
    markup = process_text_formatting("https://example.com`*literal*`", 12)
    assert 'href="https://example.com"' in markup
    assert '*literal*</span>' in markup
    # The application handles <a> itself; Pango validates the remaining markup.
    Pango.parse_markup(re.sub(r'</?a[^>]*>', '', markup), -1, "\0")


def test_renderer_receives_exact_fenced_code_contents(monkeypatch):
    import message_renderer
    code = "\n  * literal\n---\n\n"
    formatted = format_response("```markdown\n" + code + "```")
    create_view = Mock()
    monkeypatch.setattr(message_renderer, "create_source_view", create_view)
    monkeypatch.setattr(message_renderer.Gtk, "ScrolledWindow", Mock())
    monkeypatch.setattr(message_renderer.Gtk, "Frame", Mock())
    renderer = message_renderer.MessageRenderer.__new__(message_renderer.MessageRenderer)
    renderer.settings = SimpleNamespace(font_size=12, source_theme="test")
    renderer._render_message_content(formatted, 0, Mock(), "#ffffff")
    create_view.assert_called_once_with(code, "markdown", 12, "test")
