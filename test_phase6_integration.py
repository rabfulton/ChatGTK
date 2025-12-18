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
    
    # Create a mock controller
    class MockController:
        def __init__(self):
            self.event_bus = bus
            self.chat_service = self
        
        def list_chats(self):
            return [
                {'chat_id': 'chat1', 'title': 'Hello world', 'timestamp': '2024-01-01T12:00:00'},
                {'chat_id': 'chat2', 'title': 'Test message', 'timestamp': '2024-01-02T12:00:00'},
            ]
        
        def load_chat(self, chat_id):
            return None
    
    mock_controller = MockController()
    
    # Test creation
    sidebar = HistorySidebar(event_bus=bus, controller=mock_controller)
    assert sidebar.widget is not None
    print("✓ HistorySidebar creates widget")
    
    # Test it has required elements
    assert hasattr(sidebar, 'history_list')
    assert hasattr(sidebar, 'filter_entry')
    print("✓ HistorySidebar has required UI elements")
    
    # Test refresh
    sidebar.refresh()
    children = sidebar.history_list.get_children()
    assert len(children) == 2
    print("✓ refresh() populates history list")
    
    # Test filtering
    sidebar._filter_text = "hello"
    sidebar.refresh()
    children = sidebar.history_list.get_children()
    assert len(children) == 1
    print("✓ Filtering works")
    
    # Cleanup
    sidebar.cleanup()
    
    return True


def test_chat_view_component():
    """Test ChatView component structure."""
    print("\nTesting ChatView component...")
    
    from ui import ChatView
    from events import EventBus
    
    bus = EventBus()
    
    # Test creation
    chat_view = ChatView(event_bus=bus)
    assert chat_view.widget is not None
    print("✓ ChatView creates widget")
    
    # Test it has required elements
    assert hasattr(chat_view, 'conversation_box')
    assert hasattr(chat_view, 'message_widgets')
    print("✓ ChatView has required UI elements")
    
    # Test clear
    chat_view.clear()
    assert len(chat_view.message_widgets) == 0
    print("✓ clear() works")
    
    # Cleanup
    chat_view.cleanup()
    
    return True


def test_input_panel_component():
    """Test InputPanel component structure."""
    print("\nTesting InputPanel component...")
    
    from ui import InputPanel
    from events import EventBus
    
    bus = EventBus()
    
    # Track callbacks
    submitted = []
    
    # Test creation
    panel = InputPanel(
        event_bus=bus,
        on_submit=lambda text: submitted.append(text),
    )
    assert panel.widget is not None
    print("✓ InputPanel creates widget")
    
    # Test it has required elements
    assert hasattr(panel, 'entry')
    assert hasattr(panel, 'btn_send')
    assert hasattr(panel, 'btn_voice')
    assert hasattr(panel, 'btn_attach')
    print("✓ InputPanel has required UI elements")
    
    # Test text methods
    panel.set_text("Hello")
    assert panel.get_text() == "Hello"
    panel.clear()
    assert panel.get_text() == ""
    print("✓ Text methods work")
    
    # Test recording state
    panel.set_recording_state(True)
    assert "Recording" in panel.btn_voice.get_label()
    panel.set_recording_state(False)
    assert "Start" in panel.btn_voice.get_label()
    print("✓ Recording state works")
    
    # Cleanup
    panel.cleanup()
    
    return True


def test_model_selector_component():
    """Test ModelSelector component structure."""
    print("\nTesting ModelSelector component...")
    
    from ui import ModelSelector
    from events import EventBus
    
    bus = EventBus()
    
    # Track callbacks
    changed = []
    
    # Test creation
    selector = ModelSelector(
        event_bus=bus,
        on_model_changed=lambda mid, disp: changed.append((mid, disp)),
    )
    assert selector.widget is not None
    print("✓ ModelSelector creates widget")
    
    # Test set_models
    models = ['gpt-4', 'gpt-3.5-turbo', 'claude-3']
    display_names = {'gpt-4': 'GPT-4', 'claude-3': 'Claude 3'}
    selector.set_models(models, display_names, 'gpt-4')
    
    assert selector.get_selected_model_id() == 'gpt-4'
    assert selector.get_selected_display() == 'GPT-4'
    print("✓ set_models works")
    
    # Test mappings
    assert selector._display_to_model_id.get('GPT-4') == 'gpt-4'
    assert selector._model_id_to_display.get('gpt-4') == 'GPT-4'
    print("✓ Mappings work")
    
    # Cleanup
    selector.cleanup()
    
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
        ("ChatView component", test_chat_view_component),
        ("InputPanel component", test_input_panel_component),
        ("ModelSelector component", test_model_selector_component),
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
