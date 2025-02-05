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
        # Remove extra backslashes from #include
        code = re.sub(r'\\#include', '#include', code)
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

def format_message_content(content):
    """Format message content, handling text, code blocks, LaTeX equations, and images."""
    print("\nDEBUG: === Starting format_message_content ===")
    print(f"DEBUG: Initial content: {repr(content[:200])}")

    # Process HTML-style image tags
    content = re.sub(
        r'<img\s+src="([^"]+)"\s*/?>',
        process_image_tag,
        content,
        flags=re.DOTALL
    )

    # After content is escaped, replace the markers with actual LaTeX
    def replace_image_marker(match):
        path = match.group(1)
        return r'\begin{center}\includegraphics[max width=\linewidth]{' + path + r'}\end{center}'

    content = re.sub(
        r'__LATEX_IMAGE__(.+?)__END_LATEX_IMAGE__',
        replace_image_marker,
        content
    )

    def process_display_math(match):
        equation = match.group(1).strip()
        print(f"DEBUG: Processing display math: {repr(equation)}")
        # Remove extra backslashes and \{\} sequences
        equation = equation.replace('\\\\', '\\').replace('\\{}', '\\')
        return f"\n\\begin{{equation*}}\n{equation}\n\\end{{equation*}}\n"

    def process_inline_math(match):
        equation = match.group(1).strip()
        print(f"DEBUG: Processing inline math: {repr(equation)}")
        # Remove extra backslashes and \{\} sequences
        equation = equation.replace('\\\\', '\\').replace('\\{}', '\\')
        return f"${equation}$"

    # Then handle display math
    content = re.sub(
        r'\\\[(.*?)\\\]',
        process_display_math,
        content,
        flags=re.DOTALL
    )

    # Then handle inline math
    content = re.sub(
        r'\\\((.*?)\\\)',
        process_inline_math,
        content,
        flags=re.DOTALL
    )

    # Handle code blocks
    parts = content.split('```')
    formatted_parts = []
    
    for i, part in enumerate(parts):
        if i % 2 == 0:  # Regular text
            if part.strip():
                # Don't escape LaTeX content
                text_parts = []
                current_pos = 0
                # Find all LaTeX expressions
                latex_pattern = r'(\$.*?\$|\\begin\{equation\*\}.*?\\end\{equation\*\})'
                for match in re.finditer(latex_pattern, part, re.DOTALL):
                    # Add escaped text before the equation
                    if match.start() > current_pos:
                        text_parts.append(escape_latex_text(part[current_pos:match.start()]))
                    # Add the equation unchanged
                    text_parts.append(match.group(1))
                    current_pos = match.end()
                # Add any remaining text
                if current_pos < len(part):
                    text_parts.append(escape_latex_text(part[current_pos:]))
                formatted_parts.append(''.join(text_parts))
        else:  # Code block
            lines = part.split('\n', 1)
            language = lines[0].strip() or 'text'
            code = lines[1] if len(lines) > 1 else part
            # Don't escape the code content
            formatted_parts.append(format_code_block(code, language))

    result = '\n'.join(formatted_parts)
    print("\nDEBUG: === Final formatted content ===")
    print(repr(result[:200]))
    return result

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
            # Updated LaTeX preamble with better listings settings
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
\usepackage[hidelinks]{hyperref}

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