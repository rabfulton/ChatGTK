"""Tests for DocumentService and DocumentRepository."""

import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from repositories import DocumentRepository, Document
from services import DocumentService
from events import EventBus, EventType


class TestDocumentRepository:
    def test_create_document(self, tmp_path):
        repo = DocumentRepository(history_dir=str(tmp_path))
        doc = repo.create(title="Test Doc", content="Hello world")
        
        assert doc.id.startswith("document_")
        assert doc.title == "Test Doc"
        assert doc.content == "Hello world"
        assert (tmp_path / f"{doc.id}.json").exists()
    
    def test_get_document(self, tmp_path):
        repo = DocumentRepository(history_dir=str(tmp_path))
        created = repo.create(title="Test", content="Content")
        
        loaded = repo.get(created.id)
        assert loaded is not None
        assert loaded.id == created.id
        assert loaded.title == "Test"
        assert loaded.content == "Content"
    
    def test_save_document(self, tmp_path):
        repo = DocumentRepository(history_dir=str(tmp_path))
        doc = repo.create(title="Original", content="Original content")
        
        doc.content = "Updated content"
        repo.save(doc)
        
        loaded = repo.get(doc.id)
        assert loaded.content == "Updated content"
    
    def test_delete_document(self, tmp_path):
        repo = DocumentRepository(history_dir=str(tmp_path))
        doc = repo.create(title="To Delete", content="")
        doc_id = doc.id
        
        assert repo.exists(doc_id)
        repo.delete(doc_id)
        assert not repo.exists(doc_id)
    
    def test_list_documents(self, tmp_path):
        repo = DocumentRepository(history_dir=str(tmp_path))
        doc1 = repo.create(title="Doc 1", content="")
        # Ensure unique ID by modifying the second doc's ID
        doc2 = repo.create(title="Doc 2", content="")
        doc2.id = doc2.id + "_2"
        repo.save(doc2)
        
        docs = repo.list_all()
        assert len(docs) >= 2


class TestDocumentService:
    def test_new_document(self, tmp_path):
        repo = DocumentRepository(history_dir=str(tmp_path))
        service = DocumentService(repository=repo)
        
        doc = service.new_document(title="New Doc", content="Initial")
        
        assert service.has_document
        assert service.content == "Initial"
        assert not service.is_dirty
    
    def test_apply_tool_edit_pushes_undo(self, tmp_path):
        repo = DocumentRepository(history_dir=str(tmp_path))
        service = DocumentService(repository=repo)
        service.new_document(content="Original")
        
        service.apply_tool_edit("Edited", summary="Made edit")
        
        assert service.content == "Edited"
        assert service.can_undo
        assert not service.can_redo
    
    def test_manual_edit_no_undo(self, tmp_path):
        repo = DocumentRepository(history_dir=str(tmp_path))
        service = DocumentService(repository=repo)
        service.new_document(content="Original")
        
        service.set_content_manual("Manual edit")
        
        assert service.content == "Manual edit"
        assert not service.can_undo  # Manual edits don't push undo
    
    def test_undo_redo_roundtrip(self, tmp_path):
        repo = DocumentRepository(history_dir=str(tmp_path))
        service = DocumentService(repository=repo)
        service.new_document(content="V1")
        
        service.apply_tool_edit("V2", summary="Edit 1")
        service.apply_tool_edit("V3", summary="Edit 2")
        
        assert service.content == "V3"
        
        service.undo()
        assert service.content == "V2"
        assert service.can_redo
        
        service.undo()
        assert service.content == "V1"
        
        service.redo()
        assert service.content == "V2"
    
    def test_events_emitted(self, tmp_path):
        repo = DocumentRepository(history_dir=str(tmp_path))
        event_bus = EventBus()
        service = DocumentService(repository=repo, event_bus=event_bus)
        
        events = []
        event_bus.subscribe(EventType.DOCUMENT_CREATED, lambda e: events.append(e.type))
        event_bus.subscribe(EventType.DOCUMENT_UPDATED, lambda e: events.append(e.type))
        
        service.new_document(content="Test")
        service.apply_tool_edit("Updated", summary="Edit")
        
        assert EventType.DOCUMENT_CREATED in events
        assert EventType.DOCUMENT_UPDATED in events
