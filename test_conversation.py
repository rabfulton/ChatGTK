#!/usr/bin/env python3
"""
Phase 7 Integration Test: Consolidate Message Creation

Tests that message creation is standardized and deprecated functions
still work for backward compatibility.
"""

import sys
import os
import warnings

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))


def test_conversation_history_methods():
    """Test ConversationHistory class methods for message creation."""
    print("Testing ConversationHistory methods...")
    
    from conversation import ConversationHistory
    
    # Create history with system message
    history = ConversationHistory(system_message="You are helpful.")
    assert len(history) == 1
    assert history[0].role == "system"
    print("✓ ConversationHistory created with system message")
    
    # Add user message
    msg = history.add_user_message("Hello", images=[{"data": "..."}])
    assert msg.role == "user"
    assert msg.content == "Hello"
    assert msg.images is not None
    assert len(history) == 2
    print("✓ add_user_message works")
    
    # Add assistant message
    msg = history.add_assistant_message("Hi there!", provider_meta={"model": "gpt-4"})
    assert msg.role == "assistant"
    assert msg.content == "Hi there!"
    assert len(history) == 3
    print("✓ add_assistant_message works")
    
    # Get first user message
    first_user = history.get_first_user_message()
    assert first_user is not None
    assert first_user.content == "Hello"
    print("✓ get_first_user_message works")
    
    # Convert to list
    msg_list = history.to_list()
    assert isinstance(msg_list, list)
    assert len(msg_list) == 3
    assert msg_list[0]["role"] == "system"
    print("✓ to_list works")
    
    return True


def test_standalone_functions_work():
    """Test that deprecated standalone functions still work."""
    print("\nTesting standalone functions (backward compatibility)...")
    
    from conversation import (
        create_system_message,
        create_user_message,
        create_assistant_message,
    )
    
    # Test create_system_message
    msg = create_system_message("System prompt")
    assert msg["role"] == "system"
    assert msg["content"] == "System prompt"
    print("✓ create_system_message works")
    
    # Test create_user_message
    msg = create_user_message("User input", images=[{"data": "base64"}])
    assert msg["role"] == "user"
    assert msg["content"] == "User input"
    assert "images" in msg
    print("✓ create_user_message works")
    
    # Test create_assistant_message
    msg = create_assistant_message("Response", provider_meta={"tokens": 100})
    assert msg["role"] == "assistant"
    assert msg["content"] == "Response"
    print("✓ create_assistant_message works")
    
    return True


def test_from_list_roundtrip():
    """Test ConversationHistory.from_list for loading saved conversations."""
    print("\nTesting from_list roundtrip...")
    
    from conversation import ConversationHistory
    
    # Create and populate history
    history = ConversationHistory("Test system")
    history.add_user_message("Question 1")
    history.add_assistant_message("Answer 1")
    history.add_user_message("Question 2", files=[{"path": "/tmp/test.pdf"}])
    
    # Convert to list (simulates saving)
    saved = history.to_list()
    
    # Recreate from list (simulates loading)
    loaded = ConversationHistory.from_list(saved)
    
    assert len(loaded) == len(history)
    assert loaded[0].content == "Test system"
    assert loaded[1].content == "Question 1"
    assert loaded[2].content == "Answer 1"
    print("✓ from_list roundtrip preserves messages")
    
    return True


def test_metadata_preserved():
    """Test that metadata is preserved through ConversationHistory."""
    print("\nTesting metadata preservation...")
    
    from conversation import ConversationHistory
    
    history = ConversationHistory("System", metadata={"title": "Test Chat"})
    assert history.metadata == {"title": "Test Chat"}
    print("✓ Metadata set on creation")
    
    # Modify metadata
    history.metadata["tags"] = ["test"]
    assert "tags" in history.metadata
    print("✓ Metadata can be modified")
    
    # from_list with metadata
    loaded = ConversationHistory.from_list(
        history.to_list(),
        metadata={"title": "Loaded Chat"}
    )
    assert loaded.metadata == {"title": "Loaded Chat"}
    print("✓ from_list accepts metadata")
    
    return True


def main():
    """Run all Phase 7 tests."""
    print("=" * 60)
    print("Phase 7 Consolidate Message Creation Integration Test")
    print("=" * 60)
    
    tests = [
        ("ConversationHistory methods", test_conversation_history_methods),
        ("Standalone functions", test_standalone_functions_work),
        ("from_list roundtrip", test_from_list_roundtrip),
        ("Metadata preservation", test_metadata_preserved),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as e:
            print(f"\n✗ {name} FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    if failed == 0:
        print("\n✓ All tests passed! Phase 7 integration successful.")
        return 0
    else:
        print(f"\n✗ {failed} test(s) failed.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
