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
from markup_utils import create_source_view
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf

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

# Special characters mapping
SPECIAL_CHARS = {
    'Ω': r'\Omega',
    'π': r'\pi',
    'μ': r'\mu',
    'θ': r'\theta',
    'α': r'\alpha',
    'β': r'\beta',
    'γ': r'\gamma',
    'δ': r'\delta',
    'ε': r'\epsilon',
    'λ': r'\lambda',
    'σ': r'\sigma',
    'τ': r'\tau',
    'φ': r'\phi',
    'ω': r'\omega',
    '±': r'\pm',
    '∑': r'\sum',
    '∫': r'\int',
    '∞': r'\infty',
    '≈': r'\approx',
    '≠': r'\neq',
    '≤': r'\leq',
    '≥': r'\geq',
    '×': r'\times',
    '÷': r'\div',
    '→': r'\rightarrow',
    '←': r'\leftarrow',
    '↔': r'\leftrightarrow',
    '∂': r'\partial',
    '∇': r'\nabla',
    '°': r'^{\circ}',
}

def generate_formula_hash(formula, is_display_math, text_color):
    """Generate a consistent hash for a formula."""
    # Create a string combining all relevant parameters
    hash_string = f"{formula}_{is_display_math}_{text_color}"
    # Create a consistent hash using SHA-256
    return hashlib.sha256(hash_string.encode()).hexdigest()[:16]

def tex_to_png(tex_string, is_display_math=False, text_color="white", chat_id=None):
    """
    Convert a TeX string to PNG using system latex tools.
    
    Args:
        tex_string (str): The TeX expression to render
        is_display_math (bool): Whether to render as display math
        text_color (str): Color for the rendered formula (hex or name)
        chat_id (str): Optional chat ID for caching formulas
    
    Returns:
        bytes: PNG image data, or None if conversion fails
    """
    # Generate a consistent hash for this formula
    formula_hash = generate_formula_hash(tex_string, is_display_math, text_color)
    
    # Check cache first if chat_id is provided
    if chat_id:
        # Remove .json extension if present
        chat_id = chat_id.replace('.json', '')
        cache_dir = Path('history') / chat_id / 'formula_cache'
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
            result = subprocess.run(['dvipng', '-D', '300', '-T', 'tight', '-bg', 'Transparent',
                          str(dvi_file), '-o', str(png_file)],
                         cwd=tmpdir, capture_output=True, text=True)
            if result.returncode != 0:
                return None

            # Read the PNG data
            png_data = png_file.read_bytes()
            
            # Save to cache if chat_id is provided
            if chat_id and png_data:
                cache_dir = Path('history') / chat_id / 'formula_cache'
                cache_dir.mkdir(parents=True, exist_ok=True)
                cache_file = cache_dir / f"formula_{formula_hash}.png"
                cache_file.write_bytes(png_data)
            
            return png_data
        except Exception:
            return None

def process_tex_markup(text, text_color, chat_id, source_theme='solarized-dark', font_size=12):
    """Process LaTeX markup in text."""
    # Clean up multiple newlines before processing
    text = re.sub(r'\n\n+', '\n', text)
    
    def replace_display_math(match):
        math_content = match.group(1)
        png_data = tex_to_png(math_content, is_display_math=True, text_color=text_color, chat_id=chat_id)
        if png_data:
            temp_dir = Path(tempfile.gettempdir())
            temp_file = temp_dir / f"math_display_{hash(math_content)}.png"
            temp_file.write_bytes(png_data)
            return f'<img src="{temp_file}"/>'
        return match.group(0)

    def replace_inline_math(match):
        math_content = match.group(1)
        png_data = tex_to_png(math_content, is_display_math=False, text_color=text_color, chat_id=chat_id)
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

    # Create source view for LaTeX code
    source_view = create_source_view(text, "latex", font_size, source_theme)

    return text

def insert_tex_image(buffer, iter, img_path):
    """Insert a TeX-generated image into the text buffer."""
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(img_path)
        buffer.insert_pixbuf(iter, pixbuf)
        # Handle spacing based on math type
        if 'math_display_' in img_path:
            buffer.insert(iter, "\n")
            # If this is part of a list item, add another newline
            if buffer.get_text(buffer.get_start_iter(), iter, True).strip().endswith(('-', '•')):
                buffer.insert(iter, "\n")
        elif 'math_inline_' in img_path:
            buffer.insert(iter, " ")
        return True
    except Exception as e:
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