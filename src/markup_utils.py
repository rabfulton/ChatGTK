import re
import gi
from utils import rgb_to_hex  # Add this import

# Specify GTK versions before importing
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Pango

def format_code_blocks(text):
    """Format code blocks with language markers."""
    # Updated pattern to capture optional language and content more precisely
    pattern = r'```(\w+)?\s*(.*?)```'
    
    def replacer(match):
        # If the user provided a language after the triple backticks, group(1) will have it
        code_lang = match.group(1) or "plaintext"
        code_content = match.group(2).strip()
        
        # Add markers with clear separation and ensure they're on their own lines
        result = (
            "--- Code Block Start (" + code_lang + ") ---\n" +
            code_content +
            "\n--- Code Block End ---"
        )
        return result
    
    # Replace all code blocks in the text
    processed = re.sub(pattern, replacer, text, flags=re.DOTALL)
    
    return processed

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
    pattern = re.compile(r'^(:?-{3,}:?\s*)(\|\s*:?-{3,}:?\s*)*$')
    return bool(pattern.match(stripped))

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
    """Replace markdown bullet points with bullet symbols."""
    # Replace lines starting with '-' or '*' with a bullet symbol
    # Make sure we don't match inside code blocks
    lines = text.split('\n')
    formatted_lines = []
    
    for line in lines:
        # Only format lines that start with - or * followed by a space
        if re.match(r'^\s*[-*]\s+', line):
            # Replace only the first occurrence of - or * with a bullet
            formatted_line = re.sub(r'^\s*[-*]\s+', '• ', line)
            formatted_lines.append(formatted_line)
        else:
            formatted_lines.append(line)
    
    return '\n'.join(formatted_lines)

def escape_for_pango_markup(text):
    """Escapes markup-sensitive characters for Pango markup."""
    return GLib.markup_escape_text(text)

def format_response(text):
    """Apply all formatting to a response."""
    # Format bullet points first
    text = format_bullet_points(text)
    
    # Format code blocks
    text = format_code_blocks(text)

    # Format tables
    text = format_tables(text)
    
    return text

def format_headers(text):
    """Format markdown headers with appropriate styling."""
    lines = text.split('\n')
    formatted_lines = []
    
    for line in lines:
        # Match different header levels
        h1_match = re.match(r'^#\s+(.+)$', line)
        h2_match = re.match(r'^##\s+(.+)$', line)
        h3_match = re.match(r'^###\s+(.+)$', line)
        
        if h1_match:
            # Level 1 header - largest
            formatted_lines.append(f'<span size="xx-large"><b>{h1_match.group(1)}</b></span>\n')
        elif h2_match:
            # Level 2 header - medium
            formatted_lines.append(f'<span size="x-large"><b>{h2_match.group(1)}</b></span>\n')
        elif h3_match:
            # Level 3 header - smaller
            formatted_lines.append(f'<span size="large"><b>{h3_match.group(1)}</b></span>')
        else:
            formatted_lines.append(line)
    
    return '\n'.join(formatted_lines)

def process_text_formatting(text, font_size):
    """Process all inline text formatting (bold, italic, etc.)."""
    # First, escape any existing markup
    text = escape_for_pango_markup(text)
    
    # Handle code within bold text
    pattern0 = r'\*\*`([^`]+)`\*\*'
    text = re.sub(pattern0, r'<b><span font_family="monospace" background="#404040" foreground="#ffffff">\1</span></b>', text)
    
    # Handle all bold text
    pattern1 = r'\*\*([^*`]+?)\*\*'
    text = re.sub(pattern1, r'<b>\1</b>', text)
    
    # Apply other formatting and normalize line breaks.
    text = convert_single_asterisks_to_italic(text)
    text = format_headers(text)
    return text

def process_inline_markup(text, font_size):
    """Process text for inline code and other markup."""
    # First, remove audio tags from display but keep the text content
    text = re.sub(r'\n?<audio_file>.*?</audio_file>', '', text)
    
    # First, escape any existing markup
    text = escape_for_pango_markup(text)
    
    # Get theme colors for code blocks
    label = Gtk.Label()
    context = label.get_style_context()
    context.add_class('selection')
    
    bg_color = "#404040"  # Fallback dark gray
    fg_color = "#ffffff"  # Fallback white
    
    try:
        provider = Gtk.CssProvider()
        provider.load_from_data(b"""
            .selection:selected {
                background-color: @theme_selected_bg_color;
                color: @theme_selected_fg_color;
            }
        """)
        context.add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        
        # Get colors directly from context properties
        bg_color = context.get_property('background-color', Gtk.StateFlags.SELECTED).to_string()
        fg_color = context.get_property('color', Gtk.StateFlags.SELECTED).to_string()
        bg_color = fix_rgb_colors_in_markup(bg_color)
        fg_color = fix_rgb_colors_in_markup(fg_color)
    except Exception as e:
        print(f"Error getting theme colors: {e}")
    
    # Handle bold text with code inside - use theme colors
    pattern0 = r'\*\*`([^`]+)`\*\*'
    text = re.sub(pattern0, lambda m: f'<b><span font_family="monospace" background="{bg_color}" foreground="{fg_color}">{m.group(1)}</span></b>', text)
    
    # Handle remaining bold text
    pattern1 = r'\*\*([^*]+?)\*\*'
    text = re.sub(pattern1, r'<b>\1</b>', text)
    
    # Handle remaining inline code
    parts = re.split(r'(`[^`]+`)', text)
    processed_parts = []
    
    for part in parts:
        if part.startswith("`") and part.endswith("`"):
            code_content = part[1:-1]
            processed_parts.append(
                f'<span font_family="monospace" background="{bg_color}" foreground="{fg_color}">{code_content}</span>'
            )
        else:
            processed_parts.append(part)
    
    # Apply remaining formatting
    text = "".join(processed_parts)
    text = convert_single_asterisks_to_italic(text)
    text = format_headers(text)
    #text = normalize_line_breaks(text)
    
    return text

def fix_rgb_colors_in_markup(text: str) -> str:
    """
    Convert any occurrences of 'rgb(R, G, B)' in the string to '#RRGGBB'.
    This does not attempt to parse attribute names or validate usage,
    it just replaces the pattern wherever it appears.
    """
    if not text:
        return text

    # Regex to match rgb(...) anywhere in the string
    pattern = re.compile(r'rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)')

    def replacer(match):
        rgb_str = f"rgb({match.group(1)},{match.group(2)},{match.group(3)})"
        return rgb_to_hex(rgb_str)

    return pattern.sub(replacer, text)

def convert_single_asterisks_to_italic(text):
    """Convert markdown italic syntax (*text*) to Pango markup."""
    # Convert *italic* to <i>italic</i>, but not inside code blocks
    pattern = r'\*([^\*]+)\*'
    return re.sub(pattern, r'<i>\1</i>', text) 
