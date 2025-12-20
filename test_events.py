#!/usr/bin/env python3
"""
Phase 3 Integration Test: Event System

Tests that the event system is properly integrated with services and controller.
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def test_event_system_infrastructure():
    """Test basic event system functionality."""
    print("Testing event system infrastructure...")
    
    from events import EventBus, EventType, Event, get_event_bus
    
    # Test EventBus creation
    bus = EventBus()
    assert bus is not None
    print("✓ EventBus created")
    
    # Test subscription and publishing
    received_events = []
    
    def handler(event):
        received_events.append(event)
    
    bus.subscribe(EventType.CHAT_CREATED, handler)
    bus.publish(Event(type=EventType.CHAT_CREATED, data={'chat_id': 'test123'}, source='test'))
    
    assert len(received_events) == 1
    assert received_events[0].data['chat_id'] == 'test123'
    print("✓ Event subscription and publishing works")
    
    # Test unsubscribe
    bus.unsubscribe(EventType.CHAT_CREATED, handler)
    bus.publish(Event(type=EventType.CHAT_CREATED, data={'chat_id': 'test456'}, source='test'))
    
    assert len(received_events) == 1  # Should not have received second event
    print("✓ Event unsubscription works")
    
    # Test global event bus
    global_bus = get_event_bus()
    assert global_bus is not None
    global_bus2 = get_event_bus()
    assert global_bus is global_bus2  # Should be same instance
    print("✓ Global event bus singleton works")
    
    return True


def test_services_have_event_bus():
    """Test that services accept and use event bus."""
    print("\nTesting services with event bus...")
    
    from events import EventBus, EventType
    from repositories import ChatHistoryRepository, SettingsRepository, APIKeysRepository
    from services import ChatService, ImageGenerationService, AudioService, ToolService
    from tools import ToolManager
    
    bus = EventBus()
    received_events = []
    
    def capture_event(event):
        received_events.append(event)
    
    # Subscribe to various events
    bus.subscribe(EventType.CHAT_CREATED, capture_event)
    bus.subscribe(EventType.CHAT_SAVED, capture_event)
    bus.subscribe(EventType.CHAT_LOADED, capture_event)
    bus.subscribe(EventType.TOOL_EXECUTED, capture_event)
    
    # Create services with event bus
    history_repo = ChatHistoryRepository()
    settings_repo = SettingsRepository()
    api_keys_repo = APIKeysRepository()
    
    chat_service = ChatService(
        history_repo=history_repo,
        settings_repo=settings_repo,
        api_keys_repo=api_keys_repo,
        event_bus=bus,
    )
    assert chat_service._event_bus is bus
    print("✓ ChatService accepts event bus")
    
    image_service = ImageGenerationService(
        chat_history_repo=history_repo,
        event_bus=bus,
    )
    assert image_service._event_bus is bus
    print("✓ ImageGenerationService accepts event bus")
    
    audio_service = AudioService(event_bus=bus)
    assert audio_service._event_bus is bus
    print("✓ AudioService accepts event bus")
    
    tool_manager = ToolManager()
    tool_service = ToolService(
        tool_manager=tool_manager,
        event_bus=bus,
    )
    assert tool_service._event_bus is bus
    print("✓ ToolService accepts event bus")
    
    # Test that ChatService emits events
    chat_id = chat_service.create_chat("Test system message")
    
    # Check if CHAT_CREATED event was emitted
    chat_created_events = [e for e in received_events if e.type == EventType.CHAT_CREATED]
    assert len(chat_created_events) == 1
    assert chat_created_events[0].data['chat_id'] == chat_id
    print("✓ ChatService emits CHAT_CREATED event")
    
    return True


def test_controller_with_event_bus():
    """Test that controller initializes with event bus."""
    print("\nTesting controller with event bus...")
    
    from events import EventBus, EventType
    from controller import ChatController
    
    # Test with custom event bus
    custom_bus = EventBus()
    controller = ChatController(event_bus=custom_bus)
    
    assert controller._event_bus is custom_bus
    assert controller.event_bus is custom_bus
    print("✓ Controller accepts custom event bus")
    
    # Test services have the event bus
    assert controller._chat_service._event_bus is custom_bus
    assert controller._image_service._event_bus is custom_bus
    assert controller._audio_service._event_bus is custom_bus
    assert controller._tool_service._event_bus is custom_bus
    print("✓ Controller passes event bus to all services")
    
    # Test with default event bus
    controller2 = ChatController()
    assert controller2._event_bus is not None
    print("✓ Controller uses global event bus by default")
    
    return True


def test_event_types_coverage():
    """Test that all expected event types exist."""
    print("\nTesting event types coverage...")
    
    from events import EventType
    
    expected_types = [
        'CHAT_CREATED', 'CHAT_LOADED', 'CHAT_SAVED', 'CHAT_DELETED',
        'MESSAGE_SENT', 'MESSAGE_RECEIVED', 'MESSAGE_STREAMING',
        'MODELS_FETCHED', 'MODEL_CHANGED',
        'SETTINGS_CHANGED', 'API_KEY_UPDATED',
        'TOOL_EXECUTED', 'TOOL_RESULT',
        'RECORDING_STARTED', 'RECORDING_STOPPED', 'TRANSCRIPTION_COMPLETE',
        'PLAYBACK_STARTED', 'PLAYBACK_STOPPED', 'TTS_COMPLETE',
        'IMAGE_GENERATED', 'IMAGE_EDITED',
        'ERROR_OCCURRED',
        'THINKING_STARTED', 'THINKING_STOPPED',
    ]
    
    for type_name in expected_types:
        assert hasattr(EventType, type_name), f"Missing EventType.{type_name}"
    
    print(f"✓ All {len(expected_types)} expected event types exist")
    
    return True


def test_thread_safety():
    """Test that event bus is thread-safe."""
    print("\nTesting thread safety...")
    
    import threading
    from events import EventBus, EventType, Event
    
    bus = EventBus()
    received_count = [0]
    lock = threading.Lock()
    
    def handler(event):
        with lock:
            received_count[0] += 1
    
    bus.subscribe(EventType.MESSAGE_SENT, handler)
    
    # Publish from multiple threads
    threads = []
    for i in range(10):
        t = threading.Thread(
            target=lambda: bus.publish(Event(type=EventType.MESSAGE_SENT, data={}, source='test'))
        )
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
    
    assert received_count[0] == 10
    print("✓ Event bus handles concurrent publishing")
    
    return True


def main():
    """Run all Phase 3 tests."""
    print("=" * 60)
    print("Phase 3 Event System Integration Test")
    print("=" * 60)
    
    tests = [
        ("Event system infrastructure", test_event_system_infrastructure),
        ("Services with event bus", test_services_have_event_bus),
        ("Controller with event bus", test_controller_with_event_bus),
        ("Event types coverage", test_event_types_coverage),
        ("Thread safety", test_thread_safety),
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
        print("\n✓ All tests passed! Phase 3 integration successful.")
        return 0
    else:
        print(f"\n✗ {failed} test(s) failed.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
