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

def escape_latex_text(text):
    """Escape special LaTeX characters in text."""
    print(f"DEBUG: Escaping text: {repr(text[:100])}...")
    
    # Don't escape if the text is already a LaTeX equation
    if text.strip().startswith('$') and text.strip().endswith('$'):
        print("DEBUG: Skipping escape for equation")
        return text
    
    if text.strip().startswith('\\begin{equation*}'):
        print("DEBUG: Skipping escape for display equation")
        return text

    if text.strip().startswith('\\begin{center}\\includegraphics'):
        print("DEBUG: Skipping escape for image")
        return text

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
        '<': r'\textless{}',
        '>': r'\textgreater{}',
        '"': "''",  # Changed to use simple quotes instead of \textquotedbl
    }
    
    result = text
    for char, escape in escapes.items():
        result = result.replace(char, escape)
    
    print(f"DEBUG: Escaped result: {repr(result[:100])}...")
    return result

def format_code_block(code, language='text'):
    """Format a code block for LaTeX using listings package."""
    # Special handling for C code
    if language.lower() == 'c':
        # Fix section commands that got into the code
        code = re.sub(r'\\section\*\{include', '#include', code)
        # Fix escaped newlines
        code = re.sub(r'\\\\n', '\\n', code)
        # Remove any \textbackslash and \{\} sequences
        code = re.sub(r'\\textbackslash\\\{\\\}n', '\\n', code)
    else:
        # Clean up the code to avoid LaTeX special character issues
        code = code.replace('\\', '\\\\')  # Escape backslashes first
        code = code.replace('#', '\\#')    # Escape hash symbols
    
    # Replace javascript with java for LaTeX compatibility
    if language.lower() == 'javascript':
        language = 'java'
    
    # For text/plaintext, don't specify a language
    if language.lower() in ['text', 'plaintext']:
        return f"""
\\begin{{lstlisting}}
{code}
\\end{{lstlisting}}
"""
    
    return f"""
\\begin{{lstlisting}}[language={language}]
{code}
\\end{{lstlisting}}
"""

def process_image_path(src):
    """Convert a source path to a full path in the images directory."""
    try:
        # Extract the image filename from the src
        image_filename = Path(src).name
        # Construct the correct path in history/temp/images
        image_path = str(Path('history/temp/images') / image_filename)
        return str(Path(image_path).resolve())
    except Exception as e:
        print(f"DEBUG: Failed to process image path: {e}")
        return None

def create_latex_image(image_path):
    """Create LaTeX command for including an image."""
    if image_path:
        return r'\begin{center}\includegraphics[width=\linewidth]{' + image_path + r'}\end{center}'
    return r'\textit{[Image unavailable]}'

def process_image_tag(match):
    """Process an image tag and convert it to LaTeX."""
    src = match.group(1)
    print(f"DEBUG: Processing image src: {src}")
    image_path = process_image_path(src)
    return create_latex_image(image_path)

def process_headers(text):
    """Process text for headers, similar to markup_utils."""
    # Handle headers (match 1-4 #s followed by text)
    def replace_header(match):
        level = len(match.group(1))  # Count the number of #
        title = match.group(2).strip()
        # Mark the LaTeX command to prevent escaping
        if level == 1:
            return f'__LATEX_CMD__\\section*{{{title}}}__END_LATEX_CMD__'
        elif level == 2:
            return f'__LATEX_CMD__\\subsection*{{{title}}}__END_LATEX_CMD__'
        elif level == 3:
            return f'__LATEX_CMD__\\subsubsection*{{{title}}}__END_LATEX_CMD__'
        else:
            return f'__LATEX_CMD__\\paragraph*{{{title}}}__END_LATEX_CMD__'
    
    # Process headers first
    text = re.sub(r'^(#{1,4})\s*(.+?)$', replace_header, text, flags=re.MULTILINE)
    
    # After all escaping is done, restore the LaTeX commands
    text = re.sub(r'__LATEX_CMD__(.+?)__END_LATEX_CMD__', r'\1', text)
    
    return text

def clean_latex_commands(text):
    """Clean up incorrectly escaped LaTeX commands."""
    # Pattern to match: \textbackslash\{\}command*\{text:\}
    pattern = r'\\textbackslash\\\{\\\}([a-zA-Z]+)\*\\\{([^}]+)\\\}'
    
    def replace_command(match):
        command = match.group(1)  # e.g., 'subsubsection'
        content = match.group(2)  # e.g., 'Explanation:'
        return f'\\{command}*{{{content}}}'
    
    return re.sub(pattern, replace_command, text)

def format_message_content(content: str) -> str:
    """
    Process a message content through markdown-like formatting for LaTeX export.
    Converts code blocks with triple backticks to raw LaTeX lstlisting blocks,
    preserving line breaks and avoiding further inline markdown processing.
    """
    import re, sys

    # --- Step 1: Tokenize code blocks so that inline processing does not affect them.
    code_blocks = []

    def codeblock_repl(match):
        language = match.group(1) or ""
        code = match.group(2)
        # Do not alter the code—the newlines and spacing are preserved as-is.
        # If no language is provided, default to printing as raw LaTeX.
        if not language:
            language = "{[LaTeX]TeX}"
        if language.lower() == 'javascript':
            language = 'java'
        # Create a raw LaTeX lstlisting environment.
        formatted = f"\n\\begin{{lstlisting}}[language={language}]\n{code}\n\\end{{lstlisting}}\n"
        token = f"@@CODEBLOCK_{len(code_blocks)}@@"
        code_blocks.append(formatted)
        return token

    # Process closed code blocks.
    pattern_closed = r"(?ms)^[ \t]*```(\w+)?\n(.*?)\n[ \t]*```[ \t]*(\n|$)"
    content = re.sub(pattern_closed, codeblock_repl, content)
    # Process any unclosed code blocks.
    pattern_unclosed = r"(?ms)^[ \t]*```(\w+)?\n(.*)$"
    content = re.sub(pattern_unclosed, codeblock_repl, content)

    # --- Step 2: Process inline math (e.g. convert \( ... \) to $...$)
    content = re.sub(r"\\\((.*?)\\\)", r'$\1$', content)

    # --- Step 3: Process inline markdown formatting (headers, bold, inline code, etc.)
    this_mod = sys.modules[__name__]
    content = this_mod.process_inline_markup(content)

    # --- Step 4: Reinsert our protected code blocks.
    for i, block in enumerate(code_blocks):
        content = content.replace(f"@@CODEBLOCK_{i}@@", block)

    # --- Step 5: Process HTML image tags.
    content = process_html_image_tags(content)
    
    # --- Step 6: (Optional) Other processing steps.
    return content

def escape_latex_inline_code(text):
    """
    Escape LaTeX special characters for inline code text.
    For inline code, we want to preserve backslashes and underscores so that
    common programming sequences like `\n` or identifiers like `my_var` appear as-is.
    """
    # Do not escape backslashes or underscores.
    replacements = {
        '&': r'\&',
        '%': r'\%',
        '$': r'\$',
        '#': r'\#',
        '{': r'\{',
        '}': r'\}',
        '~': r'\textasciitilde{}',
        '^': r'\textasciicircum{}',
    }
    for orig, repl in replacements.items():
        text = text.replace(orig, repl)
    return text

def maybe_detokenize(code_content: str) -> str:
    return f'\\detokenize{{{code_content}}}'

def process_inline_markup(text):
    """
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
        # Use a robust alternative to \verb.
        inline_code_tokens.append(f"\\texttt{{\\detokenize{{{content}}}}}")
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
    Process the text so that every single (isolated) newline outside of tokens
    is replaced with an explicit LaTeX forced break (\\), except when:
      - The line is empty (or only whitespace),
      - The line begins with a header command (e.g. \section*, \subsection*, etc.),
      - The line already ends with a forced break, or
      - The newline is at the end of the chunk (so that a paragraph break is preserved).
    
    Tokens (matching @@CODEBLOCK_x@@, @@INLINECODE_x@@, or @@HEADER_x@@) are not modified.
    
    Single newlines (i.e. a newline not immediately preceded or followed by another newline)
    in non-tokenized text are replaced with "\\\\\n" so that LaTeX forces a line break.
    """
    import re

    token_pattern = r'(@@(?:CODEBLOCK|INLINECODE|HEADER)_\d+@@)'
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

def format_chat_message(message):
    """Format a single chat message for LaTeX."""
    role = message["role"].upper()
    content = format_message_content(message["content"])
    color = 'usercolor' if role == 'USER' else 'assistantcolor'
    
    # Ensure role is properly escaped
    role = escape_latex_text(role)
    
    # Use raw string for LaTeX formatting to avoid string formatting issues
    return r"""
\noindent{\textbf{\color{%s}%s:}}

%s

\bigskip
""" % (color, role, content)

def export_chat_to_pdf(conversation, filename, title=None):
    """Export a chat conversation to PDF with image support."""
    try:
        print("\nDEBUG: === Message Contents ===")
        for i, msg in enumerate(conversation):
            print(f"\nDEBUG: Message {i} raw content:")
            print(repr(msg['content']))
        # Debug: Print initial parameters
        print("\nDEBUG: Starting PDF export")
        print(f"DEBUG: Output filename: {filename}")
        print(f"DEBUG: Title: {title}")
        print(f"DEBUG: Number of messages: {len(conversation)}")

        # Format title and date
        export_date = datetime.now().strftime("%Y-%m-%d %H:%M")
        title_section = ""
        if title:
            escaped_title = escape_latex_text(title)
            print(f"DEBUG: Escaped title: {escaped_title}")
            title_section = r"""
\begin{center}
\Large\textbf{%s}

\normalsize Generated on %s
\end{center}
\bigskip
""" % (escaped_title, export_date)
            print("DEBUG: Title section created successfully")

        # Format all messages with debug output
        messages_content = []
        for i, message in enumerate(conversation):
            if message['role'] != 'system':
                print(f"\nDEBUG: Processing message {i}")
                print(f"DEBUG: Role: {message['role']}")
                print(f"DEBUG: Content length: {len(message['content'])}")
                try:
                    formatted_message = format_chat_message(message)
                    print(f"DEBUG: Message {i} formatted successfully")
                    messages_content.append(formatted_message)
                except Exception as e:
                    print(f"DEBUG: Error formatting message {i}: {str(e)}")
                    raise

        # Debug: Print formatted messages count
        print(f"\nDEBUG: Total formatted messages: {len(messages_content)}")

        # Combine all content
        document_content = title_section + "\n".join(messages_content)
        print("\nDEBUG: Document content created")
        
        # Create temporary directory for LaTeX files
        temp_dir = Path(tempfile.mkdtemp())
        print(f"DEBUG: Created temp directory: {temp_dir}")
        
        try:
            # Updated LaTeX preamble with textcomp package and robust custom inline code macro
            latex_preamble = r"""
\documentclass{article}
\usepackage[utf8]{inputenc}
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
    escapechar=\%,
    upquote=true,
    literate={\\}{\\}1 {\ }{ }1,
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
            
            # Debug: Save a copy of the LaTeX content for inspection
            debug_tex = Path('debug_export.tex')
            debug_tex.write_text(full_document, encoding='utf-8')
            print(f"DEBUG: Saved debug LaTeX file to {debug_tex}")
            
            # Write the actual LaTeX file
            tex_file = temp_dir / "chat_export.tex"
            tex_file.write_text(full_document, encoding='utf-8')
            print("DEBUG: LaTeX file written successfully")
            
            # Run pdflatex with detailed output
            for i in range(2):
                print(f"\nDEBUG: Running pdflatex (pass {i+1})")
                result = subprocess.run(
                    ['pdflatex', '-interaction=nonstopmode', str(tex_file)],
                    cwd=temp_dir,
                    capture_output=True,
                    text=True
                )
                if result.returncode != 0:
                    print("DEBUG: pdflatex error output:")
                    print(result.stdout)
                    print(result.stderr)
                    
                    # Save the problematic LaTeX file for inspection
                    debug_file = Path('debug_failed.tex')
                    debug_file.write_text(full_document, encoding='utf-8')
                    print(f"DEBUG: Saved failing LaTeX to {debug_file}")
                    return False
                    
                print(f"DEBUG: pdflatex pass {i+1} completed successfully")
            
            # Check if PDF was created
            output_pdf = temp_dir / "chat_export.pdf"
            if not output_pdf.exists():
                print("DEBUG: PDF file was not created")
                return False
            
            # Move the file
            output_path = Path(filename)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(output_pdf), filename)
            print(f"DEBUG: PDF moved to final location: {filename}")
            return True
            
        finally:
            # Cleanup temporary files
            print("\nDEBUG: Cleaning up temporary files")
            shutil.rmtree(temp_dir, ignore_errors=True)
            
    except Exception as e:
        print(f"DEBUG: Exception in export_chat_to_pdf: {str(e)}")
        print("DEBUG: Exception type:", type(e))
        import traceback
        print("DEBUG: Traceback:")
        traceback.print_exc()
        return False 

def process_html_image_tags(text):
    """
    Convert HTML <img> tags to LaTeX \includegraphics commands.
    
    This function searches the text for HTML image tags (e.g. <img src="..."/>)
    and converts them into LaTeX image inclusion commands. It uses the process_image_path
    function (if available) to resolve the full path.
    """
    import re
    def replacement(match):
        src = match.group(1)
        # Optionally resolve the image path. If process_image_path returns None,
        # an "unavailable" notice is inserted.
        image_path = process_image_path(src)
        if image_path:
            return r'\begin{center}\includegraphics[width=\linewidth]{' + image_path + r'}\end{center}'
        else:
            return r'\textit{[Image unavailable]}'
    # This regex matches an HTML img tag with the src attribute.
    return re.sub(r'<img\s+src="([^"]+)"\s*/?>', replacement, text) 