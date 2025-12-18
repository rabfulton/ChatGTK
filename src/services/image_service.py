"""
Image generation service for handling image creation and management.
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

from repositories import ChatHistoryRepository
from config import HISTORY_DIR


class ImageGenerationService:
    """
    Service for managing image generation and storage.
    
    This service handles image generation requests, stores generated images
    in chat-specific directories, and manages image metadata.
    """
    
    def __init__(
        self,
        chat_history_repo: ChatHistoryRepository,
    ):
        """
        Initialize the image generation service.
        
        Parameters
        ----------
        chat_history_repo : ChatHistoryRepository
            Repository for accessing chat directories.
        """
        self._chat_history_repo = chat_history_repo
    
    def _get_chat_image_dir(self, chat_id: str) -> Path:
        """
        Get the image directory for a chat.
        
        Parameters
        ----------
        chat_id : str
            The chat identifier.
            
        Returns
        -------
        Path
            Path to the chat's image directory.
        """
        chat_dir = Path(HISTORY_DIR) / chat_id
        image_dir = chat_dir / 'images'
        image_dir.mkdir(parents=True, exist_ok=True)
        return image_dir
    
    def generate_image(
        self,
        provider: Any,
        prompt: str,
        model: str,
        chat_id: Optional[str] = None,
        size: str = "1024x1024",
        quality: str = "standard",
        style: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate an image using an AI provider.
        
        Parameters
        ----------
        provider : Any
            The AI provider instance with image generation capability.
        prompt : str
            The image generation prompt.
        model : str
            The model to use for generation.
        chat_id : Optional[str]
            Chat ID for organizing generated images.
        size : str
            Image size (e.g., "1024x1024").
        quality : str
            Image quality ("standard" or "hd").
        style : Optional[str]
            Image style (e.g., "vivid" or "natural").
            
        Returns
        -------
        Dict[str, Any]
            Dictionary containing:
            - 'success': Whether generation succeeded
            - 'image_path': Path to saved image (if successful)
            - 'image_url': URL of generated image (if applicable)
            - 'error': Error message (if failed)
        """
        try:
            # Prepare generation parameters
            kwargs = {
                'size': size,
                'quality': quality,
            }
            if style:
                kwargs['style'] = style
            
            # Generate image
            result = provider.generate_image(
                prompt=prompt,
                model=model,
                **kwargs
            )
            
            # Handle different result formats
            if isinstance(result, str):
                # Result is a file path or URL
                if result.startswith('http'):
                    image_url = result
                    image_path = None
                else:
                    image_path = result
                    image_url = None
            elif isinstance(result, dict):
                image_path = result.get('path')
                image_url = result.get('url')
            else:
                return {
                    'success': False,
                    'error': f'Unexpected result type: {type(result)}',
                }
            
            # Save to chat directory if chat_id provided
            if chat_id and image_path:
                saved_path = self.save_to_chat(chat_id, image_path)
                image_path = saved_path
            
            return {
                'success': True,
                'image_path': image_path,
                'image_url': image_url,
                'prompt': prompt,
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
            }
    
    def save_to_chat(self, chat_id: str, image_path: str) -> str:
        """
        Save an image to a chat's image directory.
        
        Parameters
        ----------
        chat_id : str
            The chat identifier.
        image_path : str
            Path to the source image file.
            
        Returns
        -------
        str
            Path to the saved image in the chat directory.
        """
        image_dir = self._get_chat_image_dir(chat_id)
        
        # Generate unique filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        source_path = Path(image_path)
        extension = source_path.suffix or '.png'
        dest_filename = f"image_{timestamp}{extension}"
        dest_path = image_dir / dest_filename
        
        # Copy or move the image
        import shutil
        if source_path.exists():
            shutil.copy2(source_path, dest_path)
        
        return str(dest_path)
    
    def edit_image(
        self,
        provider: Any,
        image_path: str,
        prompt: str,
        model: str,
        chat_id: Optional[str] = None,
        mask_path: Optional[str] = None,
        size: str = "1024x1024",
    ) -> Dict[str, Any]:
        """
        Edit an existing image using an AI provider.
        
        Parameters
        ----------
        provider : Any
            The AI provider instance with image editing capability.
        image_path : str
            Path to the image to edit.
        prompt : str
            The editing prompt.
        model : str
            The model to use for editing.
        chat_id : Optional[str]
            Chat ID for organizing edited images.
        mask_path : Optional[str]
            Path to mask image (for inpainting).
        size : str
            Output image size.
            
        Returns
        -------
        Dict[str, Any]
            Dictionary containing:
            - 'success': Whether editing succeeded
            - 'image_path': Path to edited image (if successful)
            - 'error': Error message (if failed)
        """
        try:
            # Check if provider supports image editing
            if not hasattr(provider, 'edit_image'):
                return {
                    'success': False,
                    'error': 'Provider does not support image editing',
                }
            
            # Edit image
            result = provider.edit_image(
                image_path=image_path,
                prompt=prompt,
                mask_path=mask_path,
                size=size,
            )
            
            # Handle result
            if isinstance(result, str):
                edited_path = result
            elif isinstance(result, dict):
                edited_path = result.get('path')
            else:
                return {
                    'success': False,
                    'error': f'Unexpected result type: {type(result)}',
                }
            
            # Save to chat directory if chat_id provided
            if chat_id and edited_path:
                saved_path = self.save_to_chat(chat_id, edited_path)
                edited_path = saved_path
            
            return {
                'success': True,
                'image_path': edited_path,
                'prompt': prompt,
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
            }
    
    def list_chat_images(self, chat_id: str) -> list:
        """
        List all images for a chat.
        
        Parameters
        ----------
        chat_id : str
            The chat identifier.
            
        Returns
        -------
        list
            List of image file paths.
        """
        image_dir = self._get_chat_image_dir(chat_id)
        
        if not image_dir.exists():
            return []
        
        images = []
        for file in image_dir.iterdir():
            if file.is_file() and file.suffix.lower() in ['.png', '.jpg', '.jpeg', '.webp', '.gif']:
                images.append(str(file))
        
        # Sort by modification time, newest first
        images.sort(key=lambda p: Path(p).stat().st_mtime, reverse=True)
        return images
    
    def delete_image(self, image_path: str) -> bool:
        """
        Delete an image file.
        
        Parameters
        ----------
        image_path : str
            Path to the image file.
            
        Returns
        -------
        bool
            True if deleted successfully, False otherwise.
        """
        try:
            path = Path(image_path)
            if path.exists() and path.is_file():
                path.unlink()
                return True
            return False
        except Exception as e:
            print(f"Error deleting image {image_path}: {e}")
            return False
