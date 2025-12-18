#!/usr/bin/env python3
"""
Phase 6 Integration Test: Decouple UI from Business Logic

Tests that UI components use events for communication and
the event subscription infrastructure is in place.
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))


def test_ui_base_component():
    """Test UIComponent base class."""
    print("Testing UIComponent base class...")
    
    from ui.base import UIComponent
    from events import EventBus, EventType
    
    bus = EventBus()
    received = []
    
    # Create component
    component = UIComponent(event_bus=bus)
    assert component._event_bus is bus
    print("✓ UIComponent accepts event bus")
    
    # Test subscribe
    component.subscribe(EventType.CHAT_LOADED, lambda e: received.append(e))
    assert len(component._subscriptions) == 1
    print("✓ subscribe() tracks subscriptions")
    
    # Test emit
    component.emit(EventType.CHAT_CREATED, chat_id='test123')
    # Note: This won't trigger our handler since we subscribed to CHAT_LOADED
    print("✓ emit() works")
    
    # Test cleanup
    component.cleanup()
    assert len(component._subscriptions) == 0
    print("✓ cleanup() unsubscribes all")
    
    return True


def test_history_sidebar_component():
    """Test HistorySidebar component structure."""
    print("\nTesting HistorySidebar component...")
    
    from ui import HistorySidebar
    from events import EventBus
    
    bus = EventBus()
    
    # Test creation
    sidebar = HistorySidebar(event_bus=bus)
    assert sidebar.widget is not None
    print("✓ HistorySidebar creates widget")
    
    # Test it has required elements
    assert hasattr(sidebar, 'history_list')
    assert hasattr(sidebar, 'filter_entry')
    print("✓ HistorySidebar has required UI elements")
    
    # Test refresh with mock data
    mock_histories = [
        {'filename': 'chat1.json', 'first_message': 'Hello world'},
        {'filename': 'chat2.json', 'first_message': 'Test message'},
    ]
    sidebar.refresh(mock_histories)
    
    children = sidebar.history_list.get_children()
    assert len(children) == 2
    print("✓ refresh() populates history list")
    
    # Test filtering
    sidebar._filter_text = "hello"
    sidebar.refresh(mock_histories)
    children = sidebar.history_list.get_children()
    assert len(children) == 1
    print("✓ Filtering works")
    
    # Cleanup
    sidebar.cleanup()
    
    return True


def test_event_subscriptions_exist():
    """Test that ChatGTK has event subscription infrastructure."""
    print("\nTesting event subscription infrastructure...")
    
    # We can't fully test ChatGTK without GTK display, but we can
    # verify the controller has the event bus
    from controller import ChatController
    from events import EventType
    
    controller = ChatController()
    
    # Controller should have event bus
    assert controller.event_bus is not None
    print("✓ Controller has event_bus")
    
    # Test that we can subscribe to events
    received = []
    controller.event_bus.subscribe(
        EventType.CHAT_SAVED,
        lambda e: received.append(e)
    )
    print("✓ Can subscribe to controller events")
    
    return True


def test_event_types_for_ui():
    """Test that all UI-relevant event types exist."""
    print("\nTesting UI-relevant event types...")
    
    from events import EventType
    
    ui_events = [
        'CHAT_CREATED',
        'CHAT_LOADED', 
        'CHAT_SAVED',
        'CHAT_DELETED',
        'MESSAGE_SENT',
        'MESSAGE_RECEIVED',
        'SETTINGS_CHANGED',
        'ERROR_OCCURRED',
        'THINKING_STARTED',
        'THINKING_STOPPED',
    ]
    
    for event_name in ui_events:
        assert hasattr(EventType, event_name), f"Missing {event_name}"
    
    print(f"✓ All {len(ui_events)} UI event types exist")
    
    return True


def main():
    """Run all Phase 6 tests."""
    print("=" * 60)
    print("Phase 6 Decouple UI from Business Logic Integration Test")
    print("=" * 60)
    
    tests = [
        ("UIComponent base class", test_ui_base_component),
        ("HistorySidebar component", test_history_sidebar_component),
        ("Event subscription infrastructure", test_event_subscriptions_exist),
        ("UI event types", test_event_types_for_ui),
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
        print("\n✓ All tests passed! Phase 6 integration successful.")
        return 0
    else:
        print(f"\n✗ {failed} test(s) failed.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
