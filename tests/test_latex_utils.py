import os
import tempfile
import unittest
from pathlib import Path

from latex_utils import (
    escape_latex_text,
    format_code_block,
    process_inline_markup,
    format_message_content,
    format_chat_message,
    export_chat_to_pdf,
    tex_to_png,
    is_latex_installed
)

class TestLatexUtils(unittest.TestCase):

    def test_escape_latex_text(self):
        # Test escaping of special characters.
        text = "50% discount on #1 product & more"
        escaped = escape_latex_text(text)
        # Expect special characters to be escaped.
        self.assertIn(r'\%', escaped)
        self.assertIn(r'\#', escaped)
        self.assertIn(r'\&', escaped)
        # Ensure already formatted LaTeX content is not re-escaped.
        latex_equation = "$E=mc^2$"
        self.assertEqual(escape_latex_text(latex_equation), latex_equation)

    def test_format_code_block(self):
        # Test that code blocks are correctly wrapped.
        code = "def foo():\n    return 'bar'\n"
        formatted = format_code_block(code, language='python')
        self.assertIn(r'\begin{lstlisting}[language=python]', formatted)
        self.assertIn("def foo():", formatted)
        self.assertIn(r'\end{lstlisting}', formatted)

    def test_process_inline_markup(self):
        # Test header conversion and inline code transformation.
        text = "# Header Title\nThis is **bold text** and here is `inline_code`."
        processed = process_inline_markup(text)
        self.assertIn(r'\section*{Header Title}', processed)
        self.assertIn(r'\textbf{bold text}', processed)
        self.assertIn(r'\texttt{inline_code}', processed)

    def test_format_message_content_plain_text(self):
        # Test processing plain text through format_message_content.
        text = "This is a simple message."
        formatted = format_message_content(text)
        self.assertIn("This is a simple message.", formatted)

    def test_format_chat_message(self):
        # Test that a single chat message is properly formatted.
        message = {"role": "user", "content": "Hello, world!"}
        formatted = format_chat_message(message)
        # Check that the role is transformed to uppercase and the message is included.
        self.assertIn("USER:", formatted)
        self.assertIn("Hello, world!", formatted)

    def test_problematic_message_with_nested_delimiter(self):
        """
        Test a message that contains a code block with nested triple backticks.
        This simulates a case where code includes literal backticks that must not be
        misinterpreted as terminating the code environment.
        """
        problematic = (
            "Here is a code snippet with nested backticks:\n"
            "```python\n"
            "def tricky():\n"
            "    # This is tricky: ```\n"
            "    print('Hello')\n"
            "```\n"
            "Normal text after code."
        )
        formatted = format_message_content(problematic)
        # Check that we correctly convert the code block to a lstlisting environment.
        self.assertIn(r'\begin{lstlisting}[language=python]', formatted)
        self.assertIn("def tricky():", formatted)
        self.assertIn(r'\end{lstlisting}', formatted)
        # Ensure that raw markdown code fences are not present.
        self.assertNotIn("```", formatted)

    def test_problematic_unclosed_code_block(self):
        """
        Test a message with an unclosed code block delimiter.
        Even if the closing delimiter is missing, the formatter should not crash,
        and it should produce output containing the available code.
        """
        problematic = (
            "This message has an unclosed code block:\n"
            "```python\n"
            "def broken_code():\n"
            "    print('Oops!')\n"
            "And some more text afterwards."
        )
        formatted = format_message_content(problematic)
        # At least the function should capture the code and return a proper string.
        self.assertIn("def broken_code():", formatted)
        self.assertTrue(isinstance(formatted, str) and len(formatted) > 0)

    def test_problematic_message_full(self):
        """
        Test a multi-problematic message which includes:
          - A code block that contains nested backticks
          - An inline math expression that is missing the closing delimiter

        This tests that the formatter can gracefully process mixed and malformed content.
        """
        problematic = (
            "This message is problematic:\n"
            "It starts a code block with mixed content:\n"
            "```python\n"
            "def messy():\n"
            "    # Beware of delimiters: ``` and \\( E=mc^2 \n"
            "    print('Check this out')\n"
            "```\n"
            "And then an inline math with missing end: \\( a+b\n"
        )
        formatted = format_message_content(problematic)
        # Check that the code block was processed into a lstlisting environment.
        self.assertIn(r'\begin{lstlisting}[language=python]', formatted)
        self.assertIn(r'\end{lstlisting}', formatted)
        self.assertIn("def messy():", formatted)
        # Even though the inline math is missing its closing delimiter, the text should still appear.
        self.assertIn("a+b", formatted)

    @unittest.skipUnless(is_latex_installed(), "LaTeX not installed. Skipping tex_to_png test.")
    def test_tex_to_png(self):
        # Test converting a TeX string to PNG.
        png_data = tex_to_png("E=mc^2", is_display_math=False, text_color="#000000")
        self.assertIsNotNone(png_data)
        self.assertIsInstance(png_data, bytes)

    @unittest.skipUnless(is_latex_installed(), "LaTeX not installed. Skipping PDF export test.")
    def test_export_chat_to_pdf(self):
        # Test exporting a minimal chat conversation to a PDF.
        conversation = [
            {"role": "user", "content": "Hello, this is a test message."},
            {"role": "assistant", "content": "Hi! Here is some code:\n```python\ndef test():\n    return 'pass'\n```"},
            {"role": "user", "content": "And here is an inline equation: \\(E=mc^2\\)."}
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "test_export.pdf"
            result = export_chat_to_pdf(conversation, str(pdf_path), title="Unit Test Export")
            self.assertTrue(result)
            self.assertTrue(pdf_path.exists())

if __name__ == '__main__':
    unittest.main() 