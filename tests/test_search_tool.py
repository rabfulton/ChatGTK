"""Tests for the search/memory tool functionality."""

import os
import sys
import json
import re
import tempfile
import pytest

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestWordBoundaryMatching:
    """Test that word boundary matching works correctly."""
    
    def test_exact_word_match(self):
        """Test that 'dog' matches 'dog' exactly."""
        pattern = re.compile(r'\b' + re.escape('dog') + r'\b', re.IGNORECASE)
        assert pattern.search("I have a dog")
        assert pattern.search("dog is here")
        assert pattern.search("The dog")
    
    def test_word_with_punctuation(self):
        """Test that 'dog' matches 'dog,' and 'dog.' but not embedded."""
        pattern = re.compile(r'\b' + re.escape('dog') + r'\b', re.IGNORECASE)
        assert pattern.search("I have a dog, and a cat")
        assert pattern.search("The dog. It barked.")
        assert pattern.search("dog's owner")
    
    def test_no_partial_match(self):
        """Test that 'dog' does NOT match 'doggedly' or 'dogma' or 'hotdog'."""
        pattern = re.compile(r'\b' + re.escape('dog') + r'\b', re.IGNORECASE)
        assert not pattern.search("She worked doggedly")
        assert not pattern.search("That's just dogma")
        assert not pattern.search("I ate a hotdog")
    
    def test_case_insensitive(self):
        """Test that matching is case-insensitive."""
        pattern = re.compile(r'\b' + re.escape('dog') + r'\b', re.IGNORECASE)
        assert pattern.search("DOG is loud")
        assert pattern.search("Dog barks")
        assert pattern.search("My DOG")


class TestSearchHistoryFiles:
    """Test the history file searching functionality."""
    
    def test_search_finds_matching_content(self, tmp_path):
        """Test that search finds matching conversation content."""
        # Create a test history file
        history_file = tmp_path / "test_chat.json"
        history_data = {
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Tell me about my dog"},
                {"role": "assistant", "content": "Your dog is a great companion!"},
            ],
            "metadata": {}
        }
        with open(history_file, 'w') as f:
            json.dump(history_data, f)
        
        # Search pattern
        pattern = re.compile(r'\b' + re.escape('dog') + r'\b', re.IGNORECASE)
        
        # Read and search
        with open(history_file, 'r') as f:
            data = json.load(f)
        
        matches = []
        for msg in data.get("messages", []):
            content = msg.get("content", "")
            role = msg.get("role", "")
            if role != "system" and pattern.search(content):
                matches.append(f"[{role}]: {content}")
        
        assert len(matches) == 2
        assert any("dog" in m.lower() for m in matches)
    
    def test_search_skips_system_messages(self, tmp_path):
        """Test that system messages are skipped during search."""
        history_file = tmp_path / "test_chat.json"
        history_data = {
            "messages": [
                {"role": "system", "content": "You are a dog expert."},
                {"role": "user", "content": "Hello"},
            ],
            "metadata": {}
        }
        with open(history_file, 'w') as f:
            json.dump(history_data, f)
        
        pattern = re.compile(r'\b' + re.escape('dog') + r'\b', re.IGNORECASE)
        
        with open(history_file, 'r') as f:
            data = json.load(f)
        
        matches = []
        for msg in data.get("messages", []):
            content = msg.get("content", "")
            role = msg.get("role", "")
            if role != "system" and pattern.search(content):
                matches.append(content)
        
        # Should not find "dog" since it's only in system message
        assert len(matches) == 0


class TestToolSpec:
    """Test that the search tool spec is properly defined."""
    
    def test_search_tool_spec_exists(self):
        """Test that SEARCH_TOOL_SPEC is defined."""
        from tools import SEARCH_TOOL_SPEC
        assert SEARCH_TOOL_SPEC is not None
        assert SEARCH_TOOL_SPEC.name == "search_memory"
    
    def test_search_tool_in_registry(self):
        """Test that search tool is in the TOOL_REGISTRY."""
        from tools import TOOL_REGISTRY
        assert "search_memory" in TOOL_REGISTRY
    
    def test_search_tool_parameters(self):
        """Test that search tool has required parameters."""
        from tools import SEARCH_TOOL_SPEC
        params = SEARCH_TOOL_SPEC.parameters
        assert "keyword" in params["properties"]
        assert "source" in params["properties"]
        assert "keyword" in params["required"]


class TestToolManager:
    """Test ToolManager integration with search tool."""
    
    def test_tool_manager_accepts_search_enabled(self):
        """Test that ToolManager accepts search_tool_enabled parameter."""
        from tools import ToolManager
        tm = ToolManager(search_tool_enabled=True)
        assert tm.search_tool_enabled is True
    
    def test_tool_manager_default_search_disabled(self):
        """Test that search tool is disabled by default."""
        from tools import ToolManager
        tm = ToolManager()
        assert tm.search_tool_enabled is False
