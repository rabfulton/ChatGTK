from abc import ABC, abstractmethod
from openai import OpenAI
import requests
from pathlib import Path
from datetime import datetime

class AIProvider(ABC):
    """Abstract base class for AI providers."""
    
    @abstractmethod
    def initialize(self, api_key: str):
        """Initialize the AI provider with API key."""
        pass
    
    @abstractmethod
    def get_available_models(self):
        """Get list of available models."""
        pass
    
    @abstractmethod
    def generate_chat_completion(self, messages, model, temperature=0.7, max_tokens=None):
        """Generate chat completion."""
        pass
    
    @abstractmethod
    def generate_image(self, prompt, chat_id):
        """Generate image from prompt."""
        pass
    
    @abstractmethod
    def transcribe_audio(self, audio_file):
        """Transcribe audio file to text."""
        pass
    
    @abstractmethod
    def generate_speech(self, text, voice):
        """Generate speech from text."""
        pass

class OpenAIProvider(AIProvider):
    def __init__(self):
        self.client = None
    
    def initialize(self, api_key: str):
        self.client = OpenAI(api_key=api_key)
    
    def get_available_models(self):
        try:
            models = self.client.models.list()
            return [model.id for model in models]
        except Exception as e:
            print(f"Error fetching models: {e}")
            return ["gpt-3.5-turbo", "gpt-4", "gpt-4-turbo-preview", "dall-e-3"]
    
    def generate_chat_completion(self, messages, model, temperature=0.7, max_tokens=None):
        params = {
            'model': model,
            'messages': messages,
            'temperature': temperature
        }
        
        if max_tokens and max_tokens > 0:
            params['max_tokens'] = max_tokens
        
        response = self.client.chat.completions.create(**params)
        return response.choices[0].message.content
    
    def generate_image(self, prompt, chat_id):
        response = self.client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            n=1,
        )
        
        # Get the image URL
        image_url = response.data[0].url
        
        # Download the image
        images_dir = Path('history') / chat_id.replace('.json', '') / 'images'
        images_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate unique filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        image_path = images_dir / f"dalle_{timestamp}.png"
        
        # Download and save image
        response = requests.get(image_url)
        image_path.write_bytes(response.content)
        
        return f'<img src="{image_path}"/>'
    
    def transcribe_audio(self, audio_file):
        transcript = self.client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            timeout=20
        )
        return transcript.text
    
    def generate_speech(self, text, voice):
        return self.client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text
        )

    # Add a property to access audio functionality
    @property
    def audio(self):
        return self.client.audio

# Factory function to get the appropriate provider
def get_ai_provider(provider_name: str) -> AIProvider:
    providers = {
        'openai': OpenAIProvider,
        # Add other providers here as they're implemented
    }
    
    provider_class = providers.get(provider_name)
    if not provider_class:
        raise ValueError(f"Unknown AI provider: {provider_name}")
    
    return provider_class() 