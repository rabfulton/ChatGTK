import re
import gi

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

def convert_double_asterisks_to_bold(text):
    """Convert markdown bold syntax to Pango markup."""
    # First pattern: text with colon
    pattern1 = r'\*\*([^*]+?)\*\*:'
    result = re.sub(pattern1, r'<b>\1</b>:', text)
    
    # Second pattern: remaining bold text
    pattern2 = r'\*\*([^*]+?)\*\*'
    result = re.sub(pattern2, r'<b>\1</b>', result)
    
    # Show any remaining asterisks
    if '**' in result:
        print("WARNING: Remaining ** found at positions:", [i for i, c in enumerate(result) if c == '*'])
    
    return result

def format_response(text):
    """Apply all formatting to a response."""
    # Format bullet points first
    text = format_bullet_points(text)
    
    # Format code blocks
    text = format_code_blocks(text)
    
    #text = normalize_line_breaks(text)
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
            formatted_lines.append(f'\n<span size="xx-large"><b>{h1_match.group(1)}</b></span>\n')
        elif h2_match:
            # Level 2 header - medium
            formatted_lines.append(f'\n<span size="x-large"><b>{h2_match.group(1)}</b></span>\n')
        elif h3_match:
            # Level 3 header - smaller
            formatted_lines.append(f'\n<span size="large"><b>{h3_match.group(1)}</b></span>\n')
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
    text = normalize_line_breaks(text)
    return text

def process_inline_markup(text, font_size):
    """Process text for inline code and other markup."""
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
    text = normalize_line_breaks(text)
    
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
        r = int(match.group(1))
        g = int(match.group(2))
        b = int(match.group(3))
        return f'#{r:02X}{g:02X}{b:02X}'  # uppercase hex

    return pattern.sub(replacer, text)

def rgb_to_hex(rgb_str):
    """Convert RGB string like 'rgb(216,222,233)' to hex color like '#D8DEE9'."""
    try:
        # Extract the RGB values
        r, g, b = map(int, rgb_str.strip('rgb()').split(','))
        # Convert to hex
        return f'#{r:02x}{g:02x}{b:02x}'
    except:
        return '#000000'  # Default to black if conversion fails

def convert_single_asterisks_to_italic(text):
    """Convert markdown italic syntax (*text*) to Pango markup."""
    # Convert *italic* to <i>italic</i>, but not inside code blocks
    pattern = r'\*([^\*]+)\*'
    return re.sub(pattern, r'<i>\1</i>', text) 

def normalize_line_breaks(text):
    """
    Normalize line breaks around block-level elements (e.g., headers, code blocks).

    This function ensures that:
      - Lines starting with block markers (e.g., those starting with <span for headers,
        or with --- Code Block for code blocks) are preceded and followed by an empty line.
      - This yields clear paragraph breaks, which Pango/GTK interprets correctly.

    Adjust this logic as needed for your markup conventions.
    """
    lines = text.split('\n')
    new_lines = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Identify block-level elements:
        #   - Headers (produced by format_headers, starting with "<span")
        #   - Code block markers (starting with "--- Code Block")
        #   - List items that are used as headings (starting with "•")
        if (stripped.startswith('<span') or 
            stripped.startswith('--- Code Block') or 
            stripped.startswith('•')):
            # Insert an extra blank line above if the previous line isn't blank.
            if new_lines and new_lines[-1].strip() != '':
                new_lines.append('')
            new_lines.append(line)
            # Insert a blank line after only if the next line isn't block-level.
            if i < len(lines) - 1:
                next_stripped = lines[i+1].strip()
                if not (next_stripped.startswith('<span') or 
                        next_stripped.startswith('--- Code Block') or 
                        next_stripped.startswith('•')):
                    new_lines.append('')
        else:
            new_lines.append(line)
    result = '\n'.join(new_lines)

    # Debug: after joining lines

    # Collapse extra newlines between adjacent block-level elements.
    # Block-level elements here include:
    #   - Headers produced by format_headers (lines starting with "<span")
    #   - Code block markers (lines starting with "--- Code Block")
    #   - List headings (lines starting with "•")
    #
    # Additionally, if a header is immediately followed by a numbered list item that appears
    # to be a heading (e.g. "1. <span ..."), then we want to collapse the newlines between them.
    #
    # This regex captures a line that starts with one of our block-level markers and ends
    # with a non-whitespace character, then matches one or more newline characters.
    # The lookahead checks that the next non-blank line starts with either a header,
    # a code block marker, or a numbered header (e.g. "1. <span") using the pattern:
    #   (?:\d+\.\s*<span|<span|--- Code Block|•)
    result = re.sub(
        r'((?:<span|--- Code Block|•).*?\S)\n+(?=(?:\d+\.\s*<span|<span|--- Code Block|•))',
        r'\1\n\n',
        result
    )
    # Optionally, trim extra newline characters at the very end of the text.
    result = re.sub(r'\n+$', '\n', result)
    #print("Debug: Final normalized result after trimming trailing newlines:")
    #print(repr(result))
    return result 