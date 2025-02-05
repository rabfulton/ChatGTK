import re
import gi

# Specify GTK versions before importing
gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "4")
from gi.repository import Gtk, GLib, Pango, GtkSource

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
            formatted_lines.append(f'<span size="xx-large"><b>{h1_match.group(1)}</b></span>')
        elif h2_match:
            # Level 2 header - medium
            formatted_lines.append(f'<span size="x-large"><b>{h2_match.group(1)}</b></span>')
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
    
    # Apply other formatting
    text = convert_single_asterisks_to_italic(text)
    text = format_headers(text)
    
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

def create_source_view(code_content, code_lang, font_size, source_theme='solarized-dark'):
    """Create a styled source view for code display."""
    source_view = GtkSource.View.new()
    
    # Apply styling
    css_provider = Gtk.CssProvider()
    css = f"""
        textview {{
            font-family: Monospace;
            font-size: {font_size}pt;
        }}
    """
    css_provider.load_from_data(css.encode())
    source_view.get_style_context().add_provider(
        css_provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    
    # Configure view settings
    source_view.set_editable(False)
    source_view.set_wrap_mode(Gtk.WrapMode.NONE)
    source_view.set_highlight_current_line(False)
    source_view.set_show_line_numbers(False)
    
    # Set up buffer with language and style
    buffer = source_view.get_buffer()
    lang_manager = GtkSource.LanguageManager.get_default()
    if code_lang in lang_manager.get_language_ids():
        lang = lang_manager.get_language(code_lang)
    else:
        lang = None
        
    scheme_manager = GtkSource.StyleSchemeManager.get_default()
    style_scheme = scheme_manager.get_scheme(source_theme)
    
    buffer.set_language(lang)
    buffer.set_highlight_syntax(True)
    buffer.set_style_scheme(style_scheme)
    buffer.set_text(code_content)
    buffer.set_highlight_matching_brackets(False)
    
    # Set size request based on content
    line_count = code_content.count('\n') + 1
    line_height = font_size * 1.5  # Approximate line height based on font size
    height = max(line_height * line_count, line_height * 1.2)  # Minimum height of 1.2 lines
    source_view.set_size_request(-1, int(height))
    
    return source_view 

def convert_single_asterisks_to_italic(text):
    """Convert markdown italic syntax (*text*) to Pango markup."""
    # Convert *italic* to <i>italic</i>, but not inside code blocks
    pattern = r'\*([^\*]+)\*'
    return re.sub(pattern, r'<i>\1</i>', text) 