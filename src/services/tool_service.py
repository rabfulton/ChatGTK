"""
Tool service for coordinating tool execution and management.
"""

from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass

from tools import (
    ToolManager,
    run_tool_call,
    ToolContext,
    is_chat_completion_model,
    append_tool_guidance,
)
from events import EventBus, EventType, Event


@dataclass
class ToolExecutionResult:
    """Result from tool execution."""
    success: bool
    result: str
    tool_name: str
    error: Optional[str] = None


class ToolService:
    """
    Service for managing tool execution and coordination.
    
    This service provides a high-level interface for tool management,
    coordinating between different tool handlers and managing tool
    availability based on model capabilities.
    """
    
    def __init__(
        self,
        tool_manager: ToolManager,
        image_handler: Optional[Callable] = None,
        music_handler: Optional[Callable] = None,
        read_aloud_handler: Optional[Callable] = None,
        search_handler: Optional[Callable] = None,
        memory_handler: Optional[Callable] = None,
        text_get_handler: Optional[Callable] = None,
        text_edit_handler: Optional[Callable] = None,
        event_bus: Optional[EventBus] = None,
        settings_manager=None,
    ):
        """
        Initialize the tool service.
        
        Parameters
        ----------
        tool_manager : ToolManager
            The tool manager instance.
        image_handler : Optional[Callable]
            Handler for image generation tool.
        music_handler : Optional[Callable]
            Handler for music control tool.
        read_aloud_handler : Optional[Callable]
            Handler for read aloud tool.
        search_handler : Optional[Callable]
            Handler for search/memory tool.
        memory_handler : Optional[Callable]
            Handler for semantic memory retrieval tool.
        event_bus : Optional[EventBus]
            Event bus for publishing events.
        settings_manager : Optional[SettingsManager]
            Optional settings manager for centralized reads.
        """
        self._tool_manager = tool_manager
        self._handlers = {
            'image': image_handler,
            'music': music_handler,
            'read_aloud': read_aloud_handler,
            'search': search_handler,
            'memory': memory_handler,
            'text_get': text_get_handler,
            'text_edit': text_edit_handler,
        }
        self._event_bus = event_bus
        self._settings_manager = settings_manager
    
    def _emit(self, event_type: EventType, **data) -> None:
        """Emit an event if event bus is configured."""
        if self._event_bus:
            self._event_bus.publish(Event(type=event_type, data=data, source='tool_service'))
    
    def execute_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        chat_id: Optional[str] = None,
    ) -> ToolExecutionResult:
        """
        Execute a tool with the given arguments.
        
        Parameters
        ----------
        tool_name : str
            The name of the tool to execute.
        args : Dict[str, Any]
            Arguments for the tool.
        chat_id : Optional[str]
            The chat ID for context.
            
        Returns
        -------
        ToolExecutionResult
            The result of tool execution.
        """
        self._emit(EventType.TOOL_EXECUTED, tool_name=tool_name, args=args, chat_id=chat_id)
        
        try:
            # Create tool context
            context = ToolContext(
                image_handler=self._handlers.get('image'),
                music_handler=self._handlers.get('music'),
                read_aloud_handler=self._handlers.get('read_aloud'),
                search_handler=self._handlers.get('search'),
                memory_handler=self._handlers.get('memory'),
                text_get_handler=self._handlers.get('text_get'),
                text_edit_handler=self._handlers.get('text_edit'),
            )
            
            # Execute tool
            result = run_tool_call(tool_name, args, context)
            
            self._emit(EventType.TOOL_RESULT, tool_name=tool_name, success=True, result=result[:200] if result else '')
            
            return ToolExecutionResult(
                success=True,
                result=result,
                tool_name=tool_name,
            )
            
        except Exception as e:
            self._emit(EventType.TOOL_RESULT, tool_name=tool_name, success=False, error=str(e))
            return ToolExecutionResult(
                success=False,
                result='',
                tool_name=tool_name,
                error=str(e),
            )
    
    def get_available_tools(self, model: str) -> List[str]:
        """
        Get list of available tools for a model.
        
        Parameters
        ----------
        model : str
            The model identifier.
            
        Returns
        -------
        List[str]
            List of available tool names.
        """
        available = []
        
        # Check if model supports tools
        if not is_chat_completion_model(model):
            return available
        
        # Check each tool's availability
        if self._tool_manager.image_tool_enabled and self._handlers.get('image'):
            available.append('generate_image')
        
        if self._tool_manager.music_tool_enabled and self._handlers.get('music'):
            available.append('control_music')
        
        if self._tool_manager.read_aloud_tool_enabled and self._handlers.get('read_aloud'):
            available.append('read_aloud')
        
        if self._tool_manager.search_tool_enabled and self._handlers.get('search'):
            available.append('search_memory')
        
        if self._tool_manager.text_edit_tool_enabled and self._handlers.get('text_get'):
            available.append('text_get')
        
        if self._tool_manager.text_edit_tool_enabled and self._handlers.get('text_edit'):
            available.append('apply_text_edit')
        
        return available
    
    def build_tool_declarations(self, model: str, provider: str) -> List[Dict]:
        """
        Build tool declarations for a model and provider.
        
        Parameters
        ----------
        model : str
            The model identifier.
        provider : str
            The provider name.
            
        Returns
        -------
        List[Dict]
            List of tool declaration dictionaries.
        """
        # Import the builder function from tools module
        from tools import build_tools_for_provider
        
        # Get enabled tools
        enabled_tools = set()
        if self._tool_manager.image_tool_enabled:
            enabled_tools.add('image')
        if self._tool_manager.music_tool_enabled:
            enabled_tools.add('music')
        if self._tool_manager.read_aloud_tool_enabled:
            enabled_tools.add('read_aloud')
        if self._tool_manager.search_tool_enabled:
            enabled_tools.add('search')
        if self._tool_manager.text_edit_tool_enabled:
            enabled_tools.add('text_get')
            enabled_tools.add('apply_text_edit')
        
        if not enabled_tools:
            return []
        
        return build_tools_for_provider(enabled_tools, provider)
    
    def get_tool_guidance(self, model: str) -> Optional[str]:
        """
        Get tool guidance text for a model.
        
        Parameters
        ----------
        model : str
            The model identifier.
            
        Returns
        -------
        Optional[str]
            Tool guidance text, or None if no tools available.
        """
        available_tools = self.get_available_tools(model)
        if not available_tools:
            return None
        
        # Build guidance text
        guidance_parts = []
        
        if 'generate_image' in available_tools:
            guidance_parts.append(
                "You can generate images using the generate_image tool. "
                "Call it with a detailed prompt describing the image to create."
            )
        
        if 'control_music' in available_tools:
            guidance_parts.append(
                "You can control music playback using the control_music tool. "
                "Available actions: play, pause, next, previous, volume."
            )
        
        if 'read_aloud' in available_tools:
            guidance_parts.append(
                "You can read text aloud using the read_aloud tool. "
                "Pass the text you want to be spoken."
            )
        
        if 'search_memory' in available_tools:
            guidance_parts.append(
                "You can search chat history using the search_memory tool. "
                "Provide a keyword and optionally specify 'current' or 'history' as the source."
            )
        
        return "\n\n".join(guidance_parts) if guidance_parts else None
    
    def append_tool_guidance_to_system(
        self,
        system_message: str,
        model: str,
    ) -> str:
        """
        Append tool guidance to a system message.
        
        Parameters
        ----------
        system_message : str
            The original system message.
        model : str
            The model identifier.
            
        Returns
        -------
        str
            System message with tool guidance appended.
        """
        guidance = self.get_tool_guidance(model)
        if guidance:
            return append_tool_guidance(
                system_message,
                guidance,
                settings_manager=self._settings_manager
            )
        return system_message
    
    def update_handlers(
        self,
        image_handler: Optional[Callable] = None,
        music_handler: Optional[Callable] = None,
        read_aloud_handler: Optional[Callable] = None,
        search_handler: Optional[Callable] = None,
    ) -> None:
        """
        Update tool handlers.
        
        Parameters
        ----------
        image_handler : Optional[Callable]
            New image handler (None to keep existing).
        music_handler : Optional[Callable]
            New music handler (None to keep existing).
        read_aloud_handler : Optional[Callable]
            New read aloud handler (None to keep existing).
        search_handler : Optional[Callable]
            New search handler (None to keep existing).
        """
        if image_handler is not None:
            self._handlers['image'] = image_handler
        if music_handler is not None:
            self._handlers['music'] = music_handler
        if read_aloud_handler is not None:
            self._handlers['read_aloud'] = read_aloud_handler
        if search_handler is not None:
            self._handlers['search'] = search_handler
    
    def enable_tool(self, tool_name: str, enabled: bool = True) -> None:
        """
        Enable or disable a tool.
        
        Parameters
        ----------
        tool_name : str
            The tool name ('image', 'music', 'read_aloud', 'search').
        enabled : bool
            Whether to enable the tool.
        """
        if tool_name == 'image':
            self._tool_manager.image_tool_enabled = enabled
        elif tool_name == 'music':
            self._tool_manager.music_tool_enabled = enabled
        elif tool_name == 'read_aloud':
            self._tool_manager.read_aloud_tool_enabled = enabled
        elif tool_name == 'search':
            self._tool_manager.search_tool_enabled = enabled
        elif tool_name == 'text_edit':
            self._tool_manager.text_edit_tool_enabled = enabled
    
    def is_tool_enabled(self, tool_name: str) -> bool:
        """
        Check if a tool is enabled.
        
        Parameters
        ----------
        tool_name : str
            The tool name.
            
        Returns
        -------
        bool
            True if enabled, False otherwise.
        """
        if tool_name == 'image':
            return self._tool_manager.image_tool_enabled
        elif tool_name == 'music':
            return self._tool_manager.music_tool_enabled
        elif tool_name == 'read_aloud':
            return self._tool_manager.read_aloud_tool_enabled
        elif tool_name == 'search':
            return self._tool_manager.search_tool_enabled
        elif tool_name == 'text_edit':
            return self._tool_manager.text_edit_tool_enabled
        return False

    # -------------------------------------------------------------------------
    # Model capability checks (delegated to ToolManager)
    # -------------------------------------------------------------------------

    def is_image_model(self, model_name: str, provider_name: str, custom_models: Optional[Dict] = None) -> bool:
        """Check if a model is an image generation model."""
        return self._tool_manager.is_image_model_for_provider(model_name, provider_name, custom_models)

    def supports_image_tools(self, model_name: str, model_provider_map: Optional[Dict] = None, custom_models: Optional[Dict] = None) -> bool:
        """Check if a model supports image tools."""
        return self._tool_manager.supports_image_tools(model_name, model_provider_map, custom_models)

    def supports_music_tools(self, model_name: str, model_provider_map: Optional[Dict] = None, custom_models: Optional[Dict] = None) -> bool:
        """Check if a model supports music tools."""
        return self._tool_manager.supports_music_tools(model_name, model_provider_map, custom_models)

    def supports_read_aloud_tools(self, model_name: str, model_provider_map: Optional[Dict] = None, custom_models: Optional[Dict] = None) -> bool:
        """Check if a model supports read aloud tools."""
        return self._tool_manager.supports_read_aloud_tools(model_name, model_provider_map, custom_models)

    def supports_search_tools(self, model_name: str, model_provider_map: Optional[Dict] = None, custom_models: Optional[Dict] = None) -> bool:
        """Check if a model supports search tools."""
        return self._tool_manager.supports_search_tools(model_name, model_provider_map, custom_models)
