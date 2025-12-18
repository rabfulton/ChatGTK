"""
Model selector UI component.

This component manages the model dropdown with display name mapping.
"""

from typing import Optional, Callable, Dict, List

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib

from .base import UIComponent
from events import EventBus, EventType


class ModelSelector(UIComponent):
    """
    Model selector dropdown component.
    
    Features:
    - Model dropdown with display name mapping
    - Reorders to put selected model first
    - Event-driven model updates
    """
    
    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        on_model_changed: Optional[Callable[[str, str], None]] = None,
    ):
        """
        Initialize the model selector.
        
        Parameters
        ----------
        event_bus : Optional[EventBus]
            Event bus for communication.
        on_model_changed : Optional[Callable[[str, str], None]]
            Callback when model changes (model_id, display_name).
        """
        super().__init__(event_bus)
        
        self._on_model_changed = on_model_changed
        self._updating = False
        
        # Mappings
        self._display_to_model_id: Dict[str, str] = {}
        self._model_id_to_display: Dict[str, str] = {}
        
        # Build UI
        self.widget = self._build_ui()
        
        # Subscribe to events
        self.subscribe(EventType.MODEL_CHANGED, self._on_model_changed_event)
        self.subscribe(EventType.MODELS_FETCHED, self._on_models_fetched_event)
    
    def _build_ui(self) -> Gtk.ComboBoxText:
        """Build the model selector UI."""
        combo = Gtk.ComboBoxText()
        combo.connect('changed', self._on_combo_changed)
        return combo
    
    def set_models(self, models: List[str], display_names: Dict[str, str] = None, active_model: str = None):
        """
        Set available models.
        
        Parameters
        ----------
        models : List[str]
            List of model IDs.
        display_names : Dict[str, str]
            Optional mapping of model_id to display name.
        active_model : str
            Model to select initially.
        """
        self._updating = True
        try:
            # Build mappings
            self._display_to_model_id = {}
            self._model_id_to_display = {}
            
            display_names = display_names or {}
            
            for model_id in models:
                display = display_names.get(model_id, model_id)
                self._display_to_model_id[display] = model_id
                self._model_id_to_display[model_id] = display
            
            # Get active display
            active_display = None
            if active_model:
                active_display = self._model_id_to_display.get(active_model, active_model)
            
            # Populate combo
            self.widget.remove_all()
            
            # Add active model first if specified
            if active_display and active_display in self._display_to_model_id:
                self.widget.append_text(active_display)
                other_displays = sorted(d for d in self._display_to_model_id.keys() if d != active_display)
            else:
                other_displays = sorted(self._display_to_model_id.keys())
            
            for display in other_displays:
                self.widget.append_text(display)
            
            if self.widget.get_model().iter_n_children(None) > 0:
                self.widget.set_active(0)
        finally:
            self._updating = False
    
    def get_selected_model_id(self) -> Optional[str]:
        """Get the selected model ID."""
        display = self.widget.get_active_text()
        if not display:
            return None
        return self._display_to_model_id.get(display, display)
    
    def get_selected_display(self) -> Optional[str]:
        """Get the selected display text."""
        return self.widget.get_active_text()
    
    def select_model(self, model_id: str):
        """Select a model by ID."""
        display = self._model_id_to_display.get(model_id, model_id)
        self._select_display(display)
    
    def _select_display(self, display: str):
        """Select by display text."""
        if self._updating:
            return
        
        model_store = self.widget.get_model()
        iter = model_store.get_iter_first()
        idx = 0
        while iter:
            if model_store.get_value(iter, 0) == display:
                self.widget.set_active(idx)
                return
            iter = model_store.iter_next(iter)
            idx += 1
    
    def _on_combo_changed(self, combo):
        """Handle combo selection change."""
        if self._updating:
            return
        
        self._updating = True
        try:
            selected_display = combo.get_active_text()
            if not selected_display:
                return
            
            selected_model_id = self._display_to_model_id.get(selected_display, selected_display)
            
            # Callback
            if self._on_model_changed:
                self._on_model_changed(selected_model_id, selected_display)
            
            # Reorder: put selected first
            model_store = combo.get_model()
            display_texts = []
            iter = model_store.get_iter_first()
            while iter:
                display_texts.append(model_store.get_value(iter, 0))
                iter = model_store.iter_next(iter)
            
            combo.remove_all()
            combo.append_text(selected_display)
            
            for display in sorted(d for d in display_texts if d != selected_display):
                combo.append_text(display)
            
            combo.set_active(0)
        finally:
            self._updating = False
    
    def _on_model_changed_event(self, event):
        """Handle MODEL_CHANGED event from elsewhere."""
        if event.source == 'ui':
            return  # Ignore our own events
        model_id = event.data.get('model_id', '')
        if model_id:
            self.schedule_ui_update(lambda: self.select_model(model_id))
    
    def _on_models_fetched_event(self, event):
        """Handle MODELS_FETCHED event."""
        # Could refresh model list here if needed
        pass
