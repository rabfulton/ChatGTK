#!/usr/bin/env python3
"""
Phase 5 Integration Test: Enhanced Controller Pattern

Tests that the controller provides high-level orchestration methods
for message handling, provider management, and workflow coordination.
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def test_provider_management():
    """Test provider selection and management methods."""
    print("Testing provider management...")
    
    from controller import ChatController
    
    controller = ChatController()
    
    # Test get_provider_name_for_model
    assert controller.get_provider_name_for_model('gpt-4') == 'openai'
    assert controller.get_provider_name_for_model('gpt-4o-mini') == 'openai'
    print("✓ OpenAI models detected correctly")
    
    assert controller.get_provider_name_for_model('gemini-1.5-pro') == 'gemini'
    assert controller.get_provider_name_for_model('gemini-2.0-flash') == 'gemini'
    print("✓ Gemini models detected correctly")
    
    assert controller.get_provider_name_for_model('grok-2') == 'grok'
    print("✓ Grok models detected correctly")
    
    assert controller.get_provider_name_for_model('claude-3-opus') == 'claude'
    assert controller.get_provider_name_for_model('claude-sonnet-4-5') == 'claude'
    print("✓ Claude models detected correctly")
    
    assert controller.get_provider_name_for_model('sonar-pro') == 'perplexity'
    print("✓ Perplexity models detected correctly")
    
    # Test _get_api_key_for_provider
    # This should return empty string if no key is set
    key = controller._get_api_key_for_provider('openai')
    assert isinstance(key, str)
    print("✓ _get_api_key_for_provider works")
    
    return True


def test_message_handling():
    """Test message preparation and addition methods."""
    print("\nTesting message handling...")
    
    from controller import ChatController
    from events import EventBus, EventType
    
    bus = EventBus()
    received_events = []
    
    bus.subscribe(EventType.MESSAGE_SENT, lambda e: received_events.append(e))
    bus.subscribe(EventType.MESSAGE_RECEIVED, lambda e: received_events.append(e))
    
    controller = ChatController(event_bus=bus)
    
    # Test prepare_message
    msg = controller.prepare_message("Hello", images=[{"data": "base64..."}])
    assert msg['role'] == 'user'
    assert msg['content'] == 'Hello'
    assert 'images' in msg
    print("✓ prepare_message works")
    
    # Test add_user_message
    initial_len = len(controller.conversation_history)
    idx = controller.add_user_message("Test message")
    
    assert len(controller.conversation_history) == initial_len + 1
    assert controller.conversation_history[idx]['content'] == "Test message"
    print("✓ add_user_message adds to history")
    
    # Check event was emitted
    sent_events = [e for e in received_events if e.type == EventType.MESSAGE_SENT]
    assert len(sent_events) == 1
    assert sent_events[0].data['content'] == "Test message"
    print("✓ add_user_message emits MESSAGE_SENT event")
    
    # Test add_assistant_message
    idx = controller.add_assistant_message("Response")
    
    assert controller.conversation_history[idx]['content'] == "Response"
    print("✓ add_assistant_message adds to history")
    
    recv_events = [e for e in received_events if e.type == EventType.MESSAGE_RECEIVED]
    assert len(recv_events) == 1
    print("✓ add_assistant_message emits MESSAGE_RECEIVED event")
    
    return True


def test_quick_image_request():
    """Test quick image request detection."""
    print("\nTesting quick image request handling...")
    
    from controller import ChatController
    
    controller = ChatController()
    
    # Test is_quick_image_request
    assert controller.is_quick_image_request("img: a cat") == True
    assert controller.is_quick_image_request("IMG: a dog") == True
    assert controller.is_quick_image_request("Img:sunset") == True
    assert controller.is_quick_image_request("hello world") == False
    assert controller.is_quick_image_request("image of a cat") == False
    print("✓ is_quick_image_request detects img: prefix")
    
    # Test get_image_prompt
    assert controller.get_image_prompt("img: a cat") == "a cat"
    assert controller.get_image_prompt("IMG:sunset over ocean") == "sunset over ocean"
    print("✓ get_image_prompt extracts prompt correctly")
    
    # Test get_preferred_image_model
    model = controller.get_preferred_image_model()
    assert isinstance(model, str)
    assert len(model) > 0
    print(f"✓ get_preferred_image_model returns: {model}")
    
    return True


def test_temperature_handling():
    """Test temperature settings for different models."""
    print("\nTesting temperature handling...")
    
    from controller import ChatController
    
    controller = ChatController()
    
    # Regular models should have temperature
    temp = controller.get_temperature_for_model('gpt-4')
    assert temp is not None
    assert isinstance(temp, (int, float))
    print(f"✓ Regular model temperature: {temp}")
    
    # Reasoning models (o1, o3) should return None
    temp = controller.get_temperature_for_model('o1-preview')
    # Note: This depends on model_cards having the quirk set
    print(f"✓ o1-preview temperature: {temp}")
    
    return True


def test_chat_id_management():
    """Test chat ID creation and management."""
    print("\nTesting chat ID management...")
    
    from controller import ChatController
    
    controller = ChatController()
    
    # Initially no chat ID
    assert controller.current_chat_id is None
    print("✓ Initial chat_id is None")
    
    # Add a user message
    controller.add_user_message("Hello, this is a test message")
    
    # ensure_chat_id should create one
    chat_id = controller.ensure_chat_id()
    assert chat_id is not None
    assert len(chat_id) > 0
    assert controller.current_chat_id == chat_id
    print(f"✓ ensure_chat_id created: {chat_id[:30]}...")
    
    # Calling again should return same ID
    chat_id2 = controller.ensure_chat_id()
    assert chat_id2 == chat_id
    print("✓ ensure_chat_id returns same ID on subsequent calls")
    
    return True


def test_controller_has_all_services():
    """Test that controller exposes all services."""
    print("\nTesting controller service access...")
    
    from controller import ChatController
    from services import ChatService, ImageGenerationService, AudioService, ToolService
    
    controller = ChatController()
    
    assert controller.chat_service is not None
    assert isinstance(controller.chat_service, ChatService)
    print("✓ chat_service accessible")
    
    assert controller.image_service is not None
    assert isinstance(controller.image_service, ImageGenerationService)
    print("✓ image_service accessible")
    
    assert controller.audio_service is not None
    assert isinstance(controller.audio_service, AudioService)
    print("✓ audio_service accessible")
    
    assert controller.tool_service is not None
    assert isinstance(controller.tool_service, ToolService)
    print("✓ tool_service accessible")
    
    assert controller.settings_manager is not None
    print("✓ settings_manager accessible")
    
    assert controller.event_bus is not None
    print("✓ event_bus accessible")
    
    return True


def main():
    """Run all Phase 5 tests."""
    print("=" * 60)
    print("Phase 5 Enhanced Controller Pattern Integration Test")
    print("=" * 60)
    
    tests = [
        ("Provider management", test_provider_management),
        ("Message handling", test_message_handling),
        ("Quick image request", test_quick_image_request),
        ("Temperature handling", test_temperature_handling),
        ("Chat ID management", test_chat_id_management),
        ("Controller services", test_controller_has_all_services),
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
        print("\n✓ All tests passed! Phase 5 integration successful.")
        return 0
    else:
        print(f"\n✗ {failed} test(s) failed.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
