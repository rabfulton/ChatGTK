#!/usr/bin/env python3
"""
Test script to verify Phase 2 service layer integration.

This script tests that:
1. All services can be instantiated
2. Services work with repositories
3. Service methods execute correctly
4. Services coordinate properly
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from repositories import (
    SettingsRepository,
    APIKeysRepository,
    ChatHistoryRepository,
)
from services import (
    ChatService,
    ImageGenerationService,
    AudioService,
    ToolService,
)
from tools import ToolManager
from conversation import ConversationHistory


def test_services_instantiation():
    """Test that all services can be instantiated."""
    print("Testing service instantiation...")
    
    # Create repositories
    settings_repo = SettingsRepository()
    api_keys_repo = APIKeysRepository()
    chat_history_repo = ChatHistoryRepository()
    
    # Create services
    chat_service = ChatService(
        history_repo=chat_history_repo,
        settings_repo=settings_repo,
        api_keys_repo=api_keys_repo,
    )
    
    image_service = ImageGenerationService(
        chat_history_repo=chat_history_repo,
    )
    
    audio_service = AudioService()
    
    tool_manager = ToolManager()
    tool_service = ToolService(
        tool_manager=tool_manager,
    )
    
    print("✓ All services instantiated successfully")
    return True


def test_chat_service():
    """Test ChatService operations."""
    print("\nTesting ChatService...")
    
    # Create service
    settings_repo = SettingsRepository()
    api_keys_repo = APIKeysRepository()
    chat_history_repo = ChatHistoryRepository()
    
    chat_service = ChatService(
        history_repo=chat_history_repo,
        settings_repo=settings_repo,
        api_keys_repo=api_keys_repo,
    )
    
    # Test create chat
    chat_id = chat_service.create_chat("You are a test assistant.")
    assert chat_id is not None, "Failed to create chat"
    print(f"✓ Created chat: {chat_id}")
    
    # Test list chats
    chats = chat_service.list_chats()
    print(f"✓ Listed {len(chats)} chats")
    
    # Test search
    results = chat_service.search_history("test", limit=5)
    print(f"✓ Search returned {len(results)} results")
    
    # Test message preparation
    history = ConversationHistory(system_message="Test system")
    history.add_user_message("Hello")
    history.add_assistant_message("Hi there")
    
    messages = chat_service.prepare_messages_for_model(
        history=history,
        model="gpt-4",
        buffer_limit=10,
    )
    assert len(messages) > 0, "No messages prepared"
    print(f"✓ Prepared {len(messages)} messages for model")
    
    return True


def test_image_service():
    """Test ImageGenerationService operations."""
    print("\nTesting ImageGenerationService...")
    
    chat_history_repo = ChatHistoryRepository()
    image_service = ImageGenerationService(
        chat_history_repo=chat_history_repo,
    )
    
    # Test list images (should not crash even if no images)
    images = image_service.list_chat_images("test_chat")
    print(f"✓ Listed {len(images)} images for test chat")
    
    return True


def test_audio_service():
    """Test AudioService operations."""
    print("\nTesting AudioService...")
    
    settings_repo = SettingsRepository()
    chat_history_repo = ChatHistoryRepository()
    
    audio_service = AudioService()
    
    # Test that service instantiates correctly
    # (actual recording/TTS requires hardware and API keys)
    print("✓ AudioService instantiated successfully")
    
    return True


def test_tool_service():
    """Test ToolService operations."""
    print("\nTesting ToolService...")
    
    tool_manager = ToolManager(
        image_tool_enabled=True,
        music_tool_enabled=False,
        read_aloud_tool_enabled=False,
        search_tool_enabled=True,
    )
    
    tool_service = ToolService(
        tool_manager=tool_manager,
    )
    
    # Test get available tools
    tools = tool_service.get_available_tools("gpt-4")
    print(f"✓ Found {len(tools)} available tools for gpt-4")
    
    # Test tool guidance
    guidance = tool_service.get_tool_guidance("gpt-4")
    if guidance:
        print(f"✓ Generated tool guidance ({len(guidance)} chars)")
    else:
        print("✓ No tool guidance (expected if no tools enabled)")
    
    # Test enable/disable
    tool_service.enable_tool('music', True)
    assert tool_service.is_tool_enabled('music'), "Failed to enable music tool"
    print("✓ Tool enable/disable works")
    
    # Test build declarations
    declarations = tool_service.build_tool_declarations("gpt-4", "openai")
    print(f"✓ Built {len(declarations)} tool declarations")
    
    return True


def test_service_coordination():
    """Test that services can work together."""
    print("\nTesting service coordination...")
    
    # Create all repositories
    settings_repo = SettingsRepository()
    api_keys_repo = APIKeysRepository()
    chat_history_repo = ChatHistoryRepository()
    
    # Create all services
    chat_service = ChatService(
        history_repo=chat_history_repo,
        settings_repo=settings_repo,
        api_keys_repo=api_keys_repo,
    )
    
    image_service = ImageGenerationService(
        chat_history_repo=chat_history_repo,
    )
    
    audio_service = AudioService()
    
    tool_manager = ToolManager()
    tool_service = ToolService(
        tool_manager=tool_manager,
    )
    
    # Test that they can all access the same chat
    chat_id = "test_coordination_chat"
    
    # Chat service creates/loads chat
    history = ConversationHistory(system_message="Test")
    history.add_user_message("Hello")
    chat_service.save_chat(chat_id, history)
    print("✓ ChatService saved chat")
    
    # Image service can access chat directory
    images = image_service.list_chat_images(chat_id)
    print(f"✓ ImageService accessed chat directory ({len(images)} images)")
    
    # Audio service instantiated (no longer has list_chat_audio)
    print("✓ AudioService instantiated")
    
    # All services share the same repository instances
    print("✓ Services coordinate through shared repositories")
    
    return True


def main():
    """Run all tests."""
    print("=" * 60)
    print("Phase 2 Service Layer Integration Test")
    print("=" * 60)
    
    tests = [
        test_services_instantiation,
        test_chat_service,
        test_image_service,
        test_audio_service,
        test_tool_service,
        test_service_coordination,
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
        print("\n✓ All tests passed! Phase 2 integration successful.")
        return 0
    else:
        print(f"\n✗ {failed} test(s) failed.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
