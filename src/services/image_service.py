"""
Image generation service for handling image creation and management.
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

from repositories import ChatHistoryRepository
from config import HISTORY_DIR
from events import EventBus, EventType, Event
from model_cards import get_card


class ImageGenerationService:
    """
    Service for managing image generation and storage.
    
    This service handles image generation requests, stores generated images
    in chat-specific directories, and manages image metadata.
    """
    
    def __init__(
        self,
        chat_history_repo: ChatHistoryRepository,
        event_bus: Optional[EventBus] = None,
    ):
        self._chat_history_repo = chat_history_repo
        self._event_bus = event_bus
    
    def _emit(self, event_type: EventType, **data) -> None:
        """Emit an event if event bus is configured."""
        if self._event_bus:
            self._event_bus.publish(Event(type=event_type, data=data, source='image_service'))
    
    def generate_image(
        self,
        prompt: str,
        model: str,
        provider: Any,
        provider_name: str,
        chat_id: str,
        image_data: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> str:
        """
        Generate an image using the specified provider.
        
        Parameters
        ----------
        prompt : str
            The image generation prompt.
        model : str
            The model to use for generation.
        provider : Any
            The initialized AI provider instance.
        provider_name : str
            Name of the provider (openai, gemini, grok, custom).
        chat_id : str
            Chat ID for organizing generated images.
        image_data : Optional[str]
            Base64 image data for editing (if supported).
        mime_type : Optional[str]
            MIME type of the image data.
            
        Returns
        -------
        str
            HTML img tag with path to the generated image.
        """
        try:
            # Call provider-specific generation
            if provider_name == 'openai':
                result = provider.generate_image(prompt, chat_id, model, image_data)
            elif provider_name == 'custom':
                result = provider.generate_image(prompt, chat_id, model)
            elif provider_name == 'gemini':
                if image_data:
                    result = provider.generate_image(prompt, chat_id, model, image_data, mime_type)
                else:
                    result = provider.generate_image(prompt, chat_id, model)
            elif provider_name == 'grok':
                result = provider.generate_image(prompt, chat_id, model)
            else:
                raise ValueError(f"Image generation not supported for provider: {provider_name}")
            
            # Extract path from result for event
            image_path = None
            if result and '<img src="' in result:
                import re
                match = re.search(r'<img src="([^"]+)"', result)
                if match:
                    image_path = match.group(1)
            
            self._emit(
                EventType.IMAGE_GENERATED,
                image_path=image_path,
                prompt=prompt,
                model=model,
                chat_id=chat_id
            )
            
            return result
            
        except Exception as e:
            self._emit(EventType.ERROR_OCCURRED, error=str(e), context='image_generation')
            raise
    
    def list_chat_images(self, chat_id: str) -> list:
        """List all images for a chat."""
        image_dir = Path(HISTORY_DIR) / chat_id / 'images'
        if not image_dir.exists():
            return []
        images = [
            str(f) for f in image_dir.iterdir()
            if f.is_file() and f.suffix.lower() in ['.png', '.jpg', '.jpeg', '.webp', '.gif']
        ]
        images.sort(key=lambda p: Path(p).stat().st_mtime, reverse=True)
        return images
