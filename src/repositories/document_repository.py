"""
Repository for managing document persistence.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

from .base import Repository
from config import HISTORY_DIR


@dataclass
class Document:
    """Represents a document with metadata and content."""
    id: str
    title: str
    content: str
    created_at: datetime
    updated_at: datetime
    undo_stack: List[Dict[str, Any]] = field(default_factory=list)
    redo_stack: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'title': self.title,
            'content': self.content,
            'mode': 'document',
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'undo_stack': self.undo_stack,
            'redo_stack': self.redo_stack,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Document':
        return cls(
            id=data['id'],
            title=data.get('title', 'Untitled'),
            content=data.get('content', ''),
            created_at=datetime.fromisoformat(data['created_at']),
            updated_at=datetime.fromisoformat(data['updated_at']),
            undo_stack=data.get('undo_stack', []),
            redo_stack=data.get('redo_stack', []),
        )


@dataclass
class DocumentMetadata:
    """Lightweight metadata for document listing."""
    id: str
    title: str
    updated_at: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'title': self.title,
            'updated_at': self.updated_at.isoformat(),
        }


class DocumentRepository(Repository[Document]):
    """Repository for managing documents stored as JSON files."""
    
    def __init__(self, history_dir: str = None):
        self.history_dir = Path(history_dir or HISTORY_DIR)
        self._ensure_dir()
    
    def _ensure_dir(self) -> None:
        self.history_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_path(self, doc_id: str) -> Path:
        if doc_id.endswith('.json'):
            doc_id = doc_id[:-5]
        return self.history_dir / f"{doc_id}.json"
    
    def _is_document_file(self, path: Path) -> bool:
        """Check if a JSON file is a document (not a chat)."""
        if not path.exists() or not path.suffix == '.json':
            return False
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get('mode') == 'document'
        except:
            return False
    
    def create(self, title: str = "Untitled", content: str = "") -> Document:
        """Create a new document."""
        now = datetime.now()
        doc_id = f"document_{now.strftime('%Y%m%d_%H%M%S')}"
        doc = Document(
            id=doc_id,
            title=title,
            content=content,
            created_at=now,
            updated_at=now,
        )
        self.save(doc)
        return doc
    
    def get(self, doc_id: str) -> Optional[Document]:
        """Load a document by ID."""
        path = self._get_path(doc_id)
        if not path.exists():
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if data.get('mode') != 'document':
                return None
            return Document.from_dict(data)
        except Exception as e:
            print(f"Error loading document {doc_id}: {e}")
            return None
    
    def save(self, doc: Document) -> str:
        """Save a document, returns the document ID."""
        doc.updated_at = datetime.now()
        path = self._get_path(doc.id)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(doc.to_dict(), f, indent=2)
        return doc.id
    
    def delete(self, doc_id: str) -> bool:
        """Delete a document."""
        path = self._get_path(doc_id)
        if path.exists():
            path.unlink()
            return True
        return False
    
    def list_all(self) -> List[DocumentMetadata]:
        """List all documents with metadata."""
        documents = []
        for path in self.history_dir.glob('*.json'):
            if self._is_document_file(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    documents.append(DocumentMetadata(
                        id=data['id'],
                        title=data.get('title', 'Untitled'),
                        updated_at=datetime.fromisoformat(data['updated_at']),
                    ))
                except:
                    continue
        # Sort by updated_at descending
        documents.sort(key=lambda d: d.updated_at, reverse=True)
        return documents
    
    def exists(self, doc_id: str) -> bool:
        """Check if a document exists."""
        return self._get_path(doc_id).exists()
