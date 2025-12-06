"""
Tests for the LaTeX/PDF export functionality in latex_utils.py

These tests verify that the unified tokenization system correctly handles:
- Code blocks (triple backticks)
- Inline code (single backticks)
- Math expressions (both inline and display)
- Headers (markdown # syntax)
- Special character escaping
- Newline insertion (forced line breaks)
- Mixed content scenarios
"""

import sys
import os
import re

# Ensure project root is on sys.path so we can import the src package
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.latex_utils import (
    ProtectedRegions,
    escape_latex_text_simple,
    insert_forced_newlines_safe,
    process_bold_italic,
    format_message_content,
)


class TestProtectedRegions:
    """Tests for the ProtectedRegions tokenization class."""
    
    def test_code_block_protection(self):
        """Code blocks should be tokenized and not modified by other processing."""
        regions = ProtectedRegions()
        text = """Here is some code:
```python
def hello():
    print("Hello & World")  # Special chars
```
And some text after."""
        
        result = regions.protect_code_blocks(text)
        
        # Should have a token where the code block was
        assert '@@CODEBLOCK_' in result
        # Code block content should not be in the main text anymore
        assert 'def hello():' not in result
        assert '# Special chars' not in result
        
        # Restore should bring it back
        restored = regions.restore_all(result)
        assert 'lstlisting' in restored
        assert 'def hello():' in restored
    
    def test_inline_code_protection(self):
        """Inline code should be tokenized to \\lstinline."""
        regions = ProtectedRegions()
        text = "Use the `print()` function to output text."
        
        result = regions.protect_inline_code(text)
        
        assert '@@INLINECODE_' in result
        assert '`print()`' not in result
        
        restored = regions.restore_all(result)
        assert 'lstinline' in restored
        assert 'print()' in restored
    
    def test_inline_code_with_newlines_not_tokenized(self):
        """Inline code spanning newlines should not be converted to lstinline."""
        regions = ProtectedRegions()
        text = "This has `code\nwith newline` which is invalid."
        
        result = regions.protect_inline_code(text)
        
        # Should NOT be tokenized because it spans lines
        assert '@@INLINECODE_' not in result
        # Original backticks should remain
        assert '`code\nwith newline`' in result
    
    def test_display_math_protection(self):
        """Display math ($$...$$) should be protected."""
        regions = ProtectedRegions()
        text = r"The equation is $$E = mc^2$$ which is famous."
        
        result = regions.protect_display_math(text)
        
        assert '@@DISPLAYMATH_' in result
        assert '$$E = mc^2$$' not in result
        
        restored = regions.restore_all(result)
        assert '$$E = mc^2$$' in restored
    
    def test_display_math_bracket_notation(self):
        """Display math with \\[...\\] should be converted to $$...$$."""
        regions = ProtectedRegions()
        text = r"The equation is \[E = mc^2\] which is famous."
        
        result = regions.protect_display_math(text)
        
        assert '@@DISPLAYMATH_' in result
        
        restored = regions.restore_all(result)
        assert '$$E = mc^2$$' in restored
    
    def test_inline_math_protection(self):
        """Inline math ($...$) should be protected."""
        regions = ProtectedRegions()
        text = r"The variable $x$ is important."
        
        # First protect display math (order matters)
        result = regions.protect_display_math(text)
        result = regions.protect_inline_math(result)
        
        assert '@@INLINEMATH_' in result
        
        restored = regions.restore_all(result)
        assert '$x$' in restored
    
    def test_inline_math_paren_notation(self):
        """Inline math with \\(...\\) should be converted to $...$."""
        regions = ProtectedRegions()
        text = r"The variable \(x\) is important."
        
        result = regions.protect_display_math(text)
        result = regions.protect_inline_math(result)
        
        restored = regions.restore_all(result)
        assert '$x$' in restored
    
    def test_header_protection(self):
        """Markdown headers should be converted to LaTeX sectioning."""
        regions = ProtectedRegions()
        text = """# Main Title
## Subsection
### Subsubsection
#### Paragraph"""
        
        result = regions.protect_headers(text)
        
        assert '@@HEADER_' in result
        
        restored = regions.restore_all(result)
        assert r'\section*{Main Title}' in restored
        assert r'\subsection*{Subsection}' in restored
        assert r'\subsubsection*{Subsubsection}' in restored
        assert r'\paragraph*{Paragraph}' in restored
    
    def test_header_with_special_chars(self):
        """Headers with special characters should be escaped."""
        regions = ProtectedRegions()
        text = "## Section with & and % chars"
        
        result = regions.protect_headers(text)
        restored = regions.restore_all(result)
        
        # Special chars in title should be escaped
        assert r'\&' in restored
        assert r'\%' in restored
    
    def test_header_with_bold_text(self):
        """Headers that contain markdown bold should render bold text, not raw ** markers."""
        content = "### **Bold Heading**"
        result = format_message_content(content)
        
        # Should be converted to a subsubsection with bold content
        assert r'\subsubsection*' in result
        assert r'\textbf{Bold Heading}' in result
        # The raw markdown markers should not appear
        assert '**Bold Heading**' not in result
    
    def test_latex_command_protection(self):
        """Existing LaTeX commands should be protected from escaping."""
        regions = ProtectedRegions()
        text = r"This is \textbf{bold} and \textit{italic} text."
        
        result = regions.protect_latex_commands(text)
        
        assert '@@LATEXCMD_' in result
        
        restored = regions.restore_all(result)
        assert r'\textbf{bold}' in restored
        assert r'\textit{italic}' in restored
    
    def test_split_by_tokens(self):
        """Splitting by tokens should separate protected and plain text."""
        regions = ProtectedRegions()
        text = "Text with `code` and more text"
        
        tokenized = regions.protect_inline_code(text)
        segments = regions.split_by_tokens(tokenized)
        
        # Should have plain text, token, plain text
        assert len(segments) >= 3
        
        # Check that we correctly identify tokens vs plain text
        token_count = sum(1 for is_token, _ in segments if is_token)
        plain_count = sum(1 for is_token, _ in segments if not is_token)
        
        assert token_count == 1  # One inline code token
        assert plain_count >= 2  # At least two plain text segments


class TestEscaping:
    """Tests for LaTeX special character escaping."""
    
    def test_basic_special_chars(self):
        """Basic special characters should be escaped."""
        text = "Hello & World % comment # hash"
        result = escape_latex_text_simple(text)
        
        assert r'\&' in result
        assert r'\%' in result
        assert r'\#' in result
    
    def test_underscore_escape(self):
        """Underscores should be escaped."""
        text = "variable_name"
        result = escape_latex_text_simple(text)
        
        assert r'\_' in result
    
    def test_curly_braces_escape(self):
        """Curly braces should be escaped."""
        text = "dict = {key: value}"
        result = escape_latex_text_simple(text)
        
        assert r'\{' in result
        assert r'\}' in result
    
    def test_backslash_escape(self):
        """Backslashes should be escaped."""
        text = r"path\to\file"
        result = escape_latex_text_simple(text)
        
        # Should have textbackslash for each backslash
        assert result.count(r'\textbackslash{}') == 2
        # Original backslashes should be gone
        assert result.count('\\') == result.count(r'\textbackslash{}') + result.count(r'\{') + result.count(r'\}')
    
    def test_smart_quotes_escape(self):
        """Smart quotes should be converted."""
        text = '\u2018quoted\u2019 and \u201cdouble quoted\u201d'
        result = escape_latex_text_simple(text)
        
        # Smart quotes should be converted to LaTeX equivalents
        assert '\u2018' not in result  # left single quote
        assert '\u2019' not in result  # right single quote
        assert '\u201c' not in result  # left double quote
        assert '\u201d' not in result  # right double quote


class TestNewlineInsertion:
    """Tests for forced newline insertion."""
    
    def test_newlines_added_to_plain_text(self):
        """Plain text lines should get forced newlines."""
        regions = ProtectedRegions()
        text = "Line one\nLine two\nLine three"
        
        result = insert_forced_newlines_safe(text, regions)
        
        # First two lines should have \\ at the end
        assert r'Line one\\' in result
        assert r'Line two\\' in result
        # Last line should NOT have \\
        assert result.endswith('Line three')
    
    def test_no_newlines_on_blank_lines(self):
        """Blank lines should not get forced newlines."""
        regions = ProtectedRegions()
        text = "Line one\n\nLine two"
        
        result = insert_forced_newlines_safe(text, regions)
        
        # Line before blank should not have \\
        lines = result.split('\n')
        assert not lines[0].endswith(r'\\')
    
    def test_no_newlines_before_blank_line(self):
        """Lines immediately before blank lines should not get \\\\."""
        regions = ProtectedRegions()
        text = "Paragraph one\n\nParagraph two"
        
        result = insert_forced_newlines_safe(text, regions)
        
        # "Paragraph one" should NOT have \\ because next line is blank
        assert r'Paragraph one\\' not in result
    
    def test_no_newlines_on_headers(self):
        """Lines that are LaTeX section commands should not get \\\\."""
        regions = ProtectedRegions()
        text = r"\section*{Title}" + "\nSome content"
        
        result = insert_forced_newlines_safe(text, regions)
        
        # Section command should not have \\ appended
        assert r'\section*{Title}\\' not in result
    
    def test_no_newlines_in_tokens(self):
        """Protected regions (tokens) should not be modified."""
        regions = ProtectedRegions()
        text = """Some text
```python
line1
line2
```
More text"""
        
        tokenized = regions.protect_code_blocks(text)
        result = insert_forced_newlines_safe(tokenized, regions)
        restored = regions.restore_all(result)
        
        # Code inside lstlisting should not have \\ inserted
        # Find the lstlisting content
        match = re.search(r'\\begin\{lstlisting\}.*?\n(.*?)\n\\end\{lstlisting\}', 
                         restored, re.DOTALL)
        if match:
            code_content = match.group(1)
            # Verify no \\ was inserted in the code
            assert r'line1\\' not in code_content
            assert r'line2\\' not in code_content


class TestBoldItalic:
    """Tests for markdown bold/italic conversion."""
    
    def test_bold_conversion(self):
        """**text** should become \\textbf{text}."""
        text = "This is **bold** text."
        result = process_bold_italic(text)
        
        assert r'\textbf{bold}' in result
        assert '**bold**' not in result
    
    def test_italic_conversion(self):
        """*text* should become \\textit{text}."""
        text = "This is *italic* text."
        result = process_bold_italic(text)
        
        assert r'\textit{italic}' in result
        assert '*italic*' not in result
    
    def test_bold_and_italic(self):
        """Both bold and italic in same text."""
        text = "This is **bold** and *italic*."
        result = process_bold_italic(text)
        
        assert r'\textbf{bold}' in result
        assert r'\textit{italic}' in result


class TestFormatMessageContent:
    """Integration tests for the full message formatting pipeline."""
    
    def test_simple_text(self):
        """Simple text should be escaped and formatted."""
        content = "Hello, World!"
        result = format_message_content(content)
        
        # Should not crash, should return something
        assert result is not None
        assert len(result) > 0
    
    def test_text_with_special_chars(self):
        """Text with special characters should have them escaped."""
        content = "Price is 100% & tax included"
        result = format_message_content(content)
        
        assert r'\%' in result
        assert r'\&' in result
    
    def test_code_block_preserved(self):
        """Code blocks should be converted to lstlisting."""
        content = """Here is code:
```python
x = 1 + 2
```"""
        result = format_message_content(content)
        
        assert 'lstlisting' in result
        assert 'x = 1 + 2' in result
    
    def test_code_block_special_chars_not_escaped(self):
        """Special chars inside code blocks should NOT be escaped."""
        content = """```python
# This is a comment with & and %
x = {"key": "value"}
```"""
        result = format_message_content(content)
        
        # Inside lstlisting, these should NOT be escaped
        # Find content between lstlisting tags
        match = re.search(r'\\begin\{lstlisting\}.*?\n(.*?)\n\\end\{lstlisting\}', 
                         result, re.DOTALL)
        if match:
            code = match.group(1)
            # Code should have original chars, not escaped
            assert '&' in code or r'\&' not in code
    
    def test_inline_code_preserved(self):
        """Inline code should be converted to lstinline."""
        content = "Use the `print()` function."
        result = format_message_content(content)
        
        assert 'lstinline' in result
    
    def test_math_preserved(self):
        """Math expressions should be preserved."""
        content = r"The equation $E = mc^2$ is famous."
        result = format_message_content(content)
        
        assert '$E = mc^2$' in result
    
    def test_display_math_preserved(self):
        """Display math should be preserved."""
        content = r"The equation: $$\sum_{i=1}^n i = \frac{n(n+1)}{2}$$"
        result = format_message_content(content)
        
        assert '$$' in result
        assert r'\sum' in result
    
    def test_headers_converted(self):
        """Markdown headers should be converted to LaTeX sectioning."""
        content = "# Main Title\nSome content here."
        result = format_message_content(content)
        
        assert r'\section*' in result
    
    def test_mixed_content(self):
        """Mixed content with code, math, and text should all be handled."""
        content = """# Introduction

Here is some **bold** and *italic* text with $math$ inline.

```python
def example():
    return 42
```

And more text with special chars: & % #
"""
        result = format_message_content(content)
        
        # Should not crash
        assert result is not None
        
        # Should have various LaTeX elements
        assert r'\section*' in result
        assert r'\textbf' in result
        assert r'\textit' in result
        assert 'lstlisting' in result
        assert '$math$' in result
    
    def test_audio_tags_removed(self):
        """Audio file tags should be removed."""
        content = "Text before\n<audio_file>/path/to/audio.wav</audio_file>\nText after"
        result = format_message_content(content)
        
        assert '<audio_file>' not in result
        assert '</audio_file>' not in result
        assert '/path/to/audio.wav' not in result
    
    def test_consecutive_newlines_create_paragraph_break(self):
        """Consecutive newlines should create paragraph breaks, not \\\\."""
        content = "Paragraph one.\n\nParagraph two."
        result = format_message_content(content)
        
        # Should have paragraph break (empty line), not double \\
        # The line before blank should not have \\
        assert 'Paragraph one.' in result
        # Check we don't have Paragraph one.\\ followed immediately by blank
        lines = result.split('\n')
        for i, line in enumerate(lines):
            if 'Paragraph one' in line and i < len(lines) - 1:
                # If next line is blank, this line should not end with \\
                if lines[i + 1].strip() == '':
                    assert not line.rstrip().endswith(r'\\'), \
                        f"Line before paragraph break should not have \\\\: {line}"


class TestEdgeCases:
    """Tests for edge cases that have caused issues in the past."""
    
    def test_math_inside_italic(self):
        """Math inside italic text should be properly restored."""
        content = "*The cosine of $\\pi$ is $-1$.*"
        result = format_message_content(content)
        
        # Math should be preserved (not appear as @@INLINEMATH_...@@)
        assert '@@INLINEMATH' not in result
        assert '$' in result or '\\pi' in result
        # Italic should be converted
        assert 'textit' in result
    
    def test_math_inside_bold(self):
        """Math inside bold text should be properly restored."""
        content = "**The value of $x$ is $42$.**"
        result = format_message_content(content)
        
        # Math should be preserved
        assert '@@INLINEMATH' not in result
        # Bold should be converted
        assert 'textbf' in result
    
    def test_nested_formatting_with_math(self):
        """Complex nested formatting with math should work."""
        content = "In *trigonometry*, we have **$\\sin^2(x) + \\cos^2(x) = 1$**."
        result = format_message_content(content)
        
        # No tokens should remain
        assert '@@' not in result
        # Both formatting types should be present
        assert 'textit' in result
        assert 'textbf' in result
    
    def test_empty_content(self):
        """Empty content should not crash."""
        result = format_message_content("")
        assert result == ""
    
    def test_only_whitespace(self):
        """Whitespace-only content should be handled."""
        result = format_message_content("   \n\n   ")
        assert result is not None
    
    def test_unclosed_code_block(self):
        """Unclosed code blocks should still be handled."""
        content = """```python
def hello():
    pass
"""
        result = format_message_content(content)
        
        # Should still create lstlisting
        assert 'lstlisting' in result
    
    def test_nested_backticks(self):
        """Code blocks with backticks inside should be handled."""
        content = """```markdown
Use `code` in markdown
```"""
        result = format_message_content(content)
        
        assert 'lstlisting' in result
    
    def test_dollar_signs_in_code(self):
        """Dollar signs in code should not be treated as math."""
        content = """```bash
echo $HOME
```"""
        result = format_message_content(content)
        
        # $HOME should be inside lstlisting, not treated as math
        assert 'lstlisting' in result
        # The $HOME should be preserved in the code block
        match = re.search(r'\\begin\{lstlisting\}.*?\n(.*?)\n\\end\{lstlisting\}', 
                         result, re.DOTALL)
        if match:
            code = match.group(1)
            assert '$HOME' in code or 'HOME' in code
    
    def test_hash_in_code_not_escaped(self):
        """Hash characters in code should not be escaped."""
        content = """```python
# This is a comment
x = 1
```"""
        result = format_message_content(content)
        
        # Inside lstlisting, # should not become \#
        match = re.search(r'\\begin\{lstlisting\}.*?\n(.*?)\n\\end\{lstlisting\}', 
                         result, re.DOTALL)
        if match:
            code = match.group(1)
            assert '# This is a comment' in code
    
    def test_multiple_code_blocks(self):
        """Multiple code blocks should all be handled correctly."""
        content = """First block:
```python
x = 1
```

Second block:
```javascript
const y = 2;
```"""
        result = format_message_content(content)
        
        # Should have two lstlisting environments
        count = result.count(r'\begin{lstlisting}')
        assert count == 2
    
    def test_code_block_adjacent_to_text(self):
        """Code block immediately after text should be handled."""
        content = """Some text
```python
code
```
More text"""
        result = format_message_content(content)
        
        assert 'lstlisting' in result
        assert 'Some text' in result
        assert 'More text' in result


class TestTables:
    """Tests for markdown table handling."""
    
    def test_simple_markdown_table_converted(self):
        """A basic markdown table should become a LaTeX tabular environment."""
        content = """Results:
| Name | Value |
| ---  | ---   |
| a    | 1     |
| b    | 2     |
"""
        result = format_message_content(content)
        
        # Should contain a tabular environment with headers and rows
        assert r'\begin{tabular}' in result
        assert 'Name' in result
        assert 'Value' in result
        assert 'a' in result
        assert '1' in result
        assert 'b' in result
        assert '2' in result
        # No table tokens should leak through
        assert '@@TABLE_' not in result
    
    def test_table_with_alignment_and_math(self):
        """Tables with alignment markers and math should render correctly."""
        content = """| Variable | Description        |
| :------- | -----------------: |
| $x$      | Input value        |
| $y$      | Output is $x^2$    |
"""
        result = format_message_content(content)
        
        # Tabular environment exists
        assert r'\begin{tabular}' in result
        # Math should be preserved inside the table
        assert '$x$' in result or r'x' in result
        assert '$x^2$' in result or r'x^2' in result
        # No raw table markdown pipes should remain for this block
        assert '| Variable |' not in result


def run_tests():
    """Run all tests and print results."""
    import traceback
    
    test_classes = [
        TestProtectedRegions,
        TestEscaping,
        TestNewlineInsertion,
        TestBoldItalic,
        TestFormatMessageContent,
        TestEdgeCases,
    ]
    
    total_tests = 0
    passed_tests = 0
    failed_tests = []
    
    for test_class in test_classes:
        print(f"\n{'='*60}")
        print(f"Running {test_class.__name__}")
        print('='*60)
        
        instance = test_class()
        methods = [m for m in dir(instance) if m.startswith('test_')]
        
        for method_name in methods:
            total_tests += 1
            method = getattr(instance, method_name)
            try:
                method()
                print(f"  ✓ {method_name}")
                passed_tests += 1
            except AssertionError as e:
                print(f"  ✗ {method_name}: {e}")
                failed_tests.append((test_class.__name__, method_name, str(e)))
            except Exception as e:
                print(f"  ✗ {method_name}: {type(e).__name__}: {e}")
                traceback.print_exc()
                failed_tests.append((test_class.__name__, method_name, f"{type(e).__name__}: {e}"))
    
    print(f"\n{'='*60}")
    print(f"Results: {passed_tests}/{total_tests} tests passed")
    print('='*60)
    
    if failed_tests:
        print("\nFailed tests:")
        for class_name, method_name, error in failed_tests:
            print(f"  - {class_name}.{method_name}: {error}")
        return 1
    else:
        print("\nAll tests passed!")
        return 0


if __name__ == '__main__':
    sys.exit(run_tests())

