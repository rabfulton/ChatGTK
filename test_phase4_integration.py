#!/usr/bin/env python3
"""
Phase 4 Integration Test: Settings Management

Tests that the SettingsManager is properly integrated with the controller
and provides centralized settings access with event notifications.
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def test_settings_manager_basic():
    """Test basic SettingsManager functionality."""
    print("Testing SettingsManager basic operations...")
    
    from settings import SettingsManager
    from repositories import SettingsRepository
    
    repo = SettingsRepository()
    manager = SettingsManager(repository=repo)
    
    # Test get
    all_settings = manager.get_all()
    assert isinstance(all_settings, dict)
    assert len(all_settings) > 0
    print(f"✓ Loaded {len(all_settings)} settings")
    
    # Test get with default
    value = manager.get('NONEXISTENT_KEY', 'default_value')
    assert value == 'default_value'
    print("✓ get() with default works")
    
    # Test get existing
    default_model = manager.get('DEFAULT_MODEL')
    assert default_model is not None
    print(f"✓ get() existing key works: DEFAULT_MODEL={default_model}")
    
    # Test bracket notation
    assert manager['DEFAULT_MODEL'] == default_model
    print("✓ Bracket notation works")
    
    # Test contains
    assert 'DEFAULT_MODEL' in manager
    assert 'NONEXISTENT' not in manager
    print("✓ __contains__ works")
    
    # Test get_section
    tts_settings = manager.get_section('TTS_')
    assert isinstance(tts_settings, dict)
    print(f"✓ get_section('TTS_') returned {len(tts_settings)} settings")
    
    return True


def test_settings_manager_events():
    """Test that SettingsManager emits events on changes."""
    print("\nTesting SettingsManager event emission...")
    
    from settings import SettingsManager
    from repositories import SettingsRepository
    from events import EventBus, EventType
    
    bus = EventBus()
    received_events = []
    
    def capture_event(event):
        received_events.append(event)
    
    bus.subscribe(EventType.SETTINGS_CHANGED, capture_event)
    
    repo = SettingsRepository()
    manager = SettingsManager(repository=repo, event_bus=bus)
    
    # Change a setting
    old_value = manager.get('FONT_SIZE', 12)
    manager.set('FONT_SIZE', 14)
    
    # Check event was emitted
    assert len(received_events) == 1
    event = received_events[0]
    assert event.type == EventType.SETTINGS_CHANGED
    assert event.data['key'] == 'FONT_SIZE'
    assert event.data['value'] == 14
    print("✓ SETTINGS_CHANGED event emitted on set()")
    
    # Restore original value
    manager.set('FONT_SIZE', old_value)
    
    return True


def test_settings_manager_object_sync():
    """Test apply_to_object and update_from_object."""
    print("\nTesting SettingsManager object synchronization...")
    
    from settings import SettingsManager
    from repositories import SettingsRepository
    
    repo = SettingsRepository()
    manager = SettingsManager(repository=repo)
    
    # Create a mock object
    class MockObject:
        pass
    
    obj = MockObject()
    
    # Apply settings to object
    manager.apply_to_object(obj)
    
    # Check attributes were set
    assert hasattr(obj, 'default_model')
    assert hasattr(obj, 'font_size')
    print("✓ apply_to_object() sets attributes")
    
    # Modify object attribute
    original_font = obj.font_size
    obj.font_size = 999
    
    # Update manager from object
    manager.update_from_object(obj)
    
    # Check manager was updated
    assert manager.get('FONT_SIZE') == 999
    print("✓ update_from_object() reads attributes")
    
    # Restore
    manager.set('FONT_SIZE', original_font, emit_event=False)
    
    return True


def test_controller_with_settings_manager():
    """Test that controller uses SettingsManager."""
    print("\nTesting controller with SettingsManager...")
    
    from controller import ChatController
    from events import EventBus, EventType
    
    bus = EventBus()
    received_events = []
    
    bus.subscribe(EventType.SETTINGS_CHANGED, lambda e: received_events.append(e))
    
    controller = ChatController(event_bus=bus)
    
    # Check controller has settings manager
    assert hasattr(controller, '_settings_manager')
    assert controller.settings_manager is not None
    print("✓ Controller has settings_manager")
    
    # Check settings were applied as attributes
    assert hasattr(controller, 'default_model')
    print("✓ Settings applied as controller attributes")
    
    # Test get_setting
    model = controller.get_setting('DEFAULT_MODEL')
    assert model is not None
    print(f"✓ get_setting() works: {model}")
    
    # Test set_setting emits event
    old_value = controller.get_setting('FONT_SIZE', 12)
    controller.set_setting('FONT_SIZE', 16)
    
    assert len(received_events) >= 1
    print("✓ set_setting() emits SETTINGS_CHANGED event")
    
    # Check attribute was also updated
    assert controller.font_size == 16
    print("✓ set_setting() updates controller attribute")
    
    # Restore
    controller.set_setting('FONT_SIZE', old_value)
    
    return True


def test_settings_type_coercion():
    """Test that settings are coerced to correct types."""
    print("\nTesting settings type coercion...")
    
    from settings import SettingsManager
    from repositories import SettingsRepository
    
    repo = SettingsRepository()
    manager = SettingsManager(repository=repo)
    
    # Test boolean coercion
    manager.set('SIDEBAR_VISIBLE', 'true', emit_event=False)
    assert manager.get('SIDEBAR_VISIBLE') == True
    
    manager.set('SIDEBAR_VISIBLE', '0', emit_event=False)
    assert manager.get('SIDEBAR_VISIBLE') == False
    print("✓ Boolean coercion works")
    
    # Test integer coercion
    manager.set('FONT_SIZE', '14', emit_event=False)
    assert manager.get('FONT_SIZE') == 14
    assert isinstance(manager.get('FONT_SIZE'), int)
    print("✓ Integer coercion works")
    
    return True


def main():
    """Run all Phase 4 tests."""
    print("=" * 60)
    print("Phase 4 Settings Management Integration Test")
    print("=" * 60)
    
    tests = [
        ("SettingsManager basic operations", test_settings_manager_basic),
        ("SettingsManager event emission", test_settings_manager_events),
        ("SettingsManager object sync", test_settings_manager_object_sync),
        ("Controller with SettingsManager", test_controller_with_settings_manager),
        ("Settings type coercion", test_settings_type_coercion),
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
        print("\n✓ All tests passed! Phase 4 integration successful.")
        return 0
    else:
        print(f"\n✗ {failed} test(s) failed.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
