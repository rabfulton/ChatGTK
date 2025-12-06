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
from gi.repository import GdkPixbuf
import shutil
from datetime import datetime

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
\usepackage[hidelinks]{hyperref}

\geometry{margin=1in}
\definecolor{usercolor}{RGB}{70, 130, 180}    % Steel Blue
\definecolor{assistantcolor}{RGB}{60, 179, 113}  % Medium Sea Green
\definecolor{codebg}{RGB}{40, 44, 52}          % Dark background for code
\definecolor{codetext}{RGB}{171, 178, 191}     % Light text for code

% Code listing style
\lstset{
    basicstyle=\ttfamily\small,
    backgroundcolor=\color{codebg},
    basicstyle=\color{codetext}\ttfamily\small,
    breaklines=true,
    frame=single,
    numbers=left,
    numberstyle=\tiny\color{codetext},
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
                cache_dir = Path('history') / chat_id.replace('.json', '') / 'formula_cache'
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
    
    def replace_display_math(match):
        math_content = match.group(1)
        png_data = tex_to_png(math_content, is_display_math=True, text_color=text_color, chat_id=chat_id, dpi=dpi)
        if png_data:
            temp_dir = Path(tempfile.gettempdir())
            temp_file = temp_dir / f"math_display_{hash(math_content)}.png"
            temp_file.write_bytes(png_data)
            return f'<img src="{temp_file}"/>'
        return match.group(0)

    def replace_inline_math(match):
        math_content = match.group(1)
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
    text = text.replace("**", "")  # Remove any occurrences of "**" from inline math : Note this is not a perfect solution
    text = re.sub(
        r'\\\((.*?)\\\)',
        replace_inline_math,
        text
    )
    return text

def insert_tex_image(buffer, iter, img_path):
    """Insert a TeX-generated image into the text buffer."""
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(img_path)
        buffer.insert_pixbuf(iter, pixbuf)
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
# =============================================================================


def escape_latex_text_simple(text: str) -> str:
    """
    Escape special LaTeX characters in plain text.
    
    This is a simpler version that assumes protected regions have already
    been tokenized. It escapes all special characters without trying to
    detect and preserve LaTeX commands (since those are already tokens).
    
    Note: Order matters! Backslash must be escaped first, then other chars.
    """
    # First escape backslashes (must be done first to avoid double-escaping)
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
        '~': r'\textasciitilde{}',
        '^': r'\textasciicircum{}',
        '"': r"''",
        # Bullet and dashes
        '\u2022': r'\textbullet{}',   # •
        '\u2014': r'\textemdash{}',   # —
        '\u2013': r'\textendash{}',   # –
        # Smart quotes (using unicode escapes to be explicit)
        '\u2018': r'`',    # ' left single quote
        '\u2019': r"'",    # ' right single quote  
        '\u201c': r"``",   # " left double quote
        '\u201d': r"''",   # " right double quote
    }
    
    for char, escape in escapes.items():
        text = text.replace(char, escape)
    
    # Finally replace the backslash placeholder
    text = text.replace('\x00BACKSLASH\x00', r'\textbackslash{}')
    
    return text


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
        def codeblock_repl(match):
            language = match.group(1) or ""
            code = match.group(2)
            # Normalize language for lstlisting
            if not language:
                language = "{[LaTeX]TeX}"
            elif language.lower() == 'javascript':
                language = 'java'
            # Create lstlisting environment - preserve code exactly as-is
            formatted = f"\n\\begin{{lstlisting}}[language={language}]\n{code}\n\\end{{lstlisting}}\n"
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
            candidates = ['|', '!', '/', ':', ';', '@', '+', '=']
            for d in candidates:
                if d not in code_content:
                    return d
            return '|'
        
        def inline_code_repl(match):
            content = match.group(1)
            # Don't allow inline code to span newlines - this causes issues
            if '\n' in content:
                # Just escape it as regular text instead
                return '`' + content + '`'
            delim = choose_delim(content)
            formatted = f"\\lstinline{delim}{content}{delim}"
            return self._store("INLINECODE", formatted)
        
        return re.sub(r'`([^`]+)`', inline_code_repl, text)
    
    def protect_display_math(self, text: str) -> str:
        """
        Extract display math ($$...$$ or \\[...\\]) and replace with tokens.
        Normalizes to $$...$$ format.
        """
        # First convert \[...\] to $$...$$
        text = re.sub(r'\\\[(.*?)\\\]', r'$$\1$$', text, flags=re.DOTALL)
        
        # Now protect all $$...$$ blocks
        def display_math_repl(match):
            return self._store("DISPLAYMATH", match.group(0))
        
        return re.sub(r'\$\$([^$]+)\$\$', display_math_repl, text)
    
    def protect_inline_math(self, text: str) -> str:
        """
        Extract inline math ($...$ or \\(...\\)) and replace with tokens.
        Normalizes to $...$ format.
        """
        # First convert \(...\) to $...$
        text = re.sub(r'\\\((.*?)\\\)', r'$\1$', text)
        
        # Now protect all $...$ (but not $$...$$, which should already be tokenized)
        def inline_math_repl(match):
            # Skip if this looks like it might be part of a display math that wasn't matched
            content = match.group(1)
            if not content.strip():
                return match.group(0)  # Empty math, leave as-is
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
                cmd = f"\\section*{{{title}}}"
            elif level == 2:
                cmd = f"\\subsection*{{{title}}}"
            elif level == 3:
                cmd = f"\\subsubsection*{{{title}}}"
            else:
                cmd = f"\\paragraph*{{{title}}}"
            return self._store("HEADER", cmd)
        
        return re.sub(r'^(#{1,4})\s*(.+)$', header_repl, text, flags=re.MULTILINE)
    
    def protect_latex_commands(self, text: str) -> str:
        """
        Protect existing LaTeX commands from escaping.
        This handles commands like \\textbf{}, \\textit{}, \\lstinline, etc.
        """
        def cmd_repl(match):
            return self._store("LATEXCMD", match.group(0))
        
        # Protect commands with braces: \cmd{...} or \cmd*{...}
        # Use a pattern that handles escaped braces inside: \{ and \}
        # Match: \command{ then any chars except unescaped }, then }
        # This handles content like \textbf{hello \& world}
        text = re.sub(r'\\[a-zA-Z]+\*?\{(?:[^{}]|\\[{}])*\}', cmd_repl, text)
        
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
                return process_bold_italic(content.strip())

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
    
    def get_token_pattern(self) -> str:
        """Return regex pattern matching any token."""
        return r'@@(?:CODEBLOCK|INLINECODE|DISPLAYMATH|INLINEMATH|HEADER|LATEXCMD|IMAGE|TABLE)_\d+@@'
    
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
    token_pattern = r'@@(?:CODEBLOCK|INLINECODE|DISPLAYMATH|INLINEMATH|HEADER|LATEXCMD|IMAGE|TABLE)_\d+@@'
    
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
    
    # Bold: **text** → \textbf{text}
    # Use [^*\n]+ to avoid matching across newlines
    text = re.sub(r'\*\*([^*\n]+)\*\*', make_bold, text)
    
    # Italic: *text* → \textit{text}
    # Use [^*\n]+ to avoid matching across newlines
    text = re.sub(r'\*([^*\n]+)\*', make_italic, text)
    
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
        # Extract the image filename from the src
        image_filename = Path(src).name
        
        if chat_id:
            # Construct the path in the chat-specific images directory
            image_path = Path('history') / chat_id.replace('.json', '') / 'images' / image_filename
        else:
            # Fallback to temp directory if no chat_id provided
            image_path = Path('history/temp/images') / image_filename
            
        # Escape underscores in the path for LaTeX
        latex_path = str(image_path.resolve()).replace('_', r'\_')
        return latex_path
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
    
    # --- Step 1: Remove custom tags ---
    # Remove audio tags entirely
    content = re.sub(r'\n?<audio_file>.*?</audio_file>', '', content)
    
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

    # Tables (markdown-style) - after math/code/images so cells can contain tokens
    content = regions.protect_tables(content)
    
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

def process_inline_markup(text):
    r"""
    DEPRECATED: This function is kept for backward compatibility.
    New code should use format_message_content() which uses the unified
    ProtectedRegions tokenization system.
    
    Process inline markdown markup and convert it to raw LaTeX.
    
    This function converts:
      - Inline code (wrapped in backticks) into LaTeX verbatim text using the \verb command.
      - Headers (lines starting with 1–4 '#' characters) into the corresponding
        sectioning commands (\section*, \subsection*, etc.).
      - Bold text (wrapped in **...**) into \textbf{...}
      - Italic text (wrapped in *...*) into \textit{...}
      
    After these conversions, it detects single newline instances in non-protected regions
    (i.e. outside code blocks, inline code, or headers) and inserts explicit LaTeX forced line breaks.
    """
    import re

    # --- Step 1: Tokenize Inline Code using \verb ---
    inline_code_tokens = []
    def choose_delim(code_content):
        # Choose a delimiter that does not appear in the code snippet.
        candidates = ['|', '!', '/', ':', ';', '@', '#', '$']
        for d in candidates:
            if d not in code_content:
                return d
        return '|'  # fallback if all candidates appear

    def inline_code_token(match):
        content = match.group(1)
        token = f"@@INLINECODE_{len(inline_code_tokens)}@@"
        # Use lstinline for inline code - it handles special characters better than detokenize
        delim = choose_delim(content)
        inline_code_tokens.append(f"\\lstinline{delim}{content}{delim}")
        return token

    text = re.sub(r'`([^`]+)`', inline_code_token, text)

    # --- Step 2: Tokenize Headers ---
    headers = []
    def header_repl(match):
        level = len(match.group(1))
        title = match.group(2).strip()
        if level == 1:
            header_cmd = f"\\section*{{{title}}}"
        elif level == 2:
            header_cmd = f"\\subsection*{{{title}}}"
        elif level == 3:
            header_cmd = f"\\subsubsection*{{{title}}}"
        else:
            header_cmd = f"\\paragraph*{{{title}}}"
        token = f"@@HEADER_{len(headers)}@@"
        headers.append(header_cmd)
        return token

    text = re.sub(r'^(#{1,4})\s*(.+)$', header_repl, text, flags=re.MULTILINE)

    # --- Step 3: Process Bold and Italic Text ---
    text = re.sub(r'\*\*([^*]+)\*\*', r'\\textbf{\1}', text)
    text = re.sub(r'\*([^*]+)\*', r'\\textit{\1}', text)

    # --- Step 4: Reinstate Tokenized Inline Code and Headers ---
    for i, token_val in enumerate(inline_code_tokens):
        text = text.replace(f"@@INLINECODE_{i}@@", token_val)
    for i, token_val in enumerate(headers):
        text = text.replace(f"@@HEADER_{i}@@", token_val)

    # --- Step 5: Insert Forced Newlines in Non-Protected Segments ---
    text = insert_forced_newlines(text)
    return text

def insert_forced_newlines(text):
    """
    DEPRECATED: This function is kept for backward compatibility.
    New code should use insert_forced_newlines_safe() with a ProtectedRegions instance.
    
    Insert explicit LaTeX forced line breaks (\\\\) into non-protected text.
    
    This function splits the text by token placeholders (used for code blocks,
    inline code, and headers) and processes each plain-text chunk line-by-line.

    A forced newline (\\\\) is added only if:
      - The line is not blank,
      - It does not start with a header command (e.g. \\section*),
      - It isn't already terminated by a forced break, and
      - It is not the final line of a paragraph.

    This ensures that LaTeX won't encounter a "There's no line here to end" error.
    """
    import re

    token_pattern = r'(@@(?:CODEBLOCK|INLINECODE|HEADER)[_\d]+@@)'
    parts = re.split(token_pattern, text)
    new_parts = []
    for part in parts:
        # Skip processing if this part is a token.
        if re.fullmatch(token_pattern, part):
            new_parts.append(part)
        else:
            # Process each non-token part line-by-line.
            lines = part.split('\n')
            processed_lines = []
            for i, line in enumerate(lines):
                # If the line is blank, leave it (results in a paragraph break).
                if line.strip() == "":
                    processed_lines.append(line)
                # If the line starts with a header command, leave it as is.
                elif re.match(r'^\s*\\(section|subsection|subsubsection|paragraph)\*?\{', line):
                    processed_lines.append(line)
                # If the line already ends with a forced break, leave it.
                elif re.search(r'\\\\\s*$', line):
                    processed_lines.append(line)
                else:
                    # Only insert a forced break if it is not the last line in the chunk
                    # and the next line is not blank. This prevents inserting \\ at the end
                    # of a paragraph (which can trigger the error "There's no line here to end.")
                    if i < len(lines) - 1 and lines[i + 1].strip() != "":
                        processed_lines.append(line + r"\\")
                    else:
                        processed_lines.append(line)
            new_parts.append("\n".join(processed_lines))
    return ''.join(new_parts)

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
    """Export a chat conversation to PDF with image support."""
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
            # Updated LaTeX preamble with textcomp package and robust custom inline code macro
            latex_preamble = r"""
\documentclass{article}
\usepackage[utf8]{inputenc}
\DeclareTextSymbol{\textquotedbl}{OT1}{34}
\usepackage{geometry}
\usepackage{xcolor}
\usepackage{parskip}
\usepackage{listings}
\usepackage{fancyhdr}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{graphicx}
\usepackage{textcomp}
\usepackage[hidelinks]{hyperref}

% Handle common math symbols
\DeclareUnicodeCharacter{03A9}{\ensuremath{\Omega}}  % Ω
\DeclareUnicodeCharacter{03C0}{\ensuremath{\pi}}    % π
\DeclareUnicodeCharacter{03BC}{\ensuremath{\mu}}    % μ
\DeclareUnicodeCharacter{03B8}{\ensuremath{\theta}} % θ
\DeclareUnicodeCharacter{03B1}{\ensuremath{\alpha}} % α
\DeclareUnicodeCharacter{03B2}{\ensuremath{\beta}}  % β
\DeclareUnicodeCharacter{03B3}{\ensuremath{\gamma}} % γ
\DeclareUnicodeCharacter{03C3}{\ensuremath{\sigma}} % σ
\DeclareUnicodeCharacter{03C6}{\ensuremath{\phi}}   % φ
\DeclareUnicodeCharacter{2211}{\ensuremath{\sum}}   % ∑
\DeclareUnicodeCharacter{222B}{\ensuremath{\int}}   % ∫
\DeclareUnicodeCharacter{221E}{\ensuremath{\infty}} % ∞
\DeclareUnicodeCharacter{2248}{\ensuremath{\approx}} % ≈
\DeclareUnicodeCharacter{2260}{\ensuremath{\neq}}   % ≠
\DeclareUnicodeCharacter{2264}{\ensuremath{\leq}}   % ≤
\DeclareUnicodeCharacter{2265}{\ensuremath{\geq}}   % ≥
\DeclareUnicodeCharacter{00B1}{\ensuremath{\pm}}    % ±
\DeclareUnicodeCharacter{00D7}{\ensuremath{\times}} % ×
\DeclareUnicodeCharacter{00F7}{\ensuremath{\div}}   % ÷
\DeclareUnicodeCharacter{2192}{\ensuremath{\rightarrow}} % →
\DeclareUnicodeCharacter{2190}{\ensuremath{\leftarrow}}  % ←
\DeclareUnicodeCharacter{2194}{\ensuremath{\leftrightarrow}} % ↔
\DeclareUnicodeCharacter{2202}{\ensuremath{\partial}}    % ∂
\DeclareUnicodeCharacter{2207}{\ensuremath{\nabla}}     % ∇
\DeclareUnicodeCharacter{00B0}{\ensuremath{^{\circ}}}   % °
\DeclareUnicodeCharacter{2070}{\ensuremath{^{0}}}     % ⁰
\DeclareUnicodeCharacter{00B9}{\ensuremath{^{1}}}     % ¹
\DeclareUnicodeCharacter{00B2}{\ensuremath{^{2}}}     % ²
\DeclareUnicodeCharacter{00B3}{\ensuremath{^{3}}}     % ³
\DeclareUnicodeCharacter{2074}{\ensuremath{^{4}}}     % ⁴
\DeclareUnicodeCharacter{2075}{\ensuremath{^{5}}}     % ⁵
\DeclareUnicodeCharacter{2076}{\ensuremath{^{6}}}     % ⁶
\DeclareUnicodeCharacter{2077}{\ensuremath{^{7}}}     % ⁷
\DeclareUnicodeCharacter{2078}{\ensuremath{^{8}}}     % ⁸
\DeclareUnicodeCharacter{2079}{\ensuremath{^{9}}}     % ⁹

% Define a robust custom macro for inline code using listings' inline code command.
\DeclareRobustCommand{\inlinecode}[1]{\lstinline!#1!}

% Configure image handling
\DeclareGraphicsExtensions{.pdf,.png,.jpg,.jpeg}
\graphicspath{{./}}

\geometry{margin=1in}
\definecolor{usercolor}{RGB}{70, 130, 180}    % Steel Blue
\definecolor{assistantcolor}{RGB}{60, 179, 113}  % Medium Sea Green
\definecolor{codebg}{RGB}{40, 44, 52}          % Dark background for code
\definecolor{codetext}{RGB}{171, 178, 191}     % Light text for code

% Code listing style
\lstset{
    basicstyle=\ttfamily\small\color{codetext},
    backgroundcolor=\color{codebg},
    breaklines=true,
    frame=single,
    numbers=left,
    numberstyle=\tiny\color{codetext},
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
    resetmargins=true
}

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
            
            # Combine document parts
            full_document = latex_preamble + document_content + latex_end
            
            # Write the actual LaTeX file
            tex_file = temp_dir / "chat_export.tex"
            tex_file.write_text(full_document, encoding='utf-8')
            print(f"DEBUG: Wrote LaTeX file to {tex_file}")
            
            # Run pdflatex with detailed output
            for i in range(2):
                print(f"DEBUG: Running pdflatex iteration {i+1}")
                result = subprocess.run(
                    ['pdflatex', '-interaction=nonstopmode', str(tex_file)],
                    cwd=temp_dir,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace'
                )
                print(f"DEBUG: pdflatex return code: {result.returncode}")
                if result.returncode != 0:
                    print("DEBUG: pdflatex stdout:")
                    print(result.stdout)
                    print("DEBUG: pdflatex stderr:")
                    print(result.stderr)
                    # Save the problematic LaTeX file for inspection
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
                    return False
                    
            # Check if PDF was created
            output_pdf = temp_dir / "chat_export.pdf"
            if not output_pdf.exists():
                print("DEBUG: PDF file was not created")
                return False
            
            print(f"DEBUG: Moving PDF from {output_pdf} to {filename}")
            # Move the file
            output_path = Path(filename)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(output_pdf), filename)
            return True
            
        finally:
            # Cleanup temporary files
            shutil.rmtree(temp_dir, ignore_errors=True)
            
    except Exception as e:
        print(f"DEBUG: Exception in export_chat_to_pdf: {str(e)}")
        print("DEBUG: Exception type:", type(e))
        import traceback
        print("DEBUG: Traceback:")
        traceback.print_exc()
        return False 

def process_html_image_tags(text, chat_id=None):
    """
    Convert HTML <img> tags to proper LaTeX image inclusion commands.
    
    This function finds HTML image tags (e.g. <img src="..."/>) within the text and
    replaces them with a LaTeX snippet that centers the image using \\includegraphics.

    The image source is resolved (via process_image_path) and inserted with a width of
    \\linewidth to ensure proper scaling.
    """
    import re
    def replacement(match):
        src = match.group(1)
        # Optionally resolve the image path. If process_image_path returns None,
        # an "unavailable" notice is inserted.
        image_path = process_image_path(src, chat_id)
        if image_path:
            return r'\begin{center}\includegraphics[width=\linewidth]{' + image_path + r'}\end{center}'
        else:
            return r'\textit{[Image unavailable]}'
    # This regex matches an HTML img tag with the src attribute.
    return re.sub(r'<img\s+src="([^"]+)"\s*/?>', replacement, text) 

def escape_unprotected_hashes(text):
    """
    Escape unprotected '#' characters so that they appear literally in the final LaTeX output.
    
    Any '#' that is not already preceded by a backslash will be replaced with '\\#'
    to avoid LaTeX errors regarding macro parameter characters in horizontal mode.
    """
    import re
    # Replace any '#' that is not preceded by a backslash with '\#'
    return re.sub(r'(?<!\\)#', r'\\#', text) 
