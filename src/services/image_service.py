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
    
    def generate_with_preferred_model(
        self,
        prompt: str,
        preferred_model: str,
        provider_name: str,
        providers: Dict[str, Any],
        custom_providers: Dict[str, Any],
        custom_models: Dict[str, Any],
        api_keys: Dict[str, str],
        chat_id: str,
        last_msg: Optional[Dict] = None,
        image_path: Optional[str] = None,
        initialize_provider_fn: Optional[callable] = None,
    ) -> str:
        """
        Generate image using preferred model with fallback to dall-e-3.
        
        Parameters
        ----------
        prompt : str
            The image generation prompt.
        preferred_model : str
            User's preferred image model.
        provider_name : str
            Provider for the preferred model.
        providers : Dict[str, Any]
            Dictionary of initialized providers.
        custom_providers : Dict[str, Any]
            Dictionary of custom providers.
        custom_models : Dict[str, Any]
            Custom model configurations.
        api_keys : Dict[str, str]
            API keys for providers.
        chat_id : str
            Chat ID for organizing images.
        last_msg : Optional[Dict]
            Last user message (for attached images).
        image_path : Optional[str]
            Path to source image for editing.
        initialize_provider_fn : Optional[callable]
            Function to initialize a provider.
            
        Returns
        -------
        str
            HTML img tag with path to the generated image.
        """
        from ai_providers import get_ai_provider
        from utils import resolve_api_key
        
        # Prepare image data for editing
        image_data = None
        mime_type = None
        has_attached_images = last_msg and "images" in last_msg and last_msg["images"]
        
        if image_path:
            # Load image from path for editing
            try:
                import base64
                with open(image_path, 'rb') as f:
                    image_data = base64.b64encode(f.read()).decode('utf-8')
                mime_type = "image/png"
                has_attached_images = True
            except Exception as e:
                print(f"[ImageService] Error loading image for editing: {e}")
        elif has_attached_images:
            img = last_msg["images"][0]
            image_data = img.get("data")
            mime_type = img.get("mime_type")
        
        # Check if model supports editing
        card = get_card(preferred_model, custom_models)
        supports_edit = card.capabilities.image_edit if card else False
        if not supports_edit:
            image_data = None
            mime_type = None
        
        # Get or initialize provider
        provider = self._get_provider(
            provider_name, preferred_model, providers, custom_providers,
            custom_models, api_keys, initialize_provider_fn
        )
        
        print(f"[ImageService] Using model: {preferred_model} (provider: {provider_name}), editing: {image_data is not None}")
        
        try:
            return self.generate_image(
                prompt=prompt,
                model=preferred_model,
                provider=provider,
                provider_name=provider_name,
                chat_id=chat_id,
                image_data=image_data,
                mime_type=mime_type,
            )
        except Exception as e:
            # Fallback to dall-e-3
            print(f"[ImageService] Preferred model failed ({preferred_model}): {e}")
            print(f"[ImageService] Falling back to: dall-e-3 (provider: openai)")
            
            fallback_provider = self._get_provider(
                'openai', 'dall-e-3', providers, custom_providers,
                custom_models, api_keys, initialize_provider_fn
            )
            
            return self.generate_image(
                prompt=prompt,
                model='dall-e-3',
                provider=fallback_provider,
                provider_name='openai',
                chat_id=chat_id,
            )
    
    def _get_provider(
        self,
        provider_name: str,
        model: str,
        providers: Dict[str, Any],
        custom_providers: Dict[str, Any],
        custom_models: Dict[str, Any],
        api_keys: Dict[str, str],
        initialize_provider_fn: Optional[callable],
    ) -> Any:
        """Get or initialize a provider."""
        from ai_providers import get_ai_provider
        from utils import resolve_api_key
        
        if provider_name == "custom":
            provider = custom_providers.get(model)
            if not provider:
                cfg = custom_models.get(model, {})
                if not cfg:
                    raise ValueError(f"Custom model '{model}' is not configured")
                provider = get_ai_provider("custom")
                provider.initialize(
                    api_key=resolve_api_key(cfg.get("api_key", "")).strip(),
                    endpoint=cfg.get("endpoint"),
                    model_name=cfg.get("model_name") or model,
                    api_type=cfg.get("api_type") or "images",
                    voice=cfg.get("voice"),
                )
                custom_providers[model] = provider
            return provider
        else:
            provider = providers.get(provider_name)
            if not provider:
                api_key = os.environ.get(
                    f"{provider_name.upper()}_API_KEY",
                    api_keys.get(provider_name, "")
                ).strip()
                if initialize_provider_fn:
                    provider = initialize_provider_fn(provider_name, api_key)
                if not provider:
                    raise ValueError(f"{provider_name.title()} provider is not initialized")
            return provider
    
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
