#!/usr/bin/env python3
"""
Phase 8 Integration Test: Fix Property Inconsistencies

Tests that ChatGTK uses properties consistently for controller state access.
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))


def test_controller_has_required_attributes():
    """Test that controller has all attributes needed by UI."""
    print("Testing controller attributes...")
    
    from controller import ChatController
    
    controller = ChatController()
    
    # Check all attributes that UI accesses
    assert hasattr(controller, 'providers')
    assert hasattr(controller, 'model_provider_map')
    assert hasattr(controller, 'api_keys')
    assert hasattr(controller, 'custom_models')
    assert hasattr(controller, 'custom_providers')
    assert hasattr(controller, 'tool_manager')
    assert hasattr(controller, 'system_prompts')
    assert hasattr(controller, 'conversation_history')
    assert hasattr(controller, 'current_chat_id')
    assert hasattr(controller, 'system_message')
    assert hasattr(controller, 'active_system_prompt_id')
    print("✓ All required attributes present on controller")
    
    # Check types
    assert isinstance(controller.providers, dict)
    assert isinstance(controller.model_provider_map, dict)
    assert isinstance(controller.api_keys, dict)
    assert isinstance(controller.custom_models, dict)
    assert isinstance(controller.conversation_history, list)
    print("✓ Attribute types are correct")
    
    return True


def test_property_delegation():
    """Test that properties properly delegate to controller."""
    print("\nTesting property delegation pattern...")
    
    # We can't easily test ChatGTK without GTK, but we can verify
    # the controller side works correctly
    
    from controller import ChatController
    
    controller = ChatController()
    
    # Test that modifications work
    controller.current_chat_id = "test_chat_123"
    assert controller.current_chat_id == "test_chat_123"
    print("✓ current_chat_id setter works")
    
    controller.model_provider_map["test-model"] = "openai"
    assert "test-model" in controller.model_provider_map
    print("✓ model_provider_map is mutable")
    
    original_len = len(controller.conversation_history)
    controller.conversation_history.append({"role": "user", "content": "test"})
    assert len(controller.conversation_history) == original_len + 1
    print("✓ conversation_history is mutable")
    
    return True


def test_settings_manager_integration():
    """Test that settings are accessible via settings_manager."""
    print("\nTesting settings_manager integration...")
    
    from controller import ChatController
    
    controller = ChatController()
    
    # Access via settings_manager
    assert controller.settings_manager is not None
    print("✓ settings_manager accessible")
    
    # Get a setting
    font_size = controller.get_setting('FONT_SIZE', 12)
    assert isinstance(font_size, (int, float))
    print(f"✓ get_setting works: FONT_SIZE={font_size}")
    
    # Settings should also be on controller as attributes
    assert hasattr(controller, 'font_size')
    print("✓ Settings available as controller attributes")
    
    return True


def test_service_properties():
    """Test that services are accessible via properties."""
    print("\nTesting service properties...")
    
    from controller import ChatController
    
    controller = ChatController()
    
    # All services should be accessible
    assert controller.chat_service is not None
    assert controller.image_service is not None
    assert controller.audio_service is not None
    assert controller.tool_service is not None
    print("✓ All services accessible via properties")
    
    # Event bus should be accessible
    assert controller.event_bus is not None
    print("✓ event_bus accessible")
    
    return True


def main():
    """Run all Phase 8 tests."""
    print("=" * 60)
    print("Phase 8 Fix Property Inconsistencies Integration Test")
    print("=" * 60)
    
    tests = [
        ("Controller attributes", test_controller_has_required_attributes),
        ("Property delegation", test_property_delegation),
        ("Settings manager integration", test_settings_manager_integration),
        ("Service properties", test_service_properties),
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
        print("\n✓ All tests passed! Phase 8 integration successful.")
        return 0
    else:
        print(f"\n✗ {failed} test(s) failed.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
