"""
Repository pattern implementations for data access layer.

This package provides repository classes that abstract data persistence
and retrieval operations, separating data access concerns from business logic.
"""

from .base import Repository
from .chat_history_repository import ChatHistoryRepository
from .settings_repository import SettingsRepository
from .api_keys_repository import APIKeysRepository
from .model_cache_repository import ModelCacheRepository
from .projects_repository import ProjectsRepository, Project, PROJECTS_DIR
from .document_repository import DocumentRepository, Document, DocumentMetadata

__all__ = [
    'Repository',
    'ChatHistoryRepository',
    'SettingsRepository',
    'APIKeysRepository',
    'ModelCacheRepository',
    'ProjectsRepository',
    'Project',
    'PROJECTS_DIR',
    'DocumentRepository',
    'Document',
    'DocumentMetadata',
]
