"""
Service for managing document state and operations.
"""

from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from repositories import DocumentRepository, Document
from events import EventBus, Event, EventType


# Maximum undo history entries per document
MAX_UNDO_STACK_SIZE = 50


@dataclass
class UndoEntry:
    """Entry in the undo/redo stack."""
    content: str
    summary: str


class DocumentService:
    """
    Service for managing document editing operations.
    
    Handles:
    - Current document state
    - Tool-only undo/redo stacks
    - Auto-save coordination
    """
    
    def __init__(
        self,
        repository: DocumentRepository,
        event_bus: Optional[EventBus] = None,
    ):
        self._repository = repository
        self._event_bus = event_bus
        self._current_document: Optional[Document] = None
        self._dirty = False
    
    @property
    def current_document(self) -> Optional[Document]:
        return self._current_document
    
    @property
    def current_document_id(self) -> Optional[str]:
        return self._current_document.id if self._current_document else None
    
    @property
    def is_dirty(self) -> bool:
        return self._dirty
    
    @property
    def has_document(self) -> bool:
        return self._current_document is not None
    
    @property
    def content(self) -> str:
        if self._current_document:
            return self._current_document.content
        return ""
    
    def get_document(self, doc_id: str) -> Optional[Document]:
        """Get a document by ID without loading it as current."""
        return self._repository.get(doc_id)
    
    def update_document(self, doc_id: str, title: str = None, content: str = None) -> bool:
        """Update a document's metadata."""
        doc = self._repository.get(doc_id)
        if not doc:
            return False
        if title is not None:
            doc.title = title
        if content is not None:
            doc.content = content
        self._repository.save(doc)
        # Update current if it's the same document
        if self._current_document and self._current_document.id == doc_id:
            if title is not None:
                self._current_document.title = title
        return True
    
    def delete_document(self, doc_id: str) -> bool:
        """Delete a document."""
        if self._current_document and self._current_document.id == doc_id:
            self.close_document()
        return self._repository.delete(doc_id)
    
    @property
    def can_undo(self) -> bool:
        return bool(self._current_document and self._current_document.undo_stack)
    
    @property
    def can_redo(self) -> bool:
        return bool(self._current_document and self._current_document.redo_stack)
    
    def new_document(self, title: str = "Untitled", content: str = "") -> Document:
        """Create and load a new document."""
        doc = self._repository.create(title, content)
        self._current_document = doc
        self._dirty = False
        self._emit(EventType.DOCUMENT_CREATED, {'document_id': doc.id, 'title': doc.title})
        return doc
    
    def load_document(self, doc_id: str) -> Optional[Document]:
        """Load a document by ID."""
        doc = self._repository.get(doc_id)
        if doc:
            self._current_document = doc
            self._dirty = False
            self._emit(EventType.DOCUMENT_LOADED, {'document_id': doc.id, 'title': doc.title})
        return doc
    
    def save_document(self) -> Optional[str]:
        """Save the current document."""
        if not self._current_document:
            return None
        doc_id = self._repository.save(self._current_document)
        self._dirty = False
        self._emit(EventType.DOCUMENT_SAVED, {'document_id': doc_id})
        return doc_id
    
    def close_document(self) -> None:
        """Close the current document."""
        self._current_document = None
        self._dirty = False
    
    def apply_tool_edit(self, new_content: str, summary: str = "") -> bool:
        """
        Apply a tool edit to the document.
        Pushes current content to undo stack.
        """
        if not self._current_document:
            return False
        
        # Push current state to undo stack
        self._current_document.undo_stack.append({
            'content': self._current_document.content,
            'summary': summary,
        })
        
        # Trim undo stack if too large
        if len(self._current_document.undo_stack) > MAX_UNDO_STACK_SIZE:
            self._current_document.undo_stack = self._current_document.undo_stack[-MAX_UNDO_STACK_SIZE:]
        
        # Clear redo stack on new edit
        self._current_document.redo_stack = []
        
        # Apply edit
        self._current_document.content = new_content
        self._dirty = True
        
        self._emit(EventType.DOCUMENT_UPDATED, {
            'document_id': self._current_document.id,
            'summary': summary,
        })
        
        # Auto-save after tool edit
        self.save_document()
        
        return True
    
    def set_content_manual(self, new_content: str) -> bool:
        """
        Set document content from manual typing.
        Does NOT push to undo stack.
        """
        if not self._current_document:
            return False
        
        self._current_document.content = new_content
        self._dirty = True
        
        # Don't emit DOCUMENT_UPDATED for manual edits to avoid popover
        return True
    
    def undo(self) -> Optional[str]:
        """
        Undo the last tool edit.
        Returns the summary of the undone edit, or None if nothing to undo.
        """
        if not self.can_undo:
            return None
        
        doc = self._current_document
        
        # Push current state to redo stack
        doc.redo_stack.append({
            'content': doc.content,
            'summary': 'Redo',
        })
        
        # Pop from undo stack
        entry = doc.undo_stack.pop()
        doc.content = entry['content']
        self._dirty = True
        
        self._emit(EventType.DOCUMENT_UNDO, {
            'document_id': doc.id,
            'summary': entry.get('summary', ''),
        })
        
        self.save_document()
        
        return entry.get('summary', 'Undo applied')
    
    def redo(self) -> Optional[str]:
        """
        Redo the last undone edit.
        Returns the summary, or None if nothing to redo.
        """
        if not self.can_redo:
            return None
        
        doc = self._current_document
        
        # Push current state to undo stack
        doc.undo_stack.append({
            'content': doc.content,
            'summary': 'Undo',
        })
        
        # Pop from redo stack
        entry = doc.redo_stack.pop()
        doc.content = entry['content']
        self._dirty = True
        
        self._emit(EventType.DOCUMENT_REDO, {
            'document_id': doc.id,
        })
        
        self.save_document()
        
        return 'Redo applied'
    
    def rename_document(self, new_title: str) -> bool:
        """Rename the current document."""
        if not self._current_document:
            return False
        self._current_document.title = new_title
        self._dirty = True
        self.save_document()
        return True
    
    def delete_document(self, doc_id: str) -> bool:
        """Delete a document."""
        if self._current_document and self._current_document.id == doc_id:
            self.close_document()
        return self._repository.delete(doc_id)
    
    def list_documents(self) -> List[Dict[str, Any]]:
        """List all documents."""
        return [m.to_dict() for m in self._repository.list_all()]
    
    def _emit(self, event_type: EventType, data: Dict[str, Any]) -> None:
        """Emit an event if event bus is available."""
        if self._event_bus:
            self._event_bus.publish(Event(type=event_type, data=data, source='document_service'))
