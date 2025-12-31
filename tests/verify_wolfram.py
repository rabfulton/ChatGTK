import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import unittest
from unittest.mock import MagicMock, patch
from services.wolfram_service import WolframService
from services.tool_service import ToolService
from tools import ToolManager
from controller import ChatController

class TestWolframIntegration(unittest.TestCase):
    def test_service_query(self):
        service = WolframService()
        with patch('requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = "Wolfram Result"
            mock_get.return_value = mock_response
            
            result = service.query("test query", "APP_ID")
            self.assertEqual(result, "Wolfram Result")

    def test_tool_manager_support(self):
        manager = ToolManager(wolfram_tool_enabled=True)
        self.assertTrue(manager.wolfram_tool_enabled)

    def test_tool_service_availability(self):
        manager = ToolManager(wolfram_tool_enabled=True)
        # Mock supports_tool_calling to return True
        manager.supports_tool_calling = MagicMock(return_value=True)
        
        # We removed supports_wolfram_tools, so now ToolService should likely 
        # rely on the tool enabled flag and generic tool support.
        # Let's verify that 'wolfram_alpha' is in available tools for a chat model.
        
        with patch('services.tool_service.is_chat_completion_model', return_value=True):
            service = ToolService(tool_manager=manager, wolfram_handler=lambda x: "handler")
            available = service.get_available_tools("gpt-4")
            self.assertIn("wolfram_alpha", available)

    def test_controller_handler(self):
        with patch('controller.SettingsManager') as MockSettingsManager, \
             patch('controller.SettingsRepository'), \
             patch('controller.APIKeysRepository'), \
             patch('controller.ChatHistoryRepository'), \
             patch('controller.ModelCacheRepository'), \
             patch('controller.EventBus'):
            
            mock_settings_instance = MockSettingsManager.return_value
            def get_side_effect(key, default=None):
                if key == "WOLFRAM_APP_ID":
                    return "TEST_ID"
                if key == "HIDDEN_DEFAULT_PROMPTS":
                    return "[]"
                if key == "SYSTEM_PROMPTS_JSON":
                    return "[]"
                if key in ["SYSTEM_MESSAGE", "ACTIVE_SYSTEM_PROMPT_ID"]:
                    return ""
                return default
            mock_settings_instance.get.side_effect = get_side_effect

            controller = ChatController()
            controller._wolfram_service = MagicMock()
            controller._wolfram_service.query.return_value = "Result"
            
            result = controller.handle_wolfram_tool("test")
            self.assertEqual(result, "Result")
            controller._wolfram_service.query.assert_called_with("test", "TEST_ID")

if __name__ == '__main__':
    unittest.main()
