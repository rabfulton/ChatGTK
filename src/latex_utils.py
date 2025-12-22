"""
LaTeX utilities for rendering mathematical formulas as images.

This module provides functionality to:
1. Convert TeX expressions to PNG images
2. Handle both inline and display math
3. Insert rendered formulas into GTK text buffers
4. Manage temporary files and resources
"""

import subprocess
import tempfile
from pathlib import Path
import re
import os
import gi
import hashlib
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('Gtk', '3.0')
from gi.repository import GdkPixbuf, Gtk, Gdk
import shutil
from datetime import datetime
from config import HISTORY_DIR

# Import history dir getter for project support
try:
    from ai_providers import get_current_history_dir
except ImportError:
    get_current_history_dir = lambda: HISTORY_DIR

# Constants for LaTeX templates
LATEX_DISPLAY_TEMPLATE = r"""
\documentclass{article}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{xcolor}
\pagestyle{empty}
\begin{document}
\color[rgb]{%s}
\[\displaystyle %s\]
\end{document}
"""

LATEX_INLINE_TEMPLATE = r"""
\documentclass{article}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{xcolor}
\pagestyle{empty}
\begin{document}
\color[rgb]{%s}
\(%s\)
\end{document}
"""

# Constants for PDF export
CHAT_PDF_TEMPLATE = r"""
\documentclass{article}
\usepackage[utf8]{inputenc}
\usepackage{geometry}
\usepackage{xcolor}
\usepackage{parskip}
\usepackage{listings}
\usepackage{fancyhdr}
\usepackage[hyphens]{url}
\usepackage[hidelinks]{hyperref}

\geometry{margin=1in}
\definecolor{usercolor}{RGB}{70, 130, 180}    % Steel Blue
\definecolor{assistantcolor}{RGB}{60, 179, 113}  % Medium Sea Green
\definecolor{codebg}{RGB}{40, 44, 52}          % Dark background for code
\definecolor{codetext}{RGB}{171, 178, 191}     % Light text for code

% Code listing style
\lstset{
    basicstyle=\ttfamily\small,
    breaklines=true,
    frame=single,
    numbers=left,
    numberstyle=\tiny,
    showstringspaces=false
}

\pagestyle{fancy}
\fancyhf{}
\rhead{Chat Export}
\lhead{\thepage}

\begin{document}
%s
\end{document}
"""

# Special characters mapping (Unicode to LaTeX)
SPECIAL_CHARS = {
    # Currency and common symbols
    '$': r'\$',
    '°': r'^{\circ}',
    '′': r"'",
    '″': r"''",
    '…': r'\ldots',
    
    # Greek lowercase
    'α': r'\alpha',
    'β': r'\beta',
    'γ': r'\gamma',
    'δ': r'\delta',
    'ε': r'\epsilon',
    'ζ': r'\zeta',
    'η': r'\eta',
    'θ': r'\theta',
    'ι': r'\iota',
    'κ': r'\kappa',
    'λ': r'\lambda',
    'μ': r'\mu',
    'ν': r'\nu',
    'ξ': r'\xi',
    'π': r'\pi',
    'ρ': r'\rho',
    'σ': r'\sigma',
    'τ': r'\tau',
    'υ': r'\upsilon',
    'φ': r'\phi',
    'χ': r'\chi',
    'ψ': r'\psi',
    'ω': r'\omega',
    
    # Greek uppercase
    'Γ': r'\Gamma',
    'Δ': r'\Delta',
    'Θ': r'\Theta',
    'Λ': r'\Lambda',
    'Ξ': r'\Xi',
    'Π': r'\Pi',
    'Σ': r'\Sigma',
    'Υ': r'\Upsilon',
    'Φ': r'\Phi',
    'Ψ': r'\Psi',
    'Ω': r'\Omega',
    
    # Mathematical operators
    '±': r'\pm',
    '∓': r'\mp',
    '×': r'\times',
    '÷': r'\div',
    '·': r'\cdot',
    '∗': r'\ast',
    '⊕': r'\oplus',
    '⊗': r'\otimes',
    '∘': r'\circ',
    
    # Relations
    '≈': r'\approx',
    '≠': r'\neq',
    '≤': r'\leq',
    '≥': r'\geq',
    '≪': r'\ll',
    '≫': r'\gg',
    '∼': r'\sim',
    '≃': r'\simeq',
    '≅': r'\cong',
    '≡': r'\equiv',
    '∝': r'\propto',
    '⊂': r'\subset',
    '⊃': r'\supset',
    '⊆': r'\subseteq',
    '⊇': r'\supseteq',
    '∈': r'\in',
    '∉': r'\notin',
    '∋': r'\ni',
    
    # Arrows
    '→': r'\rightarrow',
    '←': r'\leftarrow',
    '↔': r'\leftrightarrow',
    '⇒': r'\Rightarrow',
    '⇐': r'\Leftarrow',
    '⇔': r'\Leftrightarrow',
    '↑': r'\uparrow',
    '↓': r'\downarrow',
    '↦': r'\mapsto',
    
    # Big operators
    '∑': r'\sum',
    '∏': r'\prod',
    '∫': r'\int',
    '∬': r'\iint',
    '∭': r'\iiint',
    '∮': r'\oint',
    '⋃': r'\bigcup',
    '⋂': r'\bigcap',
    
    # Calculus and analysis
    '∂': r'\partial',
    '∇': r'\nabla',
    '∞': r'\infty',
    '√': r'\sqrt',
    
    # Logic and sets
    '∧': r'\land',
    '∨': r'\lor',
    '¬': r'\neg',
    '∀': r'\forall',
    '∃': r'\exists',
    '∅': r'\emptyset',
    '∩': r'\cap',
    '∪': r'\cup',
    
    # Miscellaneous math
    '†': r'\dagger',
    '‡': r'\ddagger',
    '⊥': r'\perp',
    '∥': r'\parallel',
    '∠': r'\angle',
    '△': r'\triangle',
    '□': r'\square',
    '◇': r'\diamond',
    '★': r'\star',
    '♠': r'\spadesuit',
    '♥': r'\heartsuit',
    '♦': r'\diamondsuit',
    '♣': r'\clubsuit',
    
    # Subscript/superscript digits (convert to normal)
    '₀': r'_0', '₁': r'_1', '₂': r'_2', '₃': r'_3', '₄': r'_4',
    '₅': r'_5', '₆': r'_6', '₇': r'_7', '₈': r'_8', '₉': r'_9',
    '⁰': r'^0', '¹': r'^1', '²': r'^2', '³': r'^3', '⁴': r'^4',
    '⁵': r'^5', '⁶': r'^6', '⁷': r'^7', '⁸': r'^8', '⁹': r'^9',
    
    # Mathematical script letters (common ones)
    '𝒮': r'\mathcal{S}',
    'ℰ': r'\mathcal{E}',
    'ℒ': r'\mathcal{L}',
    'ℋ': r'\mathcal{H}',
    'ℱ': r'\mathcal{F}',
    'ℛ': r'\mathcal{R}',
    'ℬ': r'\mathcal{B}',
    'ℳ': r'\mathcal{M}',
    'ℕ': r'\mathbb{N}',
    'ℤ': r'\mathbb{Z}',
    'ℚ': r'\mathbb{Q}',
    'ℝ': r'\mathbb{R}',
    'ℂ': r'\mathbb{C}',
    
    # Astronomical/misc symbols - use text mode
    '☾': r'\text{Moon}',
    '☽': r'\text{Moon}',
    '☀': r'\text{Sun}',
    '★': r'\star',
}

def generate_formula_hash(formula, is_display_math, text_color):
    """Generate a consistent hash for a formula."""
    # Create a string combining all relevant parameters
    hash_string = f"{formula}_{is_display_math}_{text_color}"
    # Create a consistent hash using SHA-256
    return hashlib.sha256(hash_string.encode()).hexdigest()[:16]

def tex_to_png(tex_string, is_display_math=False, text_color="white", chat_id=None, dpi=200):
    """
    Convert a TeX string to PNG using system latex tools.
    
    Args:
        tex_string (str): The TeX expression to render
        is_display_math (bool): Whether to render as display math
        text_color (str): Color for the rendered formula (hex or name)
        chat_id (str): Optional chat ID for caching formulas
        dpi (float): DPI value for rendering (default: 200)
    
    Returns:
        bytes: PNG image data, or None if conversion fails
    """
    # Generate a consistent hash for this formula
    formula_hash = generate_formula_hash(tex_string, is_display_math, text_color)
    
    # Check cache first if chat_id is provided
    if chat_id:
        # Remove .json extension if present
        chat_id = chat_id.replace('.json', '')
        cache_dir = Path(get_current_history_dir()) / chat_id / 'formula_cache'
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"formula_{formula_hash}.png"
        
        if cache_file.exists():
            return cache_file.read_bytes()
    
    # Replace special characters with their LaTeX equivalents
    for char, latex_cmd in SPECIAL_CHARS.items():
        if char in tex_string:
            tex_string = tex_string.replace(char, latex_cmd)

    # Convert hex color to RGB components
    if text_color.startswith('#'):
        try:
            r = int(text_color[1:3], 16) / 255
            g = int(text_color[3:5], 16) / 255
            b = int(text_color[5:7], 16) / 255
            latex_color = f"{r:.3f},{g:.3f},{b:.3f}"
        except ValueError:
            latex_color = "1,1,1"
    elif text_color.startswith('rgb'):
        # Handle 'rgb(r,g,b)' format
        try:
            # Extract the numbers from the rgb string
            rgb = re.match(r'rgb\(([\d.]+),\s*([\d.]+),\s*([\d.]+)\)', text_color)
            if rgb:
                r = float(rgb.group(1)) / 255
                g = float(rgb.group(2)) / 255
                b = float(rgb.group(3)) / 255
                latex_color = f"{r:.3f},{g:.3f},{b:.3f}"
            else:
                latex_color = "1,1,1"
        except (ValueError, AttributeError):
            latex_color = "1,1,1"
    else:
        latex_color = "1,1,1"

    # Create a temporary directory for our latex files
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        # Create the LaTeX document
        template = LATEX_DISPLAY_TEMPLATE if is_display_math else LATEX_INLINE_TEMPLATE
        latex_doc = template % (latex_color, tex_string)

        # Write the LaTeX document
        tex_file = tmp_path / "equation.tex"
        tex_file.write_text(latex_doc)

        try:
            # Run latex to create DVI
            result = subprocess.run(['latex', '-interaction=nonstopmode', str(tex_file)], 
                         cwd=tmpdir, capture_output=True, text=True)
            if result.returncode != 0:
                return None

            # Convert DVI to PNG
            dvi_file = tmp_path / "equation.dvi"
            png_file = tmp_path / "equation.png"
            if is_display_math:
                result = subprocess.run(['dvipng', '-D', f"{dpi * 1.25:.1f}", '-T', 'tight', '-bg', 'Transparent',
                          str(dvi_file), '-o', str(png_file)],
                         cwd=tmpdir, capture_output=True, text=True)
            else:
                result = subprocess.run(['dvipng', '-D', f"{dpi:.1f}", '-T', 'tight', '-bg', 'Transparent',
                          str(dvi_file), '-o', str(png_file)],
                         cwd=tmpdir, capture_output=True, text=True)
            if result.returncode != 0:
                return None

            # Read the PNG data
            png_data = png_file.read_bytes()
            
            # Save to cache if chat_id is provided
            if chat_id and png_data:
                cache_dir = Path(get_current_history_dir()) / chat_id.replace('.json', '') / 'formula_cache'
                cache_dir.mkdir(parents=True, exist_ok=True)
                cache_file = cache_dir / f"formula_{formula_hash}.png"
                cache_file.write_bytes(png_data)
            
            return png_data
        except Exception:
            return None

def process_tex_markup(text, text_color, chat_id, source_theme='solarized-dark', dpi=200):
    """
    Process LaTeX markup in the provided text for LaTeX export.

    Args:
        text (str): The text to process
        text_color (str): Color for the rendered formula
        chat_id (str): Optional chat ID for caching formulas
        source_theme (str): Theme for code highlighting
        dpi (float): DPI value for formula rendering
    """
    
    def _sanitize_math_content(math_content: str) -> str:
        """
        Remove markdown bold markers that may accidentally appear inside math
        expressions. Previously this was applied to the entire message, which
        stripped **bold** markers from plain text. Keep the sanitization scoped
        to math content only so regular markdown can render correctly.
        """
        return math_content.replace("**", "")

    def replace_display_math(match):
        math_content = _sanitize_math_content(match.group(1))
        png_data = tex_to_png(math_content, is_display_math=True, text_color=text_color, chat_id=chat_id, dpi=dpi)
        if png_data:
            temp_dir = Path(tempfile.gettempdir())
            temp_file = temp_dir / f"math_display_{hash(math_content)}.png"
            temp_file.write_bytes(png_data)
            return f'<img src="{temp_file}"/>'
        return match.group(0)

    def replace_inline_math(match):
        math_content = _sanitize_math_content(match.group(1))
        png_data = tex_to_png(math_content, is_display_math=False, text_color=text_color, chat_id=chat_id, dpi=dpi)
        if png_data:
            temp_dir = Path(tempfile.gettempdir())
            temp_file = temp_dir / f"math_inline_{hash(math_content)}.png"
            temp_file.write_bytes(png_data)
            return f'<img src="{temp_file}"/>'
        return match.group(0)

    # Process display math first \[...\]
    text = re.sub(
        r'\\\[(.*?)\\\]',
        replace_display_math,
        text,
        flags=re.DOTALL
    )
    # 2) Replace inline math of the form \( ... \) 
    text = re.sub(
        r'\\\((.*?)\\\)',
        replace_inline_math,
        text
    )
    return text

def insert_tex_image(buffer, iter, img_path, text_view=None, window=None, is_math_image=False):
    """Insert a TeX-generated image into the text buffer."""
    pixbuf_mark = None
    try:
        # Check if this is a display math equation before insertion
        is_display_math = False
        if is_math_image:
            try:
                name = os.path.basename(str(img_path))
                is_display_math = name.startswith("math_display_")
            except Exception:
                pass
        
        # For display math, ensure it's on its own line for proper centering
        if is_display_math:
            # Check if we need to add a newline before
            check_iter = iter.copy()
            if not check_iter.starts_line():
                # Not at the start of a line, add a newline before
                buffer.insert(iter, "\n")
                # iter has now moved to the start of the new line
        
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(img_path)
        
        # Use a mark to preserve the pixbuf position across buffer modifications
        # This is necessary because insertions invalidate iterators
        pixbuf_mark = buffer.create_mark(None, iter, left_gravity=True)
        
        # Insert pixbuf (GTK3 insert_pixbuf only takes 2 arguments: iter and pixbuf)
        buffer.insert_pixbuf(iter, pixbuf)
        
        if is_display_math:
            # Add a newline after display math to ensure it's on its own line
            buffer.insert(iter, "\n")
            
            # Create a tag with center justification for display math
            # Use a consistent tag name so we can reuse it
            if not hasattr(buffer, '_display_math_tag'):
                buffer._display_math_tag = buffer.create_tag("display_math_center")
                buffer._display_math_tag.set_property("justification", Gtk.Justification.CENTER)
            
            # Get fresh iterators from the mark (marks remain valid after buffer modifications)
            pixbuf_iter = buffer.get_iter_at_mark(pixbuf_mark)
            
            # Apply the center justification tag to the line containing the pixbuf
            # Get the start and end of the line containing the pixbuf
            line_start = pixbuf_iter.copy()
            line_start.set_line_offset(0)  # Start of line
            line_end = pixbuf_iter.copy()
            line_end.forward_to_line_end()  # End of line (before the newline we just added)
            
            buffer.apply_tag(buffer._display_math_tag, line_start, line_end)
        
        # Only add right-click functionality for non-math images
        if not is_math_image and text_view is not None and window is not None:
            # Store image path mapping for this buffer
            if not hasattr(buffer, '_image_paths'):
                buffer._image_paths = {}
            
            # Create a tag to mark this pixbuf
            import hashlib
            tag_name = f"image_{hashlib.md5(img_path.encode()).hexdigest()[:8]}"
            tag = buffer.create_tag(tag_name)
            
            # Apply tag to the pixbuf we just inserted
            # Get fresh iterator from mark (marks remain valid after buffer modifications)
            pixbuf_iter = buffer.get_iter_at_mark(pixbuf_mark)
            end_iter = iter.copy()
            buffer.apply_tag(tag, pixbuf_iter, end_iter)
            
            # Store the path with the tag name as key
            buffer._image_paths[tag_name] = img_path
            
            def on_text_view_button_press(widget, event):
                if event.button == 3:  # Right click
                    # Get the iter at the click position
                    x, y = text_view.window_to_buffer_coords(
                        Gtk.TextWindowType.WIDGET, int(event.x), int(event.y)
                    )
                    iter_at_click = text_view.get_iter_at_location(x, y)
                    
                    if iter_at_click is None:
                        return False
                    
                    img_path_at_click = None
                    
                    # Check if the character at this position is the object replacement character (U+FFFC)
                    # which GTK uses for pixbufs and other embedded objects
                    try:
                        char = iter_at_click.get_char()
                        # Object replacement character (U+FFFC) is used for pixbufs
                        if char == '\ufffc':
                            # This is a pixbuf, check for image tags
                            # Get tags at this position
                            tags = iter_at_click.get_tags()
                            for tag_obj in tags:
                                tag_name_at_pos = tag_obj.get_property('name')
                                if tag_name_at_pos and tag_name_at_pos.startswith('image_'):
                                    if hasattr(buffer, '_image_paths'):
                                        img_path_at_click = buffer._image_paths.get(tag_name_at_pos)
                                        if img_path_at_click:
                                            break
                            
                            # If not found, check nearby positions (pixbuf might span multiple positions)
                            if img_path_at_click is None:
                                # Check a small range around the click
                                start_iter = iter_at_click.copy()
                                end_iter = iter_at_click.copy()
                                # Check a few characters before and after
                                for i in range(3):
                                    if start_iter.backward_char():
                                        tags = start_iter.get_tags()
                                        for tag_obj in tags:
                                            tag_name_at_pos = tag_obj.get_property('name')
                                            if tag_name_at_pos and tag_name_at_pos.startswith('image_'):
                                                if hasattr(buffer, '_image_paths'):
                                                    img_path_at_click = buffer._image_paths.get(tag_name_at_pos)
                                                    if img_path_at_click:
                                                        break
                                        if img_path_at_click:
                                            break
                                    else:
                                        break
                                
                                # Also check forward
                                if img_path_at_click is None:
                                    for i in range(3):
                                        if end_iter.forward_char():
                                            tags = end_iter.get_tags()
                                            for tag_obj in tags:
                                                tag_name_at_pos = tag_obj.get_property('name')
                                                if tag_name_at_pos and tag_name_at_pos.startswith('image_'):
                                                    if hasattr(buffer, '_image_paths'):
                                                        img_path_at_click = buffer._image_paths.get(tag_name_at_pos)
                                                        if img_path_at_click:
                                                            break
                                            if img_path_at_click:
                                                break
                                        else:
                                            break
                    except Exception as e:
                        # If we can't get the character, try checking tags anyway
                        tags = iter_at_click.get_tags()
                        for tag_obj in tags:
                            tag_name_at_pos = tag_obj.get_property('name')
                            if tag_name_at_pos and tag_name_at_pos.startswith('image_'):
                                if hasattr(buffer, '_image_paths'):
                                    img_path_at_click = buffer._image_paths.get(tag_name_at_pos)
                                    if img_path_at_click:
                                        break
                    
                    if img_path_at_click:
                        menu = Gtk.Menu()
                        save_item = Gtk.MenuItem(label="Save Image As...")
                        save_item.connect("activate", lambda w: window.save_image_to_file(img_path_at_click))
                        menu.append(save_item)
                        menu.show_all()
                        menu.popup_at_pointer(event)
                        return True
                
                return False
            
            # Only connect once per text_view
            if not hasattr(text_view, '_image_button_handler_connected'):
                text_view.connect("button-press-event", on_text_view_button_press)
                text_view._image_button_handler_connected = True
        
        # Clean up the mark we created
        if pixbuf_mark is not None:
            buffer.delete_mark(pixbuf_mark)
        
        return True
    except Exception as e:
        # Clean up the mark if it was created
        if pixbuf_mark is not None:
            try:
                buffer.delete_mark(pixbuf_mark)
            except Exception:
                pass  # Mark may have already been deleted or buffer invalid
        print(f"Error loading image: {e}")
        return False 

def cleanup_temp_files(pattern="math_*_*.png"):
    """Clean up temporary LaTeX-generated image files."""
    temp_dir = Path(tempfile.gettempdir())
    for file in temp_dir.glob(pattern):
        try:
            os.remove(file)
        except Exception as e:
            print(f"Error removing temporary file {file}: {e}")

def is_latex_installed():
    """Check if required LaTeX packages are installed."""
    try:
        # Check for latex
        result = subprocess.run(['latex', '--version'], 
                              capture_output=True, text=True)
        if result.returncode != 0:
            return False
        
        # Check for dvipng
        result = subprocess.run(['dvipng', '--version'], 
                              capture_output=True, text=True)
        if result.returncode != 0:
            return False
        
        return True
    except Exception:
        return False

# Add initialization check at module level
if not is_latex_installed():
    print("Warning: LaTeX or dvipng not found. Formula rendering will not work.")


# =============================================================================
# UNIFIED TOKENIZATION SYSTEM FOR PDF EXPORT
# =============================================================================
#
# This system provides a single, coherent mechanism for protecting regions of
# text that should not be modified by escaping or newline insertion logic.
#
# Pipeline order:
#   1. Extract all protected regions (code blocks, inline code, math, headers, images)
#   2. Process plain text (markdown → LaTeX conversions, escaping)
#   3. Insert forced newlines only in plain text segments
#   4. Restore all protected regions
#
# Token format: @@TYPE_INDEX@@ where TYPE is one of:
#   - CODEBLOCK: Triple-backtick code blocks → lstlisting
#   - INLINECODE: Backtick inline code → \lstinline
#   - DISPLAYMATH: Display math $$...$$ or \[...\]
#   - INLINEMATH: Inline math $...$ or \(...\)
#   - HEADER: Markdown headers → \section*, etc.
#   - LATEXCMD: Pre-existing LaTeX commands that should pass through
#   - IMAGE: HTML img tags → \includegraphics
#   - TABLE: Markdown tables → tabular environments
#   - LINK: Hyperlinks detected in plain text/markdown
# =============================================================================


def escape_latex_text_simple(text: str) -> str:
    """
    Escape special LaTeX characters in plain text.
    
    This is a simpler version that assumes protected regions have already
    been tokenized. It escapes all special characters without trying to
    detect and preserve LaTeX commands (since those are already tokens).
    
    Note: Order matters! Backslash must be escaped first, then other chars.
    """
    # First, protect existing LaTeX escape sequences (like \$ \& \% etc.)
    # so we don't double-escape them when we escape backslashes
    # Use placeholders without underscores to avoid them being escaped
    latex_escapes = {
        r'\$': '\x00LATEXESC1\x00',  # DOLLAR
        r'\%': '\x00LATEXESC2\x00',  # PERCENT
        r'\&': '\x00LATEXESC3\x00',  # AMPERSAND
        r'\#': '\x00LATEXESC4\x00',  # HASH
        r'\_': '\x00LATEXESC5\x00',  # UNDERSCORE
        r'\{': '\x00LATEXESC6\x00',  # LBRACE
        r'\}': '\x00LATEXESC7\x00',  # RBRACE
    }
    
    # Protect LaTeX escape sequences
    for escape_seq, placeholder in latex_escapes.items():
        text = text.replace(escape_seq, placeholder)
    
    # Now escape remaining backslashes (must be done before other escapes)
    # We use a placeholder to avoid the replacement being affected by later escapes
    text = text.replace('\\', '\x00BACKSLASH\x00')
    
    # Then escape other special characters
    escapes = {
        '&': r'\&',
        '%': r'\%',
        '$': r'\$',
        '#': r'\#',
        '_': r'\_',
        '{': r'\{',
        '}': r'\}',
        '[': r'{[}',  # Protect from being interpreted as optional argument
        ']': r'{]}',  # Protect from being interpreted as optional argument
        '~': r'\textasciitilde{}',
        '^': r'\textasciicircum{}',
        '|': r'\textbar{}',
        '"': r"''",
        # Bullet and dashes
        '\u2022': r'\textbullet{}',   # •
        '\u2014': r'\textemdash{}',   # —
        '\u2013': r'\textendash{}',   # –
        '\u2011': r'-',                # NON-BREAKING HYPHEN (treat as regular hyphen)
        '\u2500': r'--',                # ─ BOX DRAWINGS LIGHT HORIZONTAL (treat as double dash)
        '\u202F': r'~',                 # NARROW NO-BREAK SPACE (treat as non-breaking space)
        '\u00A0': r'~',                 # NO-BREAK SPACE (treat as non-breaking space)
        '\u2009': r' ',                 # THIN SPACE (treat as regular space)
        '\u200A': r' ',                 # HAIR SPACE (treat as regular space)
        '\u200B': r'',                  # ZERO WIDTH SPACE (remove)
        '\u200C': r'',                  # ZERO WIDTH NON-JOINER (remove)
        '\u200D': r'',                  # ZERO WIDTH JOINER (remove)
        '\uFEFF': r'',                  # ZERO WIDTH NO-BREAK SPACE (remove)
        # Smart quotes (using unicode escapes to be explicit)
        '\u2018': r'`',    # ' left single quote
        '\u2019': r"'",    # ' right single quote  
        '\u201c': r"``",   # " left double quote
        '\u201d': r"''",   # " right double quote
        # Ellipsis
        '\u2026': r'\ldots{}',         # … HORIZONTAL ELLIPSIS
        # Latin characters with diacritics: NOT escaped because XeLaTeX with fontspec
        # supports Unicode natively. These characters will pass through as-is.
        # Removing escapes for: á (E1), ä (E4), ó (F3), ö (F6) and all other accented chars
    }
    
    # Apply escapes - ensure $ is escaped first and explicitly
    # This prevents issues where $ might be missed in edge cases
    text = text.replace('$', r'\$')
    
    # Apply other escapes
    for char, escape in escapes.items():
        if char != '$':  # Already handled above
            text = text.replace(char, escape)
    
    # Finally replace the backslash placeholder
    text = text.replace('\x00BACKSLASH\x00', r'\textbackslash{}')
    
    # Restore protected LaTeX escape sequences
    reverse_escapes = {v: k for k, v in latex_escapes.items()}
    for placeholder, escape_seq in reverse_escapes.items():
        text = text.replace(placeholder, escape_seq)
    
    return text


def normalize_problematic_unicode(text: str) -> str:
    """
    Normalize Unicode characters that frequently break LaTeX/listings.
    
    Focus on the characters observed in logs: en dash, em dash, non-breaking
    hyphen, and ellipsis. Convert them to ASCII-safe equivalents.
    """
    replacements = {
        '\u2010': '-',   # hyphen
        '\u2011': '-',   # non-breaking hyphen
        '\u2012': '-',   # figure dash
        '\u2013': '-',   # en dash
        '\u2014': '--',  # em dash
        '\u2026': '...', # ellipsis
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text


def escape_latex_specials_in_code(code: str) -> str:
    """
    Escape LaTeX special characters inside code using listings' escape markers.
    
    The literate option properly handles these characters for rendering, so we
    can rely on it instead of using escape markers.
    
    This function is kept for potential future use, but currently returns the
    code unchanged since literate handles everything we need.
    """
    # All special characters are handled by the literate option in lstset
    # No escaping needed - literate will handle $, %, &, #, _, \, | correctly
    return code

# ---------------------------------------------------------------------------
# Link handling helpers for PDF export
# ---------------------------------------------------------------------------

# Trailing punctuation that should not be part of a detected URL
LINK_TRAILING_PUNCTUATION = ")]>.,;!?"

# Patterns for the different link shapes we need to detect
MD_LINK_PATTERN = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
# Footnote-style double-bracket labels: [[11]](https://...)
DBL_BRACKET_MD_PATTERN = re.compile(r'\[\[([^\]]+)\]\]\(([^)]+)\)')
HREF_PATTERN = re.compile(r'\\href\{([^}]*)\}\{([^}]*)\}')
URL_PATTERN = re.compile(r'(?<!href=")(?P<url>(?:https?://|mailto:|file://)[^\s<\[]+)')
ANCHOR_PATTERN = re.compile(r'(?<![\w@])#([A-Za-z][\w\-\.:]*)')


def _trim_trailing_punctuation(url: str) -> tuple[str, str]:
    """
    Split a URL into (clean_url, trailing_chars) by peeling common trailing
    punctuation that should stay outside the hyperlink.
    """
    trailing = ""
    while url and url[-1] in LINK_TRAILING_PUNCTUATION:
        trailing = url[-1] + trailing
        url = url[:-1]
    return url, trailing


class ProtectedRegions:
    """
    Manages protected regions during LaTeX export processing.
    
    This class provides a unified tokenization mechanism that:
    - Extracts regions that should not be modified (code, math, headers, etc.)
    - Replaces them with placeholder tokens
    - Restores them after other processing is complete
    
    Usage:
        regions = ProtectedRegions()
        text = regions.protect_code_blocks(text)
        text = regions.protect_inline_code(text)
        text = regions.protect_math(text)
        # ... do escaping and newline processing on text ...
        text = regions.restore_all(text)
    """
    
    def __init__(self):
        self._tokens = {}  # token -> original/processed content
        self._counter = 0
    
    def _make_token(self, token_type: str) -> str:
        """Generate a unique token placeholder."""
        token = f"@@{token_type}_{self._counter}@@"
        self._counter += 1
        return token
    
    def _store(self, token_type: str, content: str) -> str:
        """Store content and return its token."""
        token = self._make_token(token_type)
        self._tokens[token] = content
        return token
    
    def protect_code_blocks(self, text: str) -> str:
        """
        Extract triple-backtick code blocks and replace with tokens.
        Converts to lstlisting environments.
        """
        # Languages that are safe to pass to listings; everything else falls back
        # to an untyped lstlisting so LaTeX won't error on unknown languages
        supported_languages = {
            'bash', 'c', 'cpp', 'c++', 'cmake', 'css', 'dockerfile', 'go', 'html',
            'ini', 'java', 'javascript', 'json', 'kotlin', 'latex', '{[latex]tex}',
            'lua', 'make', 'php', 'plain', 'powershell', 'ps1', 'python',
            'r', 'ruby', 'rust', 'scala', 'shell', 'sql', 'swift', 'text', 'toml',
            'ts', 'typescript', 'xml', 'yaml'
        }

        def codeblock_repl(match):
            language = match.group(1) or ""
            code = match.group(2)
            
            # Normalize problematic Unicode and escape LaTeX-special characters
            #code = normalize_problematic_unicode(code)
            #code = escape_latex_specials_in_code(code)

            # Map invalid/unsupported languages to valid ones or remove language
            language_map = {
                'javascript': 'java',
                'pango': '',  # Not supported, use default
                'css': '',    # Not supported, use default
                'mermaid': '',  # Diagrams - listings cannot load this language
            }
            
            # Normalize language for lstlisting
            if not language:
                language = "{[LaTeX]TeX}"
            elif language.lower() in language_map:
                mapped = language_map[language.lower()]
                language = mapped if mapped else ""
            
            # Drop languages that listings cannot handle to avoid compilation errors
            if language and language.lower() not in supported_languages:
                language = ""
            
            # lstlisting handles < and > natively, no escaping needed
            
            # Create lstlisting environment
            if language:
                formatted = f"\n\\begin{{lstlisting}}[language={language}]\n{code}\n\\end{{lstlisting}}\n"
            else:
                formatted = f"\n\\begin{{lstlisting}}\n{code}\n\\end{{lstlisting}}\n"
            return self._store("CODEBLOCK", formatted)
        
        # Process closed code blocks first
        pattern_closed = r"(?ms)^[ \t]*```(\w+)?\n(.*?)\n[ \t]*```[ \t]*(\n|$)"
        text = re.sub(pattern_closed, codeblock_repl, text)
        # Process any unclosed code blocks
        pattern_unclosed = r"(?ms)^[ \t]*```(\w+)?\n(.*)$"
        text = re.sub(pattern_unclosed, codeblock_repl, text)
        return text
    
    def protect_inline_code(self, text: str) -> str:
        """
        Extract backtick inline code and replace with tokens.
        Converts to \\lstinline commands.
        """
        def choose_delim(code_content):
            """Choose a delimiter that doesn't appear in the code."""
            # Use a wide set of delimiter candidates (single characters only for lstinline)
            # Order by likelihood of not appearing in code
            candidates = ['|', '!', '/', ':', ';', '@', '+', '=', '-', '_', '.', ',', '?', 
                        '~', '#', '%', '&', '*', '(', ')', '[', ']', '{', '}', '<', '>']
            for d in candidates:
                if d not in code_content:
                    return d
            # Fallback: use | even if it appears (shouldn't happen after escaping)
            return '|'
        
        def inline_code_repl(match):
            content = match.group(1)
            # Don't allow inline code to span newlines - this causes issues
            if '\n' in content or '\r' in content:
                # Just escape it as regular text instead
                return '`' + content + '`'
            # Strip whitespace and control characters that could break lstinline
            content = content.strip()
            # Remove control characters except common ones
            content = ''.join(c for c in content if ord(c) >= 32 or c in '\t')
            
            # Check if content contains problematic characters that break \lstinline
            # If it contains complex Unicode or characters that cause issues, use \texttt instead
            problematic_chars = ['∫', '∑', '∏', '√', '∞', '±', '×', '÷', '≤', '≥', '≠', '≈', 
                              '→', '←', '↔', '∂', '∇', 'α', 'β', 'γ', 'δ', 'ε', 'θ', 'λ', 
                              'μ', 'π', 'σ', 'φ', 'ω', 'Ω', '²', '³', '¹', '⁰', '⁴', '⁵', 
                              '⁶', '⁷', '⁸', '⁹']
            has_problematic = any(char in content for char in problematic_chars)
            
            # Normalize problematic Unicode
            content = normalize_problematic_unicode(content)
            
            # If content is too complex or contains problematic characters, use \texttt instead
            # This is more robust than \lstinline for complex Unicode
            if has_problematic or len(content) > 100:
                # Use \texttt for complex content - escape for regular LaTeX (not listings)
                escaped_content = escape_latex_text_simple(content)
                formatted = f"\\texttt{{{escaped_content}}}"
                return self._store("INLINECODE", formatted)
            
            # For simpler content, use \lstinline with listings escape markers
            content = escape_latex_specials_in_code(content)
            
            # Choose delimiter after escaping (so escaped | won't conflict)
            delim = choose_delim(content)
            # Double-check that delimiter doesn't appear in escaped content
            # (This shouldn't happen after escaping, but be safe)
            if delim in content:
                # If delimiter still appears, use \texttt as fallback
                # Remove listings escape markers and use regular LaTeX escaping
                clean_content = content.replace('(*@', '').replace('@*)', '')
                escaped_content = escape_latex_text_simple(clean_content)
                formatted = f"\\texttt{{{escaped_content}}}"
                return self._store("INLINECODE", formatted)
            
            # Apply dedicated inline code style for darker text
            formatted = f"\\lstinline[style=inlinecode]{delim}{content}{delim}"
            return self._store("INLINECODE", formatted)
        
        return re.sub(r'`([^`]+)`', inline_code_repl, text)
    
    def protect_display_math(self, text: str) -> str:
        """
        Extract display math ($$...$$ or \\[...\\]) and replace with tokens.
        Normalizes to $$...$$ format.
        """
        # We only treat display math that is on its own line.
        # Inline mentions like "use $$ ... $$" are escaped as plain text later.
        lines = text.split('\n')
        result_lines = []
        collecting_dollar = False
        collecting_bracket = False
        dollar_buffer: list[str] = []
        bracket_buffer: list[str] = []

        def flush_dollar_buffer():
            content = "\n".join(dollar_buffer)
            token = self._store("DISPLAYMATH", f"$$\n{content}\n$$")
            result_lines.append(token)

        def flush_bracket_buffer():
            content = "\n".join(bracket_buffer)
            token = self._store("DISPLAYMATH", f"\\[\n{content}\n\\]")
            result_lines.append(token)

        for line in lines:
            if collecting_dollar:
                if re.match(r'^\s*\$\$\s*$', line):
                    flush_dollar_buffer()
                    dollar_buffer = []
                    collecting_dollar = False
                else:
                    dollar_buffer.append(line)
                continue
            if collecting_bracket:
                if re.match(r'^\s*\\\]\s*$', line):
                    flush_bracket_buffer()
                    bracket_buffer = []
                    collecting_bracket = False
                else:
                    bracket_buffer.append(line)
                continue

            # Single-line \[ ... \] used as a block
            bracket_match = re.match(r'^\s*\\\[(.*?)\\\]\s*$', line)
            if bracket_match:
                result_lines.append(self._store("DISPLAYMATH", f"\\[{bracket_match.group(1)}\\]"))
                continue

            # Single-line $$ ... $$ with no surrounding text
            single_line_match = re.match(r'^\s*\$\$(.*?)\$\$\s*$', line)
            if single_line_match:
                result_lines.append(self._store("DISPLAYMATH", f"$${single_line_match.group(1)}$$"))
                continue

            # Start of a $$ block on its own line
            if re.match(r'^\s*\$\$\s*$', line):
                collecting_dollar = True
                dollar_buffer = []
                continue
            # Start of a \[ block on its own line
            if re.match(r'^\s*\\\[\s*$', line):
                collecting_bracket = True
                bracket_buffer = []
                continue

            result_lines.append(line)

        # Unclosed $$ block: treat it literally to avoid generating bad math
        if collecting_dollar:
            result_lines.append('$$')
            result_lines.extend(dollar_buffer)
        # Unclosed \[ block: treat it literally
        if collecting_bracket:
            result_lines.append(r'\[')
            result_lines.extend(bracket_buffer)

        text = '\n'.join(result_lines)

        # Any remaining inline \[...\] (not on their own line) are treated as inline math
        # to keep delimiters balanced and avoid accidentally starting display math.
        def inline_bracket_repl(match):
            content = match.group(1)
            return self._store("INLINEMATH", f"${content}$")

        text = re.sub(r'\\\[(.*?)\\\]', inline_bracket_repl, text)

        # Remaining inline $$...$$ (not block-isolated) are also converted to inline math
        def inline_dollar_repl(match):
            content = match.group(1)
            return self._store("INLINEMATH", f"${content}$")

        text = re.sub(r'\$\$(.*?)\$\$', inline_dollar_repl, text)

        return text
    
    def protect_inline_math(self, text: str) -> str:
        """
        Extract inline math ($...$ or \\(...\\)) and replace with tokens.
        Normalizes to $...$ format.
        
        Important: We need to avoid matching currency amounts like $56 or $56 from $66.
        We only match $...$ patterns that look like actual math (contain math-like content).
        """
        # First convert \(...\) to $...$
        text = re.sub(r'\\\((.*?)\\\)', r'$\1$', text)
        
        # Now protect all $...$ (but not $$...$$, which should already be tokenized)
        def inline_math_repl(match):
            # Skip if this looks like it might be part of a display math that wasn't matched
            content = match.group(1)
            if not content.strip():
                return match.group(0)  # Empty math, leave as-is
            
            # Don't match if content looks like currency (starts with digits or common currency patterns)
            # This prevents matching $56, $56 from $66, etc.
            content_stripped = content.strip()
            if re.match(r'^\d+', content_stripped):  # Starts with digits - likely currency
                return match.group(0)  # Don't treat as math
            if re.match(r'^\d+\.\d+', content_stripped):  # Decimal number - likely currency
                return match.group(0)  # Don't treat as math
            if ' from ' in content or ' to ' in content or ' of ' in content:  # Common currency phrases
                return match.group(0)  # Don't treat as math
            
            return self._store("INLINEMATH", match.group(0))
        
        return re.sub(r'(?<!\$)\$([^$]+)\$(?!\$)', inline_math_repl, text)
    
    def protect_headers(self, text: str) -> str:
        """
        Extract markdown headers and replace with tokens.
        Converts to LaTeX sectioning commands.
        Title text is escaped to handle special LaTeX characters.
        Also supports markdown bold/italic inside headers (e.g. ### **Title**).
        """
        def header_repl(match):
            level = len(match.group(1))
            title = match.group(2).strip()

            # First, process markdown bold/italic inside the header title.
            # This converts **text** / *text* to \textbf{} / \textit{} while
            # escaping special characters inside those regions and preserving
            # any existing tokens (math, code, etc.).
            title = process_bold_italic(title)

            # Protect any LaTeX commands we just created so they are not escaped.
            title = self.protect_latex_commands(title)

            # Now escape remaining plain text while preserving tokens.
            segments = self.split_by_tokens(title)
            escaped_parts = []
            for is_token, segment in segments:
                if is_token:
                    escaped_parts.append(segment)
                else:
                    escaped_parts.append(escape_latex_text_simple(segment))
            title = ''.join(escaped_parts)

            if level == 1:
                cmd = f"\\section*{{{title}}}\n"
            elif level == 2:
                cmd = f"\\subsection*{{{title}}}\n"
            elif level == 3:
                cmd = f"\\subsubsection*{{{title}}}\n"
            else:
                # \paragraph* doesn't create a visual line break - it runs into following text
                # Add \mbox{} to create content to break from, then \newline
                cmd = f"\\paragraph*{{{title}}}\\mbox{{}}\\newline\n"
            return self._store("HEADER", cmd)
        
        return re.sub(r'^(#{1,4})\s*(.+)$', header_repl, text, flags=re.MULTILINE)
    
    def protect_latex_commands(self, text: str) -> str:
        """
        Protect existing LaTeX commands from escaping.
        This handles commands like \\textbf{}, \\textit{}, \\lstinline, etc.
        Handles nested commands like \\textbf{\\textit{...}} by matching balanced braces.
        """
        def cmd_repl(match):
            return self._store("LATEXCMD", match.group(0))
        
        def match_nested_braces(text, start_pos):
            """
            Match a LaTeX command with nested braces starting at start_pos.
            Returns (end_pos, full_match) or None if not found.
            """
            # Find the command name (e.g., \textbf or \textit)
            cmd_match = re.match(r'\\([a-zA-Z]+\*?)\{', text[start_pos:])
            if not cmd_match:
                return None
            
            # Start after the opening brace
            pos = start_pos + len(cmd_match.group(0))
            brace_count = 1  # We've already seen one opening brace
            
            # Track if we're in an escaped sequence
            i = pos
            while i < len(text) and brace_count > 0:
                if text[i] == '\\' and i + 1 < len(text):
                    # Skip escaped characters (including \{ and \})
                    i += 2
                    continue
                elif text[i] == '{':
                    brace_count += 1
                    i += 1
                elif text[i] == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        # Found the matching closing brace
                        return (i + 1, text[start_pos:i+1])
                    i += 1
                else:
                    i += 1
            
            return None
        
        # Find and protect all LaTeX commands with nested braces
        # First, get token pattern to skip already-protected tokens
        token_pattern = self.get_token_pattern()
        
        result = []
        i = 0
        while i < len(text):
            # Check if we're at a token - if so, skip it
            token_match = re.match(token_pattern, text[i:])
            if token_match:
                result.append(token_match.group(0))
                i += len(token_match.group(0))
                continue
            
            # Look for LaTeX command start: \command{
            match = re.search(r'\\[a-zA-Z]+\*?\{', text[i:])
            if not match:
                # No more commands, add rest of text
                result.append(text[i:])
                break
            
            # Add text before the command
            result.append(text[i:i + match.start()])
            
            # Try to match the full command with nested braces
            cmd_start = i + match.start()
            nested_match = match_nested_braces(text, cmd_start)
            
            if nested_match:
                end_pos, full_cmd = nested_match
                # Store the command as a token
                token = self._store("LATEXCMD", full_cmd)
                result.append(token)
                i = end_pos
            else:
                # Couldn't match nested braces - might be malformed
                # Just advance past the opening brace to avoid infinite loop
                result.append(text[cmd_start:cmd_start + match.end()])
                i = cmd_start + match.end()
        
        text = ''.join(result)
        
        # Protect \lstinline commands (which use delimiters, not braces)
        text = re.sub(r'\\lstinline[|!/:;@+=][^|!/:;@+=]*[|!/:;@+=]', cmd_repl, text)
        
        # Protect double backslash (line break)
        text = re.sub(r'\\\\', cmd_repl, text)
        
        return text
    
    def protect_images(self, text: str, chat_id: str = None) -> str:
        """
        Extract HTML img tags and replace with tokens.
        Converts to LaTeX \\includegraphics commands.
        """
        def img_repl(match):
            src = match.group(1)
            image_path = process_image_path(src, chat_id)
            if image_path:
                formatted = r'\begin{center}\includegraphics[width=\linewidth]{' + image_path + r'}\end{center}'
            else:
                formatted = r'\textit{[Image unavailable]}'
            return self._store("IMAGE", formatted)
        
        return re.sub(r'<img\s+src="([^"]+)"\s*/?>', img_repl, text)
    
    def protect_tables(self, text: str) -> str:
        """
        Detect simple markdown-style tables and replace them with tokens.
        
        Supported syntax (GitHub-style):
        
            | Col1 | Col2 |
            | ---  | ---: |
            | a    |   1  |
        
        This is converted to a LaTeX tabular environment. The table content is
        fully protected from later escaping/newline logic, so it won't be
        mangled by other processing stages.
        """
        def is_table_row(line: str) -> bool:
            line = line.strip()
            # Must start and end with '|' and contain at least one inner '|'
            return line.startswith('|') and line.endswith('|') and line.count('|') >= 2

        def split_row(line: str):
            # Strip outer pipes and split on remaining
            inner = line.strip().strip('|')
            return [cell.strip() for cell in inner.split('|')]

        def is_separator_line(line: str) -> bool:
            cells = split_row(line)
            if not cells:
                return False
            # All non-empty cells must look like --- / :--- / ---:
            for cell in cells:
                if not cell:
                    return False
                if not re.fullmatch(r':?-{3,}:?', cell):
                    return False
            return True

        def alignment_from_separator(cell: str) -> str:
            cell = cell.strip()
            if cell.startswith(':') and cell.endswith(':'):
                return 'c'
            if cell.endswith(':'):
                return 'r'
            return 'l'

        def convert_table_block(table_lines):
            # Expect at least header + separator
            if len(table_lines) < 2 or not is_separator_line(table_lines[1]):
                # Not a valid table block; return original text
                return '\n'.join(table_lines)

            header_cells = split_row(table_lines[0])
            sep_cells = split_row(table_lines[1])
            data_lines = table_lines[2:]

            # Build column alignment spec based on separator row
            align_cells = sep_cells or ['---'] * len(header_cells)
            # Pad/truncate to header width
            if len(align_cells) < len(header_cells):
                align_cells += ['---'] * (len(header_cells) - len(align_cells))
            col_align = ''.join(alignment_from_separator(c) for c in align_cells[:len(header_cells)])

            # Process cell content: allow bold/italic/math tokens, escape text
            def process_cell(content: str) -> str:
                # Run bold/italic conversion with token-aware escaping
                # This reuses the same logic as normal text, but is applied
                # before the table block is tokenized, so later passes won't
                # touch it again.
                cell_text = process_bold_italic(content.strip())
                
                # Escape LaTeX special characters in the cell content
                # We need to escape dollar signs and other special chars that aren't
                # already part of LaTeX commands (like \textbf{})
                # Split by LaTeX commands to preserve them while escaping plain text
                token_pattern = r'\\[a-zA-Z]+\*?\{[^}]*\}'
                parts = re.split(f'({token_pattern})', cell_text)
                result_parts = []
                for part in parts:
                    if re.fullmatch(token_pattern, part):
                        # This is a LaTeX command (like \textbf{...}) - keep as-is
                        result_parts.append(part)
                    else:
                        # This is plain text - escape it (including dollar signs)
                        result_parts.append(escape_latex_text_simple(part))
                return ''.join(result_parts)

            header_tex = ' & '.join(process_cell(c) for c in header_cells) + r' \\ \hline'
            body_rows = []
            for line in data_lines:
                if not is_table_row(line):
                    # Stop table on first non-table row
                    break
                cells = split_row(line)
                # Pad/truncate to header width
                if len(cells) < len(header_cells):
                    cells += [''] * (len(header_cells) - len(cells))
                row_tex = ' & '.join(process_cell(c) for c in cells[:len(header_cells)]) + r' \\'
                body_rows.append(row_tex)

            rows_tex = '\n'.join([header_tex] + body_rows)
            return (
                r'\begin{tabular}{' + col_align + '}' + '\n'
                r'\hline' + '\n' +
                rows_tex + '\n' +
                r'\hline' + '\n' +
                r'\end{tabular}'
            )

        lines = text.split('\n')
        result_lines = []
        i = 0
        n = len(lines)

        while i < n:
            line = lines[i]
            if is_table_row(line) and i + 1 < n and is_separator_line(lines[i + 1]):
                # Collect contiguous table lines
                table_block = [lines[i], lines[i + 1]]
                i += 2
                while i < n and is_table_row(lines[i]):
                    table_block.append(lines[i])
                    i += 1
                table_tex = convert_table_block(table_block)
                # If conversion failed, just emit original lines
                if table_tex == '\n'.join(table_block):
                    result_lines.extend(table_block)
                else:
                    token = self._store("TABLE", table_tex)
                    result_lines.append(token)
            else:
                result_lines.append(line)
                i += 1

        return '\n'.join(result_lines)
    
    def protect_lists(self, text: str) -> str:
        """
        Convert markdown list items to LaTeX itemize/enumerate environments.
        
        Handles:
        - Unordered lists: * Item or - Item
        - Ordered lists: 1. Item, 2. Item (numeric with a dot)
        - Nested lists (indentation-based)
        - Mixed content between lists
        """
        list_re = re.compile(r'^(\s*)([\*\-]|\d+\.)\s+(.*)$')

        def parse_list_item(line: str):
            """Return (indent_level, marker, content) or None."""
            m = list_re.match(line)
            if not m:
                return None
            indent = len(m.group(1)) // 4  # 4 spaces per level
            marker = m.group(2)
            content = m.group(3)
            return indent, marker, content

        def process_item_content(raw_content: str) -> str:
            """Process markdown/escaping inside a list item's content."""
            content = process_bold_italic(raw_content)
            content = self.protect_latex_commands(content)
            parts = []
            for is_token, segment in self.split_by_tokens(content):
                if is_token:
                    parts.append(segment)
                else:
                    parts.append(escape_latex_text_simple(segment))
            return ''.join(parts)

        def process_list_block(start_idx: int, base_indent: int, ordered: bool) -> tuple[int, str]:
            """Process a block of list items of the same type/indent."""
            items = []
            i = start_idx
            while i < n:
                parsed = parse_list_item(lines[i])
                if not parsed:
                    # Allow one blank line inside a list; skip it and continue
                    if lines[i].strip() == "" and i + 1 < n and parse_list_item(lines[i + 1]):
                        i += 1
                        continue
                    break

                indent, marker, content = parsed
                is_ordered = marker.endswith('.')

                if indent < base_indent or is_ordered != ordered:
                    break
                if indent > base_indent:
                    # Should be handled as nested; stop here
                    break

                i += 1
                item_content = process_item_content(content)

                # Nested list?
                if i < n:
                    next_parsed = parse_list_item(lines[i])
                    if next_parsed and next_parsed[0] > base_indent:
                        nested_indent = next_parsed[0]
                        nested_ordered = next_parsed[1].endswith('.')
                        nested_i, nested_tex = process_list_block(i, nested_indent, nested_ordered)
                        item_content += "\n" + nested_tex
                        i = nested_i

                items.append(item_content)

            if not items:
                return start_idx, ""

            items_tex = '\n'.join(f'\\item {item}' for item in items)
            env = 'enumerate' if ordered else 'itemize'
            latex_code = f'\\begin{{{env}}}\n{items_tex}\n\\end{{{env}}}'
            return i, latex_code

        lines = text.split('\n')
        result_lines = []
        i = 0
        n = len(lines)

        while i < n:
            parsed = parse_list_item(lines[i])
            if parsed:
                base_indent, marker, _ = parsed
                ordered = marker.endswith('.')
                next_i, list_tex = process_list_block(i, base_indent, ordered)
                if list_tex:
                    token = self._store("LIST", list_tex)
                    result_lines.append(token)
                i = next_i
            else:
                result_lines.append(lines[i])
                i += 1

        return '\n'.join(result_lines)
    
    def protect_horizontal_rules(self, text: str) -> str:
        """
        Convert markdown horizontal rules (*** or ---) to LaTeX.
        
        Handles:
        - *** (three or more asterisks)
        - --- (three or more dashes)
        - Must be on their own line (possibly with whitespace)
        """
        def is_horizontal_rule(line: str) -> bool:
            """Check if a line is a horizontal rule."""
            stripped = line.strip()
            # Match *** or --- (three or more)
            return bool(re.match(r'^[\*\-]{3,}$', stripped))
        
        lines = text.split('\n')
        result_lines = []
        
        for line in lines:
            if is_horizontal_rule(line):
                # Convert to LaTeX horizontal rule with spacing
                # Use \hrule with some vertical spacing
                token = self._store("HRULE", r"\bigskip\noindent\rule{\linewidth}{0.4pt}\bigskip")
                result_lines.append(token)
            else:
                result_lines.append(line)
        
        return '\n'.join(result_lines)

    def _format_link_label(self, label: str) -> str:
        """
        Apply inline formatting and escaping to a link label, preserving tokens.
        """
        label = label or ""
        # Allow markdown bold/italic inside link labels
        label = process_bold_italic(label)
        # Protect any LaTeX commands created by formatting
        label = self.protect_latex_commands(label)

        parts = []
        for is_token, segment in self.split_by_tokens(label):
            if is_token:
                parts.append(segment)
            else:
                parts.append(escape_latex_text_simple(segment))
        return ''.join(parts)

    def _build_href(self, url: str, label=None) -> str:
        """
        Construct a LaTeX \\href{url}{label} string with proper escaping.
        If the visible text is the URL itself, wrap it in \\nolinkurl to allow wrapping.
        """
        clean_url = escape_latex_text_simple((url or "").strip())
        raw_url = (url or "").strip()

        # If no label or label equals URL, use a breakable URL presentation
        if label is None or (isinstance(label, str) and label.strip() == raw_url):
            formatted_label = r"\nolinkurl{" + escape_latex_text_simple(raw_url) + "}"
        else:
            formatted_label = self._format_link_label(label)
            # If formatting produced empty text, fall back to a breakable URL
            if not formatted_label:
                formatted_label = r"\nolinkurl{" + escape_latex_text_simple(raw_url) + "}"
        return f"\\href{{{clean_url}}}{{{formatted_label}}}"

    def _build_anchor_link(self, anchor: str, label=None) -> str:
        """
        Construct a LaTeX \\hyperlink{anchor}{label} for internal anchors.
        """
        anchor = (anchor or "").lstrip('#')
        escaped_anchor = escape_latex_text_simple(anchor)
        formatted_label = self._format_link_label(label if label is not None else f"#{anchor}")
        return f"\\hyperlink{{{escaped_anchor}}}{{{formatted_label}}}"

    def protect_links(self, text: str) -> str:
        """
        Detect links in plain text segments and replace them with LINK tokens.
        Supported:
            - Markdown links: [label](url)
            - Bare URLs: http/https/mailto/file
            - Internal anchors: #section
            - Existing \\href{url}{label} commands (pass-through)
        """
        def linkify_segment(segment: str) -> str:
            # Preserve existing LaTeX href commands as-is
            segment = HREF_PATTERN.sub(
                lambda m: self._store("LINK", m.group(0)),
                segment
            )

            # Footnote-style [[label]](url)
            def dbl_bracket_repl(match):
                label_inner = match.group(1).strip()
                url = match.group(2).strip()
                label = f"[[{label_inner}]]"
                return self._store("LINK", self._build_href(url, label))

            segment = DBL_BRACKET_MD_PATTERN.sub(dbl_bracket_repl, segment)

            # Markdown [label](url)
            def md_repl(match):
                label = match.group(1).strip()
                url = match.group(2).strip()
                return self._store("LINK", self._build_href(url, label))

            segment = MD_LINK_PATTERN.sub(md_repl, segment)

            # Bare URLs (http/https/mailto/file)
            def url_repl(match):
                raw_url = match.group("url")
                clean_url, trailing = _trim_trailing_punctuation(raw_url)
                token = self._store("LINK", self._build_href(clean_url, clean_url))
                return f"{token}{trailing}"

            segment = URL_PATTERN.sub(url_repl, segment)

            # Internal anchors like #section-one
            def anchor_repl(match):
                anchor = match.group(1)
                return self._store("LINK", self._build_anchor_link(anchor, f"#{anchor}"))

            segment = ANCHOR_PATTERN.sub(anchor_repl, segment)

            return segment

        parts = self.split_by_tokens(text)
        processed = []
        for is_token, part in parts:
            if is_token:
                processed.append(part)
            else:
                processed.append(linkify_segment(part))
        return ''.join(processed)
    
    def get_token_pattern(self) -> str:
        """Return regex pattern matching any token."""
        return r'@@(?:CODEBLOCK|INLINECODE|DISPLAYMATH|INLINEMATH|HEADER|LATEXCMD|IMAGE|TABLE|LIST|HRULE|LINK)_\d+@@'
    
    def restore_all(self, text: str) -> str:
        """
        Restore all protected regions by replacing tokens with their content.
        
        Tokens are restored in reverse order (LIFO) because later tokens may
        contain earlier tokens. For example, if \textit{$x$} is processed:
        1. $x$ becomes @@INLINEMATH_0@@
        2. \textit{@@INLINEMATH_0@@} becomes @@LATEXCMD_1@@
        
        When restoring, we must restore LATEXCMD_1 first (revealing INLINEMATH_0),
        then restore INLINEMATH_0.
        """
        # Restore in reverse order (last added first)
        for token in reversed(list(self._tokens.keys())):
            text = text.replace(token, self._tokens[token])
        return text
    
    def split_by_tokens(self, text: str) -> list:
        """
        Split text into segments, separating tokens from plain text.
        Returns list of (is_token, content) tuples.
        """
        pattern = self.get_token_pattern()
        parts = re.split(f'({pattern})', text)
        result = []
        for part in parts:
            if part:  # Skip empty strings
                is_token = re.fullmatch(pattern, part) is not None
                result.append((is_token, part))
        return result


def insert_forced_newlines_safe(text: str, regions: ProtectedRegions) -> str:
    """
    Insert LaTeX forced line breaks (\\\\) only in plain text segments.
    
    This function is aware of protected regions and will never insert
    line breaks inside code blocks, math, headers, or other protected content.
    
    Rules for adding \\\\:
    - Only in plain text segments (between tokens)
    - Not on blank lines (those become paragraph breaks)
    - Not on lines starting with LaTeX sectioning commands
    - Not on lines already ending with \\\\
    - Not on the last line before a blank line or end of segment
    """
    segments = regions.split_by_tokens(text)
    result_parts = []
    
    for is_token, content in segments:
        if is_token:
            # Token - pass through unchanged
            result_parts.append(content)
        else:
            # Plain text - process line by line
            lines = content.split('\n')
            processed = []
            
            for i, line in enumerate(lines):
                stripped = line.strip()
                
                # Rule: blank lines stay blank (paragraph break)
                if stripped == "":
                    processed.append(line)
                    continue
                
                # Rule: lines starting with sectioning commands don't get \\
                if re.match(r'^\s*\\(section|subsection|subsubsection|paragraph)\*?\{', line):
                    processed.append(line)
                    continue
                
                # Rule: lines already ending with \\ don't get another
                if re.search(r'\\\\\s*$', line):
                    processed.append(line)
                    continue
                
                # Rule: don't add \\ if this is the last line or next line is blank
                # This prevents "There's no line here to end" errors
                is_last = (i == len(lines) - 1)
                next_is_blank = (i < len(lines) - 1 and lines[i + 1].strip() == "")
                
                if is_last or next_is_blank:
                    processed.append(line)
                else:
                    processed.append(line + r"\\")
            
            result_parts.append('\n'.join(processed))
    
    return ''.join(result_parts)


def process_bold_italic(text: str) -> str:
    """
    Convert markdown bold and italic to LaTeX.
    
    Important constraints:
    - Must not span multiple lines (LaTeX \\textbf/\\textit don't allow \\par inside)
    - Content inside must have special chars escaped, but tokens must be preserved
    """
    # Token pattern to protect from escaping
    token_pattern = r'@@(?:CODEBLOCK|INLINECODE|DISPLAYMATH|INLINEMATH|HEADER|LATEXCMD|IMAGE|TABLE|LIST|HRULE)_\d+@@'
    
    def escape_preserving_tokens(content):
        """Escape content but preserve any tokens it contains."""
        # Split by tokens
        parts = re.split(f'({token_pattern})', content)
        result = []
        for part in parts:
            if re.fullmatch(token_pattern, part):
                # This is a token - keep as-is
                result.append(part)
            else:
                # This is plain text - escape it
                result.append(escape_latex_text_simple(part))
        return ''.join(result)
    
    def make_bold(match):
        content = match.group(1)
        content = escape_preserving_tokens(content)
        return f'\\textbf{{{content}}}'
    
    def make_italic(match):
        content = match.group(1)
        content = escape_preserving_tokens(content)
        return f'\\textit{{{content}}}'
    
    def make_bold_italic(match):
        content = match.group(1)
        content = escape_preserving_tokens(content)
        return f'\\textbf{{\\textit{{{content}}}}}'
    
    # Combined bold+italic: ***text*** → \textbf{\textit{text}}
    # Must be processed FIRST before individual bold/italic to avoid conflicts
    # Pattern: three asterisks, content (no asterisks), three asterisks
    text = re.sub(r'\*\*\*([^*\n]+)\*\*\*', make_bold_italic, text)
    
    # Bold: **text** → \textbf{text}
    # Use [^*\n]+ to avoid matching across newlines
    # Note: This won't match ***text*** because we already processed those
    text = re.sub(r'\*\*([^*\n]+)\*\*', make_bold, text)
    
    # Italic: *text* → \textit{text}
    # Important: Don't match list markers (which are * followed by space at start of line)
    # List markers: "* " (asterisk + space/tab at start of line)
    # Italic: "*text*" where text starts with non-whitespace character
    # Strategy: Simply require that * is followed by non-whitespace
    # This excludes "* " (list marker) but includes "*text*" (italic)
    # The pattern [^*\n\s] ensures content starts with non-space, excluding list markers
    text = re.sub(r'\*([^*\n\s][^*\n]*?)\*(?!\s)', make_italic, text)
    
    return text


def escape_latex_text(text):
    """Escape special LaTeX characters in text, preserving math expressions."""
    import re

    # Don't escape if the text is already a LaTeX equation
    if text.strip().startswith('$') and text.strip().endswith('$'):
        return text

    if text.strip().startswith('\\begin{equation*}'):
        return text

    if text.strip().startswith('\\begin{center}\\includegraphics'):
        return text

    # Tokenize expressions to protect them from escaping
    protected_items = []  # List of (token, original_text) pairs

    # Find display math $$...$$
    def display_math_repl(match):
        token = f"@@DISPLAYMATH{len(protected_items)}@@"
        protected_items.append((token, match.group(0)))
        return token

    text = re.sub(r'\$\$([^$]+)\$\$', display_math_repl, text)

    # Find inline math $...$
    def inline_math_repl(match):
        token = f"@@INLINEMATH{len(protected_items)}@@"
        protected_items.append((token, match.group(0)))
        return token

    text = re.sub(r'\$([^$]+)\$', inline_math_repl, text)

    # Find LaTeX commands like \textbf{...}, \textit{...}, \section*{...}, etc.
    def latex_cmd_repl(match):
        token = f"@@LATEXCMD{len(protected_items)}@@"
        protected_items.append((token, match.group(0)))
        return token

    # Match common LaTeX commands with their arguments
    text = re.sub(r'\\[a-zA-Z]+\*?\{[^}]*\}', latex_cmd_repl, text)

    # Also protect \lstinline commands
    def lstinline_repl(match):
        token = f"@@LATEXCMD{len(protected_items)}@@"
        protected_items.append((token, match.group(0)))
        return token

    text = re.sub(r'\\lstinline[^\s]*', lstinline_repl, text)

    # Protect double backslash (line break command)
    def double_backslash_repl(match):
        token = f"@@LATEXCMD{len(protected_items)}@@"
        protected_items.append((token, match.group(0)))
        return token

    text = re.sub(r'\\\\', double_backslash_repl, text)

    # Now escape the remaining text
    escapes = {
        '\\': r'\textbackslash{}',
        '&': r'\&',
        '%': r'\%',
        '$': r'\$',
        '#': r'\#',
        '_': r'\_',
        '{': r'\{',
        '}': r'\}',
        '~': r'\textasciitilde{}',
        '^': r'\textasciicircum{}',
        '<': r'<',
        '>': r'>',
        '"': r"''",  # Use simple quotes
        '•': r'\textbullet{}',  # Bullet point
        '—': r'\textemdash{}',  # Em dash
        '–': r'\textendash{}',  # En dash
        ''': r'`',  # Left single quote
        ''': r"'",  # Right single quote
        '"': r"''",  # Left double quote
        '"': r"''",  # Right double quote
    }

    result = text
    for char, escape in escapes.items():
        result = result.replace(char, escape)

    # Restore protected expressions
    for token, expr in protected_items:
        result = result.replace(token, expr)

    return result

def process_image_path(src, chat_id=None):
    """Convert a source path to a full path in the images directory."""
    try:
        src_path = Path(src)
        
        # If src is already an absolute path that exists, use it directly
        if src_path.is_absolute() and src_path.exists():
            return str(src_path.resolve())
        
        # Extract the image filename from the src
        image_filename = src_path.name
        
        if chat_id:
            # Construct the path in the chat-specific images directory
            image_path = Path(get_current_history_dir()) / chat_id.replace('.json', '') / 'images' / image_filename
        else:
            # Fallback to temp directory if no chat_id provided
            image_path = Path(get_current_history_dir()) / 'temp' / 'images' / image_filename
        
        # Only return path if file exists
        if image_path.exists():
            return str(image_path.resolve())
        else:
            print(f"DEBUG: Image not found: {image_path}")
            return None
    except Exception as e:
        print(f"DEBUG: Failed to process image path: {e}")
        return None

def format_message_content(content: str, chat_id=None) -> str:
    """
    Process a message content through markdown-like formatting for LaTeX export.
    
    This function uses a unified tokenization system to protect regions that
    should not be modified (code blocks, math, headers, etc.) before applying
    escaping and newline insertion to plain text.
    
    Pipeline:
        1. Remove custom tags (audio, etc.)
        2. Protect all sensitive regions with tokens
        3. Process markdown (bold/italic) in plain text
        4. Escape LaTeX special characters in plain text
        5. Insert forced newlines in plain text only
        6. Restore all protected regions
    """

    # Initialize the unified protection system
    regions = ProtectedRegions()
    
    # --- Step 0: Remove emojis ---
    # Remove characters from the Supplementary Multilingual Plane (where most emojis live)
    # This prevents LaTeX processing issues with these characters
    content = re.sub(r'[\U00010000-\U0010FFFF]', '', content)
    
    # Remove common emojis from Basic Multilingual Plane that cause LaTeX errors
    # Replace with text equivalents for better readability
    emoji_replacements = {
        '⭐': '[star]',
        '✅': '[check]',
        '❌': '[cross]',
        '➡️': '[right arrow]',
        '⬅️': '[left arrow]',
        '➡': '[right arrow]',
        '⬅': '[left arrow]',
    }
    for emoji, replacement in emoji_replacements.items():
        content = content.replace(emoji, replacement)
    
    # Remove emoji-related Unicode ranges that cause issues
    # These ranges include many emojis and symbols that LaTeX can't handle
    emoji_patterns = [
        r'[\u2600-\u26FF]',   # Miscellaneous Symbols (includes ⭐ and other symbols)
        r'[\u2700-\u27BF]',   # Dingbats (includes ✅ ❌ and other symbols)
        r'[\u2B00-\u2BFF]',   # Miscellaneous Symbols and Arrows (includes ➡ ⬅)
        r'[\uFE00-\uFE0F]',   # Variation Selectors (emoji modifiers like ️)
        r'[\u200D]',          # Zero Width Joiner (used in emoji sequences)
    ]
    for pattern in emoji_patterns:
        content = re.sub(pattern, '', content)
    
    # --- Step 1: Remove custom tags ---
    # Remove audio tags entirely
    content = re.sub(r'\n?<audio_file>.*?</audio_file>', '', content, flags=re.DOTALL)
    # Remove reasoning tags (from reasoning models like o1/o3)
    # These tags contain internal reasoning that shouldn't appear in exports
    content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)
    content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)
    
    # --- Step 2: Protect all sensitive regions (order matters!) ---
    # Code blocks first (they may contain anything, including math-like syntax)
    content = regions.protect_code_blocks(content)
    
    # Display math before inline math ($$...$$ before $...$)
    content = regions.protect_display_math(content)
    content = regions.protect_inline_math(content)
    
    # Headers (must be before inline code, as headers might contain backticks)
    content = regions.protect_headers(content)
    
    # Inline code
    content = regions.protect_inline_code(content)
    
    # Images
    content = regions.protect_images(content, chat_id)

    # Links - detect markdown/bare/anchor links while still in plain text
    content = regions.protect_links(content)

    # Tables (markdown-style) - after links so table cells can contain link tokens
    content = regions.protect_tables(content)
    
    # Lists (markdown-style) - after tables so list items can contain link tokens
    content = regions.protect_lists(content)
    
    # Horizontal rules (*** or ---) - after lists
    content = regions.protect_horizontal_rules(content)
    
    # --- Step 3: Process markdown formatting in remaining plain text ---
    # Bold and italic (these create LaTeX commands that we then protect)
    content = process_bold_italic(content)
    
    # Now protect the LaTeX commands we just created (textbf, textit, etc.)
    content = regions.protect_latex_commands(content)
    
    # --- Step 4: Escape special characters in plain text ---
    # At this point, only plain text remains unprotected
    segments = regions.split_by_tokens(content)
    escaped_parts = []
    for is_token, segment in segments:
        if is_token:
            escaped_parts.append(segment)
        else:
            escaped_parts.append(escape_latex_text_simple(segment))
    content = ''.join(escaped_parts)
    
    # --- Step 5: Insert forced newlines in plain text only ---
    content = insert_forced_newlines_safe(content, regions)
    
    # --- Step 6: Restore all protected regions ---
    content = regions.restore_all(content)
    
    return content



def format_chat_message(message, chat_id=None):
    """Format a single chat message for LaTeX."""
    role = message["role"].upper()
    content = format_message_content(message["content"], chat_id)
    color = 'usercolor' if role == 'USER' else 'assistantcolor'
    
    # Ensure role is properly escaped
    role = escape_latex_text(role)
    
    # Use raw string for LaTeX formatting to avoid string formatting issues
    return r"""
\noindent{\textbf{\color{%s}%s:}}

%s

\bigskip
""" % (color, role, content)

def export_chat_to_pdf(conversation, filename, title=None, chat_id=None):
    """
    Export a chat conversation to PDF with image support.
    
    Returns:
        tuple: (success: bool, engine_name: str or None)
        - success: True if PDF was successfully created, False otherwise
        - engine_name: Name of the LaTeX engine used ('XeLaTeX'), 
          or None if export failed
    """
    try:
        # Format title and date
        export_date = datetime.now().strftime("%Y-%m-%d %H:%M")
        title_section = ""
        if title:
            escaped_title = escape_latex_text(title)
            title_section = r"""
\begin{center}
\Large\textbf{%s}

\normalsize Generated on %s
\end{center}
\bigskip
""" % (escaped_title, export_date)

        # Format all messages with debug output
        messages_content = []
        for i, message in enumerate(conversation):
            if message['role'] != 'system':
                try:
                    formatted_message = format_chat_message(message, chat_id)
                    messages_content.append(formatted_message)
                    print(f"DEBUG: Successfully formatted message {i}")
                except Exception as e:
                    print(f"DEBUG: Error formatting message {i}: {str(e)}")
                    raise

        # Combine all content
        document_content = title_section + "\n".join(messages_content)
        
        # Create temporary directory for LaTeX files
        temp_dir = Path(tempfile.mkdtemp())
        print(f"DEBUG: Created temp directory at {temp_dir}")
        
        try:
            # LaTeX preamble for XeLaTeX (with native Unicode support)
            latex_preamble_xelatex = r"""
\documentclass{article}
\usepackage{fontspec}
\usepackage{geometry}
\usepackage{xcolor}
\usepackage{parskip}
\usepackage{listings}
\usepackage{fancyhdr}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{graphicx}
\usepackage{textcomp}
\usepackage[hyphens]{url}
\usepackage[hidelinks]{hyperref}

% Set fonts with Unicode support
% Try common system fonts that support Unicode
\IfFontExistsTF{DejaVu Serif}{
    \setmainfont{DejaVu Serif}
}{
    \IfFontExistsTF{Liberation Serif}{
        \setmainfont{Liberation Serif}
    }{
        % Fallback to default font
    }
}
\IfFontExistsTF{DejaVu Sans Mono}{
    \setmonofont{DejaVu Sans Mono}
}{
    \IfFontExistsTF{Liberation Mono}{
        \setmonofont{Liberation Mono}
    }{
        % Fallback to default monospace
    }
}

% Configure image handling
\DeclareGraphicsExtensions{.pdf,.png,.jpg,.jpeg}
\graphicspath{{./}}

\geometry{margin=1in}
\definecolor{usercolor}{RGB}{70, 130, 180}    % Steel Blue
\definecolor{assistantcolor}{RGB}{60, 179, 113}  % Medium Sea Green
\definecolor{codebg}{RGB}{40, 44, 52}          % Dark background for code
\definecolor{codetext}{RGB}{171, 178, 191}     % Light text for code
\definecolor{codecomment}{RGB}{92, 99, 112}    % Grey for comments
\definecolor{inlinecodecolor}{RGB}{40, 44, 52} % Darker inline code

% Code listing style
\lstset{
    basicstyle=\ttfamily\small,
    breaklines=true,
    frame=single,
    numbers=left,
    numberstyle=\tiny,
    showstringspaces=false,
    columns=flexible,
    keepspaces=true,
    escapeinside={(*@}{@*)},
    mathescape=false,
    texcl=false,
    upquote=true,
    basewidth={0.5em,0.45em},
    lineskip=-0.1pt,
    xleftmargin=\dimexpr\fboxsep+1pt\relax,
    xrightmargin=\dimexpr\fboxsep+1pt\relax,
    framexleftmargin=\dimexpr\fboxsep+.4pt\relax,
    resetmargins=true,
    literate={\$}{{\$}}1
             {\%}{{\%}}1
             {\&}{{\&}}1
             {\#}{{\#}}1
             {\_}{{\_}}1
             {\\}{{\textbackslash{}}}1
             {|}{\textbar{}}1
}

% Inline code style to keep text darker without a background box
\lstdefinestyle{inlinecode}{
    basicstyle=\ttfamily\small\color{inlinecodecolor},
}

% Use a dedicated inline code style for \inlinecode
\DeclareRobustCommand{\inlinecode}[1]{\lstinline[style=inlinecode]!#1!}

\pagestyle{fancy}
\fancyhf{}
\rhead{Chat Export}
\lhead{\thepage}

% Set up math mode
\allowdisplaybreaks
\setlength{\jot}{10pt}

\begin{document}
"""
            
            latex_end = r"\end{document}"
            
            # Use XeLaTeX for Unicode support
            engine_cmd = 'xelatex'
            engine_name = 'XeLaTeX'
            latex_preamble = latex_preamble_xelatex
            
            try:
                # Check if engine is available
                check_result = subprocess.run(
                    [engine_cmd, '--version'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if check_result.returncode != 0:
                    print(f"DEBUG: {engine_name} not available")
                    return (False, None)
                
                print(f"DEBUG: Using {engine_name} for PDF generation")
                
                # Combine document parts
                full_document = latex_preamble + document_content + latex_end
                
                # Write the actual LaTeX file
                tex_file = temp_dir / "chat_export.tex"
                tex_file.write_text(full_document, encoding='utf-8')
                print(f"DEBUG: Wrote LaTeX file to {tex_file}")
                
                # Run LaTeX engine with detailed output
                engine_succeeded = True
                for i in range(2):
                    print(f"DEBUG: Running {engine_name} iteration {i+1}")
                    result = subprocess.run(
                        [engine_cmd, '-interaction=nonstopmode', str(tex_file)],
                        cwd=temp_dir,
                        capture_output=True,
                        text=True,
                        encoding='utf-8',
                        errors='replace'
                    )
                    print(f"DEBUG: {engine_name} return code: {result.returncode}")
                    if result.returncode != 0:
                        print(f"DEBUG: {engine_name} stdout:")
                        print(result.stdout)
                        print(f"DEBUG: {engine_name} stderr:")
                        print(result.stderr)
                        engine_succeeded = False
                        # Save debug info and return failure
                        debug_file = Path('debug_failed.tex')
                        debug_file.write_text(full_document, encoding='utf-8')
                        print(f"DEBUG: Saved failing LaTeX to {debug_file}")
                        # Also save the log file if it exists
                        log_file = temp_dir / "chat_export.log"
                        if log_file.exists():
                            debug_log = Path('debug_failed.log')
                            try:
                                debug_log.write_text(log_file.read_text(encoding='utf-8', errors='replace'))
                            except UnicodeDecodeError:
                                # If log file contains binary data, save as binary
                                debug_log.write_bytes(log_file.read_bytes())
                            print(f"DEBUG: Saved LaTeX log to {debug_log}")
                        return (False, None)
                
                # Only check for PDF if engine completed successfully
                if not engine_succeeded:
                    return (False, None)
                
                # Check if PDF was created
                output_pdf = temp_dir / "chat_export.pdf"
                if not output_pdf.exists():
                    print(f"DEBUG: PDF file was not created with {engine_name}")
                    return (False, None)
                
                print(f"DEBUG: PDF successfully created with {engine_name}")
                        
            except FileNotFoundError:
                print(f"DEBUG: {engine_name} not found")
                return (False, None)
            except subprocess.TimeoutExpired:
                print(f"DEBUG: {engine_name} version check timed out")
                return (False, None)
            except Exception as e:
                print(f"DEBUG: Error with {engine_name}: {str(e)}")
                return (False, None)
            
            # Move the PDF file
            output_pdf = temp_dir / "chat_export.pdf"
            print(f"DEBUG: Moving PDF from {output_pdf} to {filename}")
            output_path = Path(filename)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(output_pdf), filename)
            return (True, engine_name)
            
        finally:
            # Cleanup temporary files
            shutil.rmtree(temp_dir, ignore_errors=True)
            
    except Exception as e:
        print(f"DEBUG: Exception in export_chat_to_pdf: {str(e)}")
        print("DEBUG: Exception type:", type(e))
        import traceback
        print("DEBUG: Traceback:")
        traceback.print_exc()
        return (False, None) 

 
