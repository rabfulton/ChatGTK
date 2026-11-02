import re
import gi
from utils import rgb_to_hex  # Add this import

# Specify GTK versions before importing
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Pango

def _protect_inline_code(text):
    """Mask code spans before processing Markdown outside them."""
    prefix = "\ue000"
    while prefix in text:
        prefix += "\ue000"
    protected = {}
    pattern = r'(?<!`)(`+)(?!`)([^\n]+?)(?<!`)\1(?!`)'

    def replace(match):
        token = f"{prefix}{len(protected)}\ue001"
        protected[token] = (match.group(0), match.group(2))
        return token

    return re.sub(pattern, replace, text), protected


def _map_fenced_blocks(text, format_plain):
    """Process prose separately from fenced code, preserving code contents."""
    opening = re.compile(r'(?m)^[ \t]*(`{3,}|~{3,})([^\r\n]*)\r?\n')
    parts = []
    position = 0
    while True:
        match = opening.search(text, position)
        if not match:
            parts.append(format_plain(text[position:]))
            break
        parts.append(format_plain(text[position:match.start()]))
        fence = match.group(1)
        closing = re.compile(
            r'(?m)^[ \t]*' + re.escape(fence[0]) + '{' + str(len(fence))
            + r',}[ \t]*(?:\r?\n|$)'
        ).search(text, match.end())
        end = closing.start() if closing else len(text)
        code = text[match.end():end]
        info = match.group(2).strip().split()
        language = info[0] if info else "plaintext"
        if not re.fullmatch(r'[\w.+#-]+', language):
            language = "plaintext"
        # Delimiter newlines are separate from the literal code contents.
        parts.append(f"--- Code Block Start ({language}) ---\n"
                     f"{code}\n--- Code Block End ---")
        if closing and closing.group(0).endswith("\n"):
            parts.append("\n")
        position = closing.end() if closing else len(text)
    return ''.join(parts)


def format_code_blocks(text):
    """Wrap fenced code in renderer markers without modifying its contents."""
    return _map_fenced_blocks(text, lambda plain: plain)

def _is_table_header(line):
    """Return True if line looks like a markdown table header."""
    if not line:
        return False
    stripped = line.strip()
    if '|' not in stripped:
        return False
    # Ignore lines that are pure separators
    return not _is_table_separator(stripped)

def _is_table_separator(line):
    """Return True if the line is a markdown table separator like | --- |."""
    if not line:
        return False
    stripped = line.strip().strip('|')
    if not stripped:
        return False
    cells = [cell.strip() for cell in stripped.split('|')]
    if not cells:
        return False
    pattern = re.compile(r'^:?-{3,}:?$')
    return all(bool(pattern.match(cell)) for cell in cells)

def _is_table_row(line):
    """Return True if the line represents a markdown row (not separator)."""
    if not line:
        return False
    stripped = line.strip()
    if '|' not in stripped:
        return False
    return not _is_table_separator(stripped)

def format_tables(text):
    """Wrap markdown tables with explicit markers for downstream rendering."""
    lines = text.split('\n')
    formatted_lines = []
    i = 0

    while i < len(lines):
        line = lines[i]
        next_idx = i + 1
        if (
            _is_table_header(line)
            and next_idx < len(lines)
            and _is_table_separator(lines[next_idx])
        ):
            start = i
            i = next_idx + 1
            while i < len(lines) and _is_table_row(lines[i]):
                i += 1
            table_block = '\n'.join(l for l in lines[start:i] if l.strip())
            formatted_lines.append('--- Table Start ---')
            formatted_lines.append(table_block)
            formatted_lines.append('--- Table End ---')
        else:
            formatted_lines.append(line)
            i += 1

    return '\n'.join(formatted_lines)

def format_bullet_points(text):
    """Replace markdown bullet points with bullet symbols, stripping indentation.
    
    Leading whitespace is stripped and will be handled by the renderer's
    left_margin tag for proper hanging indent on wrapped lines.
    """
    lines = text.split('\n')
    formatted_lines = []

    for line in lines:
        # Match leading whitespace separately to track nesting level
        match = re.match(r'^(\s*)([-*])\s+(.*)$', line)
        if match:
            indent, bullet, content = match.groups()
            # Store nesting level as a marker that renderer can detect
            # Use non-breaking spaces as level markers (will be stripped by renderer)
            level = len(indent) // 2  # 2 spaces per level
            level_marker = '\u200B' * level  # Zero-width spaces as level marker
            formatted_lines.append(f'{level_marker}• {content}')
        else:
            formatted_lines.append(line)

    return '\n'.join(formatted_lines)

def format_horizontal_lines(text):
    """Replace horizontal rule markers (*** or ---) with special markers for later processing."""
    lines = text.split('\n')
    formatted_lines = []

    for line in lines:
        # Check if line contains only whitespace + (*** or ---) + whitespace
        stripped = line.strip()
        if stripped == '***' or stripped == '---':
            # Replace with special marker that will be processed later
            formatted_lines.append('---HORIZONTAL-LINE---')
        else:
            formatted_lines.append(line)

    return '\n'.join(formatted_lines)

def escape_for_pango_markup(text):
    """Escapes markup-sensitive characters for Pango markup."""
    return GLib.markup_escape_text(text)

def format_response(text):
    """Apply block formatting outside fenced code and inline code spans."""
    def format_plain(plain):
        masked, protected = _protect_inline_code(plain)
        masked = masked.replace(r"\$", "$")
        masked = format_bullet_points(masked)
        masked = format_horizontal_lines(masked)
        masked = format_tables(masked)
        for token, (original, _) in protected.items():
            masked = masked.replace(token, original)
        return masked

    return _map_fenced_blocks(text, format_plain)

def format_headers(text):
    """Format markdown headers with appropriate styling."""
    lines = text.split('\n')
    formatted_lines = []
    
    for line in lines:
        # Match different header levels
        h1_match = re.match(r'^#\s+(.+)$', line)
        h2_match = re.match(r'^##\s+(.+)$', line)
        h3_match = re.match(r'^###\s+(.+)$', line)
        h4_match = re.match(r'^####\s+(.+)$', line)
        
        if h1_match:
            # Level 1 header - largest
            formatted_lines.append(f'<span size="xx-large"><b>{h1_match.group(1)}</b></span>\n')
        elif h2_match:
            # Level 2 header - medium
            formatted_lines.append(f'<span size="x-large"><b>{h2_match.group(1)}</b></span>\n')
        elif h3_match:
            # Level 3 header - smaller
            formatted_lines.append(f'<span size="large"><b>{h3_match.group(1)}</b></span>\n')
        elif h4_match:
            # Level 4 header - smallest heading style
            formatted_lines.append(f'<span size="medium"><b>{h4_match.group(1)}</b></span>\n')
        else:
            formatted_lines.append(line)
    
    return '\n'.join(formatted_lines)

def _linkify(text: str) -> str:
    """
    Convert markdown-style links and bare URLs into Pango <a href="..."> links.
    This should be called *after* escaping for Pango markup so that any '&'
    characters in query strings are already encoded as &amp;.
    """
    if not text:
        return text

    # 0) Grok-style footnote links: [[number]](https://example.com) -> [number] as clickable link
    grok_footnote_pattern = re.compile(r'\[\[(\d+)\]\]\((https?://[^\s)\uE000]+)\)')

    def _grok_repl(match):
        footnote_num = match.group(1)
        href = match.group(2)
        return f'<a href="{href}">[{footnote_num}]</a>'

    text = grok_footnote_pattern.sub(_grok_repl, text)

    # 1) Standard markdown links: [label](https://example.com) or [label](#anchor)
    md_link_pattern = re.compile(r'\[([^\]]+)\]\((https?://[^\s)\uE000]+|#[^\s)\uE000]+)\)')

    def _md_repl(match):
        label = match.group(1)
        href = match.group(2)
        return f'<a href="{href}">{label}</a>'

    text = md_link_pattern.sub(_md_repl, text)

    # 2) Bare URLs. Avoid wrapping URLs that are already part of an href.
    # We intentionally stop the URL before a '[' so that Grok-style footnote
    # patterns like `https://example.com)[[2]](https://...)` do not get merged
    # into a single long link. Trailing punctuation is trimmed in the
    # replacement step.
    url_pattern = re.compile(r'(?<!href=")(https?://[^\s<\[\uE000]+)')

    def _url_repl(match):
        url = match.group(1)

        # Trim trailing punctuation that should not be part of the URL.
        # This handles patterns like `(https://example.com)` where the closing
        # `)` or `]` (and some other punctuation) is rendered outside the link.
        trailing = ""
        while url and url[-1] in ")]>.,;!?":
            trailing = url[-1] + trailing
            url = url[:-1]

        return f'<a href="{url}">{url}</a>{trailing}'

    text = url_pattern.sub(_url_repl, text)
    return text


def _render_inline_markup(text, background, foreground):
    """Format prose first and restore escaped code after all Markdown passes."""
    masked, protected = _protect_inline_code(text)
    masked = re.sub(r'\n?<audio_file>.*?</audio_file>', '', masked)
    masked = escape_for_pango_markup(masked)
    masked = _linkify(masked)
    masked = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', masked)
    masked = convert_single_asterisks_to_italic(masked)
    masked = format_headers(masked)
    for token, (_, code) in protected.items():
        markup = (
            f'<span font_family="monospace" background="{background}" '
            f'foreground="{foreground}">{escape_for_pango_markup(code)}</span>'
        )
        masked = masked.replace(token, markup)
    return masked


def process_text_formatting(text, font_size):
    """Format text and literal inline code beside rendered math/images."""
    return _render_inline_markup(text, "#404040", "#ffffff")

def process_inline_markup(text, font_size):
    """Format prose and literal inline code using the current theme."""
    label = Gtk.Label()
    context = label.get_style_context()
    context.add_class('selection')
    bg_color = "#404040"
    fg_color = "#ffffff"
    try:
        provider = Gtk.CssProvider()
        provider.load_from_data(b"""
            .selection:selected {
                background-color: @theme_selected_bg_color;
                color: @theme_selected_fg_color;
            }
        """)
        context.add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        bg_color = fix_rgb_colors_in_markup(
            context.get_property('background-color', Gtk.StateFlags.SELECTED).to_string()
        )
        fg_color = fix_rgb_colors_in_markup(
            context.get_property('color', Gtk.StateFlags.SELECTED).to_string()
        )
    except Exception as error:
        print(f"Error getting theme colors: {error}")
    return _render_inline_markup(text, bg_color, fg_color)

def fix_rgb_colors_in_markup(text: str) -> str:
    """
    Convert CSS rgb/rgba colors to Pango-compatible '#RRGGBB' colors.

    GTK themes can return rgba colors, but Pango color attributes reject
    CSS color functions. Use the RGB channels and discard theme opacity.
    Replaces colors both on their own and inside markup strings.
    """
    if not text:
        return text

    pattern = re.compile(
        r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*'
        r'(?:,\s*\d*\.?\d+\s*)?\)'
    )

    def replacer(match):
        rgb_str = f"rgb({match.group(1)},{match.group(2)},{match.group(3)})"
        return rgb_to_hex(rgb_str)

    return pattern.sub(replacer, text)

def convert_single_asterisks_to_italic(text):
    """Convert markdown italic syntax (*text*) to Pango markup."""
    # Convert *italic* to <i>italic</i>, but not inside code blocks
    pattern = r'\*([^\*]+)\*'
    return re.sub(pattern, r'<i>\1</i>', text) 
