"""
UI components for ChatGTK application.

This package contains GTK UI components that are decoupled from business logic.
Components communicate via the event bus.
"""

from .base import UIComponent
from .history_sidebar import HistorySidebar
from .chat_view import ChatView
from .input_panel import InputPanel
from .model_selector import ModelSelector

__all__ = ['UIComponent', 'HistorySidebar', 'ChatView', 'InputPanel', 'ModelSelector']
