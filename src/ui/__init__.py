"""
UI components for ChatGTK application.

This package contains GTK UI components that are decoupled from business logic.
Components communicate via the event bus.
"""

from .base import UIComponent
from .history_sidebar import HistorySidebar

__all__ = ['UIComponent', 'HistorySidebar']
