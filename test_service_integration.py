#!/usr/bin/env python3
"""
Test script to verify service integration with ChatController.

This script tests that:
1. Controller initializes with services
2. Controller methods use services correctly
3. Services are accessible via controller properties
4. End-to-end workflows function properly
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from controller import ChatController
from conversation import ConversationHistory


def test_controller_initialization():
    """Test that controller initializes with all services."""
    print("Testing controller initialization...")
    
    controller = ChatController()
    
    # Check that services are accessible
    assert hasattr(controller, '_chat_service'), "Controller missing _chat_service"
    assert hasattr(controller, '_image_service'), "Controller missing _image_service"
    assert hasattr(controller, '_audio_service'), "Controller missing _audio_service"
    assert hasattr(controller, '_tool_service'), "Controller missing _tool_service"
    
    # Check that service properties work
    assert controller.chat_service is not None, "chat_service property returns None"
    assert controller.image_service is not None, "image_service property returns None"
    assert controller.audio_service is not None, "audio_service property returns None"
    assert controller.tool_service is not None, "tool_service property returns None"
    
    print("✓ Controller initialized with all services")
    return True


def test_chat_lifecycle():
    """Test chat creation, saving, and loading through controller."""
    print("\nTesting chat lifecycle...")
    
    controller = ChatController()
    
    # Create new chat
    controller.new_chat()
    assert controller.current_chat_id is None, "New chat should have no ID"
    assert len(controller.conversation_history) == 1, "New chat should have system message"
    print("✓ New chat created")
    
    # Add a message
    from conversation import create_user_message, create_assistant_message
    controller.conversation_history.append(create_user_message("Hello, test message"))
    controller.conversation_history.append(create_assistant_message("Hi there!"))
    print("✓ Messages added to conversation")
    
    # Save chat
    chat_id = controller.save_current_chat()
    assert chat_id is not None, "Failed to save chat"
    assert controller.current_chat_id == chat_id, "Chat ID not updated"
    print(f"✓ Chat saved with ID: {chat_id}")
    
    # Create new chat
    controller.new_chat()
    assert controller.current_chat_id is None, "New chat should reset ID"
    assert len(controller.conversation_history) == 1, "New chat should reset history"
    print("✓ New chat created after save")
    
    # Load saved chat
    loaded = controller.load_chat(chat_id)
    assert loaded, "Failed to load chat"
    assert controller.current_chat_id == chat_id, "Loaded chat ID mismatch"
    assert len(controller.conversation_history) == 3, "Loaded chat should have 3 messages"
    print(f"✓ Chat loaded successfully")
    
    return True


def test_service_access():
    """Test that services can be accessed and used through controller."""
    print("\nTesting service access...")
    
    controller = ChatController()
    
    # Test chat service
    chats = controller.chat_service.list_chats()
    print(f"✓ Chat service accessible - found {len(chats)} chats")
    
    # Test search
    results = controller.chat_service.search_history("test", limit=5)
    print(f"✓ Chat service search - found {len(results)} results")
    
    # Test image service
    images = controller.image_service.list_chat_images("test_chat")
    print(f"✓ Image service accessible - found {len(images)} images")
    
    # Test audio service
    audio_files = controller.audio_service.list_chat_audio("test_chat")
    print(f"✓ Audio service accessible - found {len(audio_files)} audio files")
    
    # Test tool service
    tools = controller.tool_service.get_available_tools("gpt-4")
    print(f"✓ Tool service accessible - found {len(tools)} available tools")
    
    return True


def test_message_preparation():
    """Test that message preparation still works."""
    print("\nTesting message preparation...")
    
    controller = ChatController()
    
    # Add some messages
    from conversation import create_user_message, create_assistant_message
    controller.conversation_history.append(create_user_message("First message"))
    controller.conversation_history.append(create_assistant_message("First response"))
    controller.conversation_history.append(create_user_message("Second message"))
    
    # Prepare messages for model
    messages = controller.messages_for_model("gpt-4")
    assert len(messages) > 0, "No messages prepared"
    assert messages[0]['role'] == 'system', "First message should be system"
    print(f"✓ Prepared {len(messages)} messages for model")
    
    # Test buffer limit
    limit = controller.get_conversation_buffer_limit()
    print(f"✓ Conversation buffer limit: {limit}")
    
    return True


def test_provider_management():
    """Test that provider management still works."""
    print("\nTesting provider management...")
    
    controller = ChatController()
    
    # Check providers dict exists
    assert hasattr(controller, 'providers'), "Controller missing providers dict"
    assert hasattr(controller, 'model_provider_map'), "Controller missing model_provider_map"
    print("✓ Provider management structures present")
    
    # Check API keys loaded
    assert hasattr(controller, 'api_keys'), "Controller missing api_keys"
    assert isinstance(controller.api_keys, dict), "api_keys should be dict"
    print(f"✓ API keys loaded: {len(controller.api_keys)} keys")
    
    return True


def test_tool_manager_integration():
    """Test that tool manager integrates with tool service."""
    print("\nTesting tool manager integration...")
    
    controller = ChatController()
    
    # Check tool manager exists
    assert hasattr(controller, 'tool_manager'), "Controller missing tool_manager"
    print("✓ Tool manager present")
    
    # Check tool service uses tool manager
    assert controller.tool_service._tool_manager is controller.tool_manager, \
        "Tool service should use controller's tool manager"
    print("✓ Tool service uses controller's tool manager")
    
    # Test updating tool manager
    controller.update_tool_manager()
    print("✓ Tool manager updated successfully")
    
    return True


def main():
    """Run all tests."""
    print("=" * 60)
    print("Service Integration Test")
    print("=" * 60)
    
    tests = [
        test_controller_initialization,
        test_chat_lifecycle,
        test_service_access,
        test_message_preparation,
        test_provider_management,
        test_tool_manager_integration,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"✗ Test failed: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    if failed == 0:
        print("\n✓ All tests passed! Service integration successful.")
        return 0
    else:
        print(f"\n✗ {failed} test(s) failed.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
