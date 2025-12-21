"""
Memory system for ChatGTK - semantic search over conversation history.

This package provides optional memory features using Qdrant for vector storage
and sentence-transformers or hosted APIs for embeddings.

The feature is fully optional - the app works normally if dependencies are missing.
"""

# Core dependency - always required for memory
QDRANT_AVAILABLE = False
try:
    from qdrant_client import QdrantClient
    del QdrantClient
    QDRANT_AVAILABLE = True
except ImportError:
    pass

# Local embeddings - only required if using local mode
LOCAL_EMBEDDINGS_AVAILABLE = False
try:
    from sentence_transformers import SentenceTransformer
    del SentenceTransformer
    LOCAL_EMBEDDINGS_AVAILABLE = True
except ImportError:
    pass

# Memory is available if Qdrant is installed (embeddings can be hosted)
MEMORY_AVAILABLE = QDRANT_AVAILABLE


def get_missing_dependencies() -> list:
    """Return list of missing optional dependencies for memory features."""
    missing = []
    if not QDRANT_AVAILABLE:
        missing.append("qdrant-client")
    return missing


def get_available_embedding_modes() -> list:
    """Return list of available embedding modes based on installed dependencies."""
    modes = []
    if LOCAL_EMBEDDINGS_AVAILABLE:
        modes.append("local")
    # Hosted modes only need their respective API keys, not extra deps
    modes.extend(["openai", "gemini", "cohere"])
    return modes


if MEMORY_AVAILABLE:
    from .schema import MemoryItem
    from .embedding_provider import get_embedding_provider, EmbeddingProvider, LOCAL_EMBEDDINGS_AVAILABLE as _LEA
    from .memory_repository import MemoryRepository
    from .memory_service import MemoryService
    
    __all__ = [
        'MEMORY_AVAILABLE',
        'LOCAL_EMBEDDINGS_AVAILABLE',
        'get_missing_dependencies',
        'get_available_embedding_modes',
        'MemoryItem',
        'EmbeddingProvider',
        'get_embedding_provider',
        'MemoryRepository',
        'MemoryService',
    ]
else:
    __all__ = [
        'MEMORY_AVAILABLE',
        'LOCAL_EMBEDDINGS_AVAILABLE',
        'get_missing_dependencies',
        'get_available_embedding_modes',
    ]
