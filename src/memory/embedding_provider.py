"""
Embedding providers for the memory system.

Supports local (sentence-transformers) and hosted (OpenAI, Gemini, Cohere) embeddings.
"""

from abc import ABC, abstractmethod
from typing import List, Optional
import os

# Check if local embeddings are available
LOCAL_EMBEDDINGS_AVAILABLE = False
try:
    from sentence_transformers import SentenceTransformer
    LOCAL_EMBEDDINGS_AVAILABLE = True
except ImportError:
    pass


# Vector dimensions for known models
EMBEDDING_DIMENSIONS = {
    # Local
    "all-MiniLM-L6-v2": 384,
    "all-mpnet-base-v2": 768,
    # OpenAI
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    # Gemini
    "text-embedding-004": 768,
    # Mistral
    "mistral-embed": 1024,
}


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers."""
    
    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the embedding dimension for this provider."""
        pass
    
    @abstractmethod
    def embed(self, text: str) -> List[float]:
        """Generate embedding for a single text."""
        pass
    
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts. Override for efficiency."""
        return [self.embed(t) for t in texts]


class LocalEmbeddingProvider(EmbeddingProvider):
    """Local embeddings using sentence-transformers."""
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        if not LOCAL_EMBEDDINGS_AVAILABLE:
            raise ImportError(
                "sentence-transformers is required for local embeddings. "
                "Install with: pip install sentence-transformers"
            )
        from sentence_transformers import SentenceTransformer
        self.model_name = model_name
        self._model = SentenceTransformer(model_name)
        self._dimension = EMBEDDING_DIMENSIONS.get(model_name, 384)
    
    @property
    def dimension(self) -> int:
        return self._dimension
    
    def embed(self, text: str) -> List[float]:
        return self._model.encode(text, convert_to_numpy=True).tolist()
    
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        embeddings = self._model.encode(texts, convert_to_numpy=True)
        return [e.tolist() for e in embeddings]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI embeddings via API."""
    
    def __init__(self, model_name: str = "text-embedding-3-small", api_key: str = None):
        from openai import OpenAI
        self.model_name = model_name
        self._client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))
        self._dimension = EMBEDDING_DIMENSIONS.get(model_name, 1536)
    
    @property
    def dimension(self) -> int:
        return self._dimension
    
    def embed(self, text: str) -> List[float]:
        response = self._client.embeddings.create(input=text, model=self.model_name)
        return response.data[0].embedding
    
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        response = self._client.embeddings.create(input=texts, model=self.model_name)
        return [d.embedding for d in response.data]


class GeminiEmbeddingProvider(EmbeddingProvider):
    """Google Gemini embeddings via API."""
    
    def __init__(self, model_name: str = "text-embedding-004", api_key: str = None):
        import google.generativeai as genai
        self.model_name = model_name
        api_key = api_key or os.environ.get("GEMINI_API_KEY")
        genai.configure(api_key=api_key)
        self._genai = genai
        self._dimension = EMBEDDING_DIMENSIONS.get(model_name, 768)
    
    @property
    def dimension(self) -> int:
        return self._dimension
    
    def embed(self, text: str) -> List[float]:
        result = self._genai.embed_content(
            model=f"models/{self.model_name}",
            content=text,
            task_type="retrieval_document"
        )
        return result['embedding']
    
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        # Gemini doesn't have native batch, but we can use embed_content with list
        return [self.embed(t) for t in texts]


class CustomEmbeddingProvider(EmbeddingProvider):
    """Custom embeddings via OpenAI-compatible /v1/embeddings endpoint."""
    
    def __init__(self, model_name: str, endpoint: str, api_key: str = None, dimension: int = None):
        from openai import OpenAI
        self.model_name = model_name
        # Ensure endpoint ends properly for base_url
        base_url = endpoint.rstrip('/')
        if not base_url.endswith('/v1'):
            base_url = base_url + '/v1' if not base_url.endswith('/') else base_url + 'v1'
        self._client = OpenAI(base_url=base_url, api_key=api_key or "dummy")
        # Auto-detect dimension from first embedding if not provided
        self._dimension = dimension or EMBEDDING_DIMENSIONS.get(model_name)
        if self._dimension is None:
            self._dimension = self._detect_dimension()
    
    def _detect_dimension(self) -> int:
        """Detect embedding dimension by making a test request."""
        try:
            response = self._client.embeddings.create(input="test", model=self.model_name)
            dim = len(response.data[0].embedding)
            print(f"[Memory] Auto-detected embedding dimension: {dim}")
            return dim
        except Exception as e:
            print(f"[Memory] Failed to detect dimension, defaulting to 1536: {e}")
            return 1536
    
    @property
    def dimension(self) -> int:
        return self._dimension
    
    def embed(self, text: str) -> List[float]:
        response = self._client.embeddings.create(input=text, model=self.model_name)
        return response.data[0].embedding
    
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        response = self._client.embeddings.create(input=texts, model=self.model_name)
        return [d.embedding for d in response.data]


def get_embedding_provider(
    mode: str = "local",
    model: str = None,
    api_key: str = None,
    endpoint: str = None,
    dimension: int = None,
) -> EmbeddingProvider:
    """
    Factory function to create an embedding provider.
    
    Parameters
    ----------
    mode : str
        One of: "local", "openai", "gemini", "custom"
    model : str
        Model name (uses sensible defaults if not provided)
    api_key : str
        API key for hosted providers (falls back to env vars)
    endpoint : str
        Custom endpoint URL (required for "custom" mode)
    dimension : int
        Vector dimension for custom models (optional, defaults to 1536)
    
    Returns
    -------
    EmbeddingProvider
        The configured embedding provider
    """
    mode = mode.lower()
    
    if mode == "local":
        return LocalEmbeddingProvider(model or "all-MiniLM-L6-v2")
    elif mode == "openai":
        return OpenAIEmbeddingProvider(model or "text-embedding-3-small", api_key)
    elif mode == "gemini":
        return GeminiEmbeddingProvider(model or "text-embedding-004", api_key)
    elif mode == "custom":
        if not endpoint:
            raise ValueError("Custom embedding mode requires an endpoint URL")
        return CustomEmbeddingProvider(model, endpoint, api_key, dimension)
    else:
        raise ValueError(f"Unknown embedding mode: {mode}")


def get_dimension_for_model(model: str) -> int:
    """Get the embedding dimension for a known model."""
    return EMBEDDING_DIMENSIONS.get(model, 1536)
