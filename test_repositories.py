#!/usr/bin/env python3
"""
Test script to verify Phase 1 repository integration.

This script tests that:
1. Repositories can be instantiated
2. Utils functions work with repository backends
3. ChatController works with repositories
4. Data flows correctly through the system
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from repositories import (
    SettingsRepository,
    APIKeysRepository,
    ChatHistoryRepository,
    ModelCacheRepository
)
from utils import load_settings, save_settings, load_api_keys, save_api_keys
from controller import ChatController
from conversation import ConversationHistory, create_user_message, create_assistant_message


def test_repositories_instantiation():
    """Test that all repositories can be instantiated."""
    print("Testing repository instantiation...")
    
    settings_repo = SettingsRepository()
    api_keys_repo = APIKeysRepository()
    chat_history_repo = ChatHistoryRepository()
    model_cache_repo = ModelCacheRepository()
    
    print("✓ All repositories instantiated successfully")
    return True


def test_settings_flow():
    """Test settings loading and saving through utils."""
    print("\nTesting settings flow...")
    
    # Load settings via utils (which uses repository backend)
    settings = load_settings()
    print(f"✓ Loaded {len(settings)} settings")
    
    # Check some expected settings
    assert 'SYSTEM_MESSAGE' in settings, "SYSTEM_MESSAGE not in settings"
    assert 'DEFAULT_MODEL' in settings, "DEFAULT_MODEL not in settings"
    print("✓ Expected settings present")
    
    return True


def test_api_keys_flow():
    """Test API keys loading through utils."""
    print("\nTesting API keys flow...")
    
    # Load API keys via utils (which uses repository backend)
    api_keys = load_api_keys()
    print(f"✓ Loaded API keys structure with {len(api_keys)} entries")
    
    # Check expected keys are present (even if empty)
    expected_keys = ['openai', 'gemini', 'grok', 'claude', 'perplexity']
    for key in expected_keys:
        assert key in api_keys, f"{key} not in api_keys"
    print("✓ Expected API key fields present")
    
    return True


def test_controller_with_repositories():
    """Test that ChatController works with repositories."""
    print("\nTesting ChatController with repositories...")
    
    # Create controller (will use repositories internally)
    controller = ChatController()
    
    # Check that controller loaded settings
    assert hasattr(controller, 'system_message'), "Controller missing system_message"
    assert hasattr(controller, 'default_model'), "Controller missing default_model"
    print("✓ Controller initialized with settings")
    
    # Check that controller has repositories
    assert hasattr(controller, '_settings_repo'), "Controller missing _settings_repo"
    assert hasattr(controller, '_api_keys_repo'), "Controller missing _api_keys_repo"
    assert hasattr(controller, '_chat_history_repo'), "Controller missing _chat_history_repo"
    assert hasattr(controller, '_model_cache_repo'), "Controller missing _model_cache_repo"
    print("✓ Controller has repository instances")
    
    # Check conversation history initialized
    assert len(controller.conversation_history) > 0, "Conversation history empty"
    assert controller.conversation_history[0]['role'] == 'system', "First message not system"
    print("✓ Controller conversation history initialized")
    
    return True


def test_chat_history_repository():
    """Test ChatHistoryRepository operations."""
    print("\nTesting ChatHistoryRepository...")
    
    repo = ChatHistoryRepository()
    
    # List all chats
    chats = repo.list_all()
    print(f"✓ Found {len(chats)} existing chats")
    
    # Test search (should not crash even if no results)
    results = repo.search("test", limit=5)
    print(f"✓ Search returned {len(results)} results")
    
    return True


def test_model_cache_repository():
    """Test ModelCacheRepository operations."""
    print("\nTesting ModelCacheRepository...")
    
    repo = ModelCacheRepository()
    
    # Get cached providers
    providers = repo.get_all_cached_providers()
    print(f"✓ Found {len(providers)} cached providers")
    
    # Get cache stats
    stats = repo.get_cache_stats()
    print(f"✓ Cache stats: {len(stats)} providers")
    
    return True


def main():
    """Run all tests."""
    print("=" * 60)
    print("Phase 1 Repository Integration Test")
    print("=" * 60)
    
    tests = [
        test_repositories_instantiation,
        test_settings_flow,
        test_api_keys_flow,
        test_controller_with_repositories,
        test_chat_history_repository,
        test_model_cache_repository,
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
        print("\n✓ All tests passed! Phase 1 integration successful.")
        return 0
    else:
        print(f"\n✗ {failed} test(s) failed.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
