"""
controller.py – Application state and business logic, decoupled from GTK UI.

This module provides the ChatController class that manages:
- Conversation history and chat lifecycle
- AI provider initialization and model management
- Settings and API key management
- Tool manager configuration

The controller is designed to be toolkit-agnostic to facilitate future porting.
"""

from __future__ import annotations

import os
import json
import shutil
import subprocess
import tempfile
from datetime import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Callable

from repositories import (
    SettingsRepository,
    APIKeysRepository,
    ChatHistoryRepository,
    ModelCacheRepository,
)
from services import (
    ChatService,
    ImageGenerationService,
    AudioService,
    ToolService,
)
from settings import SettingsManager
from events import EventBus, EventType, Event, get_event_bus
from utils import (
    load_api_keys,
    load_custom_models,
    save_custom_models,
    set_history_dir_getter as set_utils_history_dir_getter,
)
from ai_providers import get_ai_provider, set_history_dir_getter as set_ai_history_dir_getter
from conversation import (
    create_system_message,
    create_user_message,
    create_assistant_message,
    ConversationHistory,
)
from tools import (
    ToolManager,
    is_chat_completion_model,
    append_tool_guidance,
)
from config import DEFAULT_TEXT_EDIT_TOOL_PROMPT_APPENDIX, DEFAULT_TEXT_EDIT_TOOL_PROMPT_APPENDIX_LEGACY


@dataclass
class TextTarget:
    """Text target for tool-based edits."""
    get_text: Callable[[], str]
    apply_tool_edit: Callable[[str, Optional[str]], None]
    path: Optional[str] = None  # File path for undo persistence


class ChatController:
    """
    Manages application state and business logic for the chat client.
    
    This class is designed to be independent of any specific GUI toolkit,
    making it suitable for use with GTK, Qt, or other frameworks.
    """

    def __init__(self, 
                 settings_repo: Optional[SettingsRepository] = None,
                 api_keys_repo: Optional[APIKeysRepository] = None,
                 chat_history_repo: Optional[ChatHistoryRepository] = None,
                 model_cache_repo: Optional[ModelCacheRepository] = None,
                 event_bus: Optional[EventBus] = None,
                 settings_manager: Optional[SettingsManager] = None):
        """Initialize the controller with settings and state.
        
        Parameters
        ----------
        settings_repo : Optional[SettingsRepository]
            Settings repository instance. If None, creates a new one.
        api_keys_repo : Optional[APIKeysRepository]
            API keys repository instance. If None, creates a new one.
        chat_history_repo : Optional[ChatHistoryRepository]
            Chat history repository instance. If None, creates a new one.
        model_cache_repo : Optional[ModelCacheRepository]
            Model cache repository instance. If None, creates a new one.
        event_bus : Optional[EventBus]
            Event bus for publishing/subscribing to events. If None, uses global.
        settings_manager : Optional[SettingsManager]
            Settings manager instance. If None, creates a new one.
        """
        # Initialize repositories
        self._settings_repo = settings_repo or SettingsRepository()
        self._api_keys_repo = api_keys_repo or APIKeysRepository()
        self._model_cache_repo = model_cache_repo or ModelCacheRepository()
        
        # Initialize projects repository
        from repositories import ProjectsRepository, DocumentRepository
        self._projects_repo = ProjectsRepository()
        self._document_repo = DocumentRepository()

        # Initialize event bus
        self._event_bus = event_bus or get_event_bus()

        # Initialize settings manager
        self._settings_manager = settings_manager or SettingsManager(
            repository=self._settings_repo,
            event_bus=self._event_bus,
        )
        self._migrate_text_edit_prompt_appendix()

        # Initialize chat history repo with current project's history dir
        self._chat_history_repo = chat_history_repo
        self._init_history_repo_for_project()
        
        # Initialize services with event bus
        self._chat_service = ChatService(
            history_repo=self._chat_history_repo,
            settings_repo=self._settings_repo,
            api_keys_repo=self._api_keys_repo,
            event_bus=self._event_bus,
            settings_manager=self._settings_manager,
        )
        self._image_service = ImageGenerationService(
            chat_history_repo=self._chat_history_repo,
            event_bus=self._event_bus,
        )
        self._audio_service = AudioService(event_bus=self._event_bus)
        
        # Load settings for frequently accessed attributes
        self.system_message = self._settings_manager.get(
            'SYSTEM_MESSAGE',
            'You are a helpful assistant.'
        )
        self.active_system_prompt_id = self._settings_manager.get(
            'ACTIVE_SYSTEM_PROMPT_ID',
            ''
        )
        self.system_prompts_json = self._settings_manager.get(
            'SYSTEM_PROMPTS_JSON',
            ''
        )
        self.hidden_default_prompts = self._settings_manager.get(
            'HIDDEN_DEFAULT_PROMPTS',
            '[]'
        )
        
        # Initialize system prompts from settings
        self._init_system_prompts_from_settings()
        
        # Chat state
        self.current_chat_id: Optional[str] = None
        self.conversation_history: List[Dict[str, Any]] = [
            create_system_message(self.system_message)
        ]
        self.current_chat_metadata: Dict[str, Any] = {}
        self._pending_text_edit_events: List[Dict[str, Any]] = []
        self._text_edit_history_by_message: Dict[int, List[Dict[str, Any]]] = {}
        self._suppress_text_edit_logging = False
        
        # Text targets for reusable text edit tools
        self._text_targets: Dict[str, TextTarget] = {}
        
        # Provider management
        self.providers: Dict[str, Any] = {}
        self.model_provider_map: Dict[str, str] = {}
        self.api_keys: Dict[str, str] = self._api_keys_repo.get_all_raw()
        self.custom_models: Dict[str, Dict[str, Any]] = load_custom_models()
        self.custom_providers: Dict[str, Any] = {}
        
        # Tool manager
        self.tool_manager = ToolManager(
            image_tool_enabled=self._settings_manager.get('IMAGE_TOOL_ENABLED', True),
            music_tool_enabled=self._settings_manager.get('MUSIC_TOOL_ENABLED', False),
            read_aloud_tool_enabled=self._settings_manager.get('READ_ALOUD_TOOL_ENABLED', False),
            search_tool_enabled=self._settings_manager.get('SEARCH_TOOL_ENABLED', False),
            text_edit_tool_enabled=self._settings_manager.get('TEXT_EDIT_TOOL_ENABLED', False),
        )
        
        # Initialize tool service with event bus
        self._tool_service = ToolService(
            tool_manager=self.tool_manager,
            event_bus=self._event_bus,
            settings_manager=self._settings_manager,
        )
        
        # Initialize document service
        from services import DocumentService
        self._document_service = DocumentService(
            repository=self._document_repo,
            event_bus=self._event_bus,
        )
        
        # Initialize memory service (optional - only if dependencies available)
        self._memory_service = None

    # -----------------------------------------------------------------------
    # Memory service management
    # -----------------------------------------------------------------------

    def _init_memory_service(self) -> None:
        """Initialize the memory service if dependencies are available and enabled."""
        if not self._settings_manager.get('MEMORY_ENABLED', False):
            return

        from memory import MEMORY_AVAILABLE

        if not MEMORY_AVAILABLE:
            return
        
        # Close existing service first to release the database lock
        if self._memory_service is not None:
            try:
                self._memory_service.close()
            except Exception:
                pass
            self._memory_service = None
        
        try:
            from memory import MemoryService
            from config import MEMORY_DB_PATH
            
            mode = self._settings_manager.get('MEMORY_EMBEDDING_MODE', 'openai')
            model = self._settings_manager.get('MEMORY_EMBEDDING_MODEL', 'text-embedding-3-small')
            
            # Handle custom embedding providers
            endpoint = None
            api_key = None
            if mode == "custom":
                cfg = self.custom_models.get(model, {})
                endpoint = cfg.get("endpoint", "")
                api_key = cfg.get("api_key", "")
            
            self._memory_service = MemoryService(
                db_path=MEMORY_DB_PATH,
                embedding_mode=mode,
                embedding_model=model,
                api_key=api_key,
                endpoint=endpoint,
                event_bus=self._event_bus,
                settings_manager=self._settings_manager,
            )
            print(f"[Memory] Service initialized with mode={mode}, model={model}")
        except Exception as e:
            print(f"[Memory] Failed to initialize memory service: {e}")
            import traceback
            traceback.print_exc()
            self._memory_service = None

    def init_memory_service_if_enabled(self) -> None:
        """Initialize memory service (safe no-op if disabled)."""
        self._init_memory_service()

    def _migrate_text_edit_prompt_appendix(self) -> None:
        current = self._settings_manager.get('TEXT_EDIT_TOOL_PROMPT_APPENDIX', '')
        if current == DEFAULT_TEXT_EDIT_TOOL_PROMPT_APPENDIX_LEGACY:
            self._settings_manager.set(
                'TEXT_EDIT_TOOL_PROMPT_APPENDIX',
                DEFAULT_TEXT_EDIT_TOOL_PROMPT_APPENDIX,
                emit_event=False,
            )
            self._settings_manager.save()

    # -----------------------------------------------------------------------
    # Reusable text edit tool targets
    # -----------------------------------------------------------------------

    def register_text_target(self, name: str, target: TextTarget) -> None:
        """Register a text target for tool-based edits."""
        if not name:
            raise ValueError("Text target name is required.")
        self._text_targets[name] = target

    def unregister_text_target(self, name: str) -> None:
        """Remove a registered text target."""
        self._text_targets.pop(name, None)

    def has_text_targets(self) -> bool:
        """Return True if any text targets are registered."""
        return bool(self._text_targets)

    def _get_text_target(self, target: str) -> Optional[TextTarget]:
        return self._text_targets.get(target)

    def handle_text_get(self, target: str) -> str:
        """Return the current text for a registered target."""
        entry = self._get_text_target(target)
        if entry is None:
            return f"Error: unknown text target '{target}'."
        try:
            return entry.get_text() or ""
        except Exception as e:
            return f"Error reading text target '{target}': {e}"

    def handle_apply_text_edit(
        self,
        target: str,
        operation: str,
        text: str,
        summary: Optional[str] = None,
        search: Optional[str] = None,
    ) -> str:
        """Apply a tool edit to a registered target."""
        entry = self._get_text_target(target)
        if entry is None:
            return f"Error: unknown text target '{target}'."
        if operation not in ("replace", "diff", "search_replace"):
            return f"Error: unsupported text edit operation '{operation}'."
        try:
            original_text = entry.get_text() or ""
            new_text = text
            if operation == "diff":
                normalized_diff = self._normalize_diff_text(text)
                if not self._looks_like_unified_diff(normalized_diff):
                    print("[TextEditTool] Diff format invalid; refusing to apply.")
                    return (
                        "Error: diff must be unified format with ---/+++ headers and @@ hunks. "
                        "Use operation=search_replace instead for targeted edits."
                    )
                new_text = self._apply_unified_diff(original_text, normalized_diff)
            elif operation == "search_replace":
                if not search:
                    return "Error: search_replace requires 'search' parameter with text to find."
                if search not in original_text:
                    return f"Error: search text not found in target. Make sure it matches exactly including whitespace."
                count = original_text.count(search)
                if count > 1:
                    print(f"[TextEditTool] Warning: search text found {count} times, replacing all occurrences.")
                new_text = original_text.replace(search, text)
            entry.apply_tool_edit(new_text, summary)
            print(f"[TextEditTool] Applied {operation} edit to '{target}'.")
            if not self._suppress_text_edit_logging:
                event = {
                    "target": target,
                    "operation": operation,
                    "summary": summary or "",
                    "previous_text": original_text,
                }
                if entry.path:
                    event["target_path"] = entry.path
                self._pending_text_edit_events.append(event)
                print(f"[TextEditTool] Logged edit event, pending count: {len(self._pending_text_edit_events)}")
            return summary or "Text updated."
        except Exception as e:
            print(f"[TextEditTool] Error applying edit to '{target}': {e}")
            if operation == "diff":
                return (
                    f"Error applying text edit to '{target}': {e}. "
                    "Use operation=search_replace instead for targeted edits."
                )
            return f"Error applying text edit to '{target}': {e}"

    def _apply_unified_diff(self, original_text: str, diff_text: str) -> str:
        """Apply a unified diff to text using the system patch utility."""
        if shutil.which("patch") is None:
            raise RuntimeError("patch utility not found; diff edits require patch.")
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = os.path.join(tmpdir, "target.txt")
            patched_path = os.path.join(tmpdir, "patched.txt")
            with open(original_path, "w", encoding="utf-8") as handle:
                handle.write(original_text or "")
            # Use --fuzz=3 to allow fuzzy matching for slightly misaligned diffs
            result = subprocess.run(
                ["patch", "--silent", "--fuzz=3", "--output", patched_path, original_path],
                input=diff_text or "",
                text=True,
                capture_output=True,
            )
            if result.returncode != 0:
                stderr = (result.stderr or result.stdout or "").strip()
                if stderr:
                    print(f"[TextEditTool] patch error: {stderr}")
                raise RuntimeError(stderr or "patch failed")
            if not os.path.exists(patched_path):
                raise RuntimeError("patch did not produce output")
            with open(patched_path, "r", encoding="utf-8", errors="ignore") as handle:
                return handle.read()

    def _looks_like_unified_diff(self, diff_text: str) -> bool:
        if not diff_text:
            return False
        stripped = diff_text.lstrip()
        if stripped.startswith("diff --git"):
            return "+++" in diff_text and "@@" in diff_text
        if not stripped.startswith("--- "):
            return False
        return "+++" in diff_text and "@@" in diff_text

    def _normalize_diff_text(self, diff_text: str) -> str:
        text = (diff_text or "").strip()
        lines = text.splitlines()
        removed = 0
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
            removed += 1
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
            removed += 1
        filtered = []
        for line in lines:
            if line.lstrip().startswith("```"):
                removed += 1
                continue
            filtered.append(line)
        text = "\n".join(filtered).strip()
        if removed:
            print(f"[TextEditTool] Stripped {removed} code-fence lines from diff text.")
        return text

    def undo_text_edit_for_message(self, message_index: int) -> tuple[bool, str]:
        """Undo the last text edit associated with a message."""
        events = self._text_edit_history_by_message.get(message_index)
        if not events:
            return False, "No text edit history found for this message."
        last_event = events[-1]
        target = last_event.get("target", "")
        target_path = last_event.get("target_path")
        previous_text = last_event.get("previous_text", "")
        
        # If we have a stored path, write directly to file
        if target_path and target == "file":
            try:
                with open(target_path, 'w', encoding='utf-8') as f:
                    f.write(previous_text)
                return True, "Undo applied."
            except Exception as e:
                return False, f"Error writing to {target_path}: {e}"
        
        # Fall back to current registered target
        entry = self._get_text_target(target)
        if entry is None:
            return False, f"Text target '{target}' is no longer available."
        try:
            self._suppress_text_edit_logging = True
            entry.apply_tool_edit(previous_text, "Undo text edit")
        finally:
            self._suppress_text_edit_logging = False
        return True, "Undo applied."

    def add_to_memory(self, text: str, role: str) -> None:
        """Add a message to memory if enabled."""
        if not self._memory_service:
            return
        if not self._settings_manager.get('MEMORY_AUTO_IMPORT', True):
            return
        
        store_mode = self._settings_manager.get('MEMORY_STORE_MODE', 'all')
        if store_mode == 'user' and role != 'user':
            return
        if store_mode == 'assistant' and role != 'assistant':
            return
        
        try:
            self._memory_service.add_memory(
                text=text,
                role=role,
                conversation_id=self.current_chat_id or 'unsaved',
            )
        except Exception as e:
            print(f"[Memory] Failed to add memory: {e}")

    def query_memory(self, query: str) -> str:
        """Query memory for relevant context."""
        if not self._memory_service:
            return ""
        
        try:
            return self._memory_service.get_context_for_llm(
                query_text=query,
                k=self._settings_manager.get('MEMORY_RETRIEVAL_TOP_K', 5),
                min_score=self._settings_manager.get('MEMORY_MIN_SIMILARITY', 0.3),
                exclude_conversation_id=self.current_chat_id,
            )
        except Exception as e:
            print(f"[Memory] Failed to query memory: {e}")
            return ""

    @property
    def memory_service(self):
        """Access the memory service (may be None if unavailable)."""
        return self._memory_service

    @property
    def document_service(self):
        """Access the document service."""
        return self._document_service

    # -----------------------------------------------------------------------
    # Document management
    # -----------------------------------------------------------------------

    def new_document(self, title: str = "Untitled", content: str = "") -> 'Document':
        """Create a new document."""
        return self._document_service.new_document(title, content)

    def load_document(self, doc_id: str) -> bool:
        """Load a document by ID. Returns True if successful."""
        doc = self._document_service.load_document(doc_id)
        return doc is not None

    def save_document(self) -> Optional[str]:
        """Save the current document. Returns doc_id or None."""
        return self._document_service.save_document()

    def close_document(self) -> None:
        """Close the current document."""
        self._document_service.close_document()

    def apply_document_edit(self, new_content: str, summary: str = "") -> bool:
        """Apply a tool edit to the current document."""
        return self._document_service.apply_tool_edit(new_content, summary)

    def set_document_content(self, content: str) -> bool:
        """Set document content from manual typing (no undo)."""
        return self._document_service.set_content_manual(content)

    def undo_document_edit(self) -> Optional[str]:
        """Undo the last document edit. Returns summary or None."""
        return self._document_service.undo()

    def redo_document_edit(self) -> Optional[str]:
        """Redo the last undone edit. Returns summary or None."""
        return self._document_service.redo()

    def get_document_content(self) -> str:
        """Get current document content."""
        return self._document_service.content

    def set_document_preview_mode(self, enabled: bool) -> bool:
        """Set preview mode for current document."""
        return self._document_service.set_preview_mode(enabled)

    def get_document_preview_mode(self) -> bool:
        """Get preview mode for current document."""
        return self._document_service.get_preview_mode()

    def has_document(self) -> bool:
        """Check if a document is currently loaded."""
        return self._document_service.has_document

    def list_documents(self) -> List[Dict[str, Any]]:
        """List all documents."""
        return self._document_service.list_documents()

    def delete_document(self, doc_id: str) -> bool:
        """Delete a document."""
        return self._document_service.delete_document(doc_id)

    # -----------------------------------------------------------------------
    # Project management
    # -----------------------------------------------------------------------

    def _init_history_repo_for_project(self) -> None:
        """Initialize chat history repository for the current project."""
        from config import HISTORY_DIR

        current_project = self._settings_manager.get('CURRENT_PROJECT', '')
        
        if current_project:
            history_dir = self._projects_repo.get_history_dir(current_project)
        else:
            history_dir = HISTORY_DIR
        
        self._chat_history_repo = ChatHistoryRepository(history_dir=history_dir)
        
        # Update document repository for current project
        from repositories import DocumentRepository
        self._document_repo = DocumentRepository(history_dir=history_dir)
        if hasattr(self, '_document_service'):
            self._document_service._repository = self._document_repo
        
        # Update chat service with new repository
        if hasattr(self, '_chat_service'):
            self._chat_service._history_repo = self._chat_history_repo
        
        # Update modules to use current history dir
        set_ai_history_dir_getter(lambda: history_dir)
        set_utils_history_dir_getter(lambda: history_dir)

    def switch_project(self, project_id: str) -> None:
        """Switch to a different project.
        
        Parameters
        ----------
        project_id : str
            The project ID to switch to, or empty string for default history.
        """
        # Save current project setting
        self._settings_manager.set('CURRENT_PROJECT', project_id)
        self._settings_manager.save()
        
        # Reinitialize history repository
        self._init_history_repo_for_project()
        
        # Clear current chat state
        self.current_chat_id = None
        self.conversation_history = [
            create_system_message(self.system_message)
        ]
        
        # Emit event for UI refresh
        self._event_bus.publish(Event(
            type=EventType.CHAT_CREATED,
            data={'chat_id': '', 'project_switched': True},
            source='controller'
        ))

    def get_current_project(self) -> Optional[str]:
        """Get the current project ID (empty string for default)."""
        return self._settings_manager.get('CURRENT_PROJECT', '')

    def get_current_history_dir(self) -> str:
        """Get the current history directory path."""
        return str(self._chat_history_repo.history_dir)

    def move_chat_to_project(self, chat_id: str, project_id: str) -> bool:
        """Move a chat to a project (or default history if project_id is empty).
        
        Parameters
        ----------
        chat_id : str
            The chat ID to move.
        project_id : str
            The target project ID, or empty string for default history.
            
        Returns
        -------
        bool
            True if successful.
        """
        source_dir = str(self._chat_history_repo.history_dir)
        return self._projects_repo.move_chat_to_project(chat_id, source_dir, project_id)

    def move_document_to_project(self, doc_id: str, project_id: str) -> bool:
        """Move a document to a project (or default history if project_id is empty)."""
        source_dir = str(self._document_repo.history_dir)
        return self._projects_repo.move_document_to_project(doc_id, source_dir, project_id)

    # -----------------------------------------------------------------------
    # System prompts management
    # -----------------------------------------------------------------------

    def _init_system_prompts_from_settings(self) -> None:
        """
        Initialize system prompts from settings.
        
        Merges default prompts (excluding hidden ones) with user-defined prompts.
        Sets up self.system_prompts and self.active_system_prompt_id.
        """
        from config import DEFAULT_SYSTEM_PROMPTS
        
        # Get hidden default prompt IDs
        hidden_raw = self._settings_manager.get('HIDDEN_DEFAULT_PROMPTS', '[]') or "[]"
        try:
            hidden_ids = set(json.loads(hidden_raw))
        except json.JSONDecodeError:
            hidden_ids = set()
        
        # Start with non-hidden default prompts
        prompts = [p.copy() for p in DEFAULT_SYSTEM_PROMPTS if p["id"] not in hidden_ids]
        default_ids = {p["id"] for p in DEFAULT_SYSTEM_PROMPTS}
        
        # Add user-defined prompts (those not in defaults)
        raw = self._settings_manager.get('SYSTEM_PROMPTS_JSON', '') or ""
        if raw.strip():
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    for p in parsed:
                        if isinstance(p, dict) and "id" in p and "name" in p and "content" in p:
                            if p["id"] not in default_ids:
                                prompts.append(p)
            except json.JSONDecodeError:
                pass
        
        self.system_prompts: List[Dict[str, Any]] = prompts
        
        # Determine active prompt ID
        active_id = self._settings_manager.get('ACTIVE_SYSTEM_PROMPT_ID', '') or ""
        valid_ids = {p["id"] for p in self.system_prompts}
        if active_id not in valid_ids:
            active_id = self.system_prompts[0]["id"] if self.system_prompts else ""
        self.active_system_prompt_id = active_id
        
        # Update system_message to the active prompt's content
        active_prompt = self.get_system_prompt_by_id(active_id)
        if active_prompt:
            self.system_message = active_prompt["content"]

    def hide_default_prompt(self, prompt_id: str) -> None:
        """Hide a default prompt (mark as deleted)."""
        from config import DEFAULT_SYSTEM_PROMPTS
        default_ids = {p["id"] for p in DEFAULT_SYSTEM_PROMPTS}
        if prompt_id not in default_ids:
            return  # Not a default prompt
        
        hidden_raw = self._settings_manager.get('HIDDEN_DEFAULT_PROMPTS', '[]') or "[]"
        try:
            hidden_ids = set(json.loads(hidden_raw))
        except json.JSONDecodeError:
            hidden_ids = set()
        
        hidden_ids.add(prompt_id)
        self._settings_manager.set(
            'HIDDEN_DEFAULT_PROMPTS',
            json.dumps(list(hidden_ids)),
            emit_event=False
        )
        self._init_system_prompts_from_settings()

    def init_system_prompts(self) -> None:
        """Public method to initialize system prompts from settings."""
        self._init_system_prompts_from_settings()

    def get_system_prompt_by_id(self, prompt_id: str) -> Optional[Dict[str, Any]]:
        """Return the system prompt dict with the given ID, or None."""
        for p in getattr(self, "system_prompts", []):
            if p["id"] == prompt_id:
                return p
        return None

    def set_active_system_prompt(self, prompt_id: str) -> bool:
        """
        Set the active system prompt by ID.
        
        Returns True if the prompt was found and set, False otherwise.
        """
        prompt = self.get_system_prompt_by_id(prompt_id)
        if not prompt:
            return False
        
        self.active_system_prompt_id = prompt_id
        self.system_message = prompt["content"]
        
        # Update the system message in the current conversation history
        if self.conversation_history and self.conversation_history[0].get("role") == "system":
            self.conversation_history[0]["content"] = prompt["content"]

        self._settings_manager.set('ACTIVE_SYSTEM_PROMPT_ID', prompt_id, emit_event=False)
        self._settings_manager.set('SYSTEM_MESSAGE', prompt["content"], emit_event=False)
        self._settings_manager.save()
        return True

    # -----------------------------------------------------------------------
    # Provider management
    # -----------------------------------------------------------------------

    def initialize_provider(self, provider_name: str, api_key: str) -> Any:
        """
        Initialize and cache a provider when the key changes.
        
        Returns the provider instance, or None if the key was cleared.
        """
        api_key = (api_key or "").strip()
        self.api_keys[provider_name] = api_key

        # If the key was cleared, drop the provider.
        if not api_key:
            self.providers.pop(provider_name, None)
            return None

        # Reuse an existing provider instance when available so caches survive.
        provider = self.providers.get(provider_name)
        if provider is None:
            provider = get_ai_provider(provider_name)

        # Let the provider decide how to handle key changes (e.g., clear caches).
        provider.initialize(api_key)
        self.providers[provider_name] = provider
        return provider

    def initialize_providers_from_env(self) -> None:
        """
        Initialize providers from environment variables and saved keys.
        
        Environment variables take precedence over saved keys.
        """
        env_openai_key = os.environ.get('OPENAI_API_KEY', '').strip()
        env_gemini_key = os.environ.get('GEMINI_API_KEY', '').strip()
        env_grok_key = os.environ.get('GROK_API_KEY', '').strip()
        env_claude_key = (
            os.environ.get('CLAUDE_API_KEY', '').strip()
            or os.environ.get('ANTHROPIC_API_KEY', '').strip()
        )
        env_perplexity_key = os.environ.get('PERPLEXITY_API_KEY', '').strip()

        # Choose the effective key for each provider
        openai_key = env_openai_key or self.api_keys.get('openai', '').strip()
        gemini_key = env_gemini_key or self.api_keys.get('gemini', '').strip()
        grok_key = env_grok_key or self.api_keys.get('grok', '').strip()
        claude_key = env_claude_key or self.api_keys.get('claude', '').strip()
        perplexity_key = env_perplexity_key or self.api_keys.get('perplexity', '').strip()

        if openai_key:
            self.api_keys['openai'] = openai_key
            self.initialize_provider('openai', openai_key)
        if gemini_key:
            self.api_keys['gemini'] = gemini_key
            self.initialize_provider('gemini', gemini_key)
        if grok_key:
            self.api_keys['grok'] = grok_key
            self.initialize_provider('grok', grok_key)
        if claude_key:
            self.api_keys['claude'] = claude_key
            os.environ['CLAUDE_API_KEY'] = claude_key
            os.environ['ANTHROPIC_API_KEY'] = claude_key
            self.initialize_provider('claude', claude_key)
        if perplexity_key:
            self.api_keys['perplexity'] = perplexity_key
            self.initialize_provider('perplexity', perplexity_key)

    def get_default_models_for_provider(self, provider_name: str) -> List[str]:
        """Return default models for a provider when the API is unavailable."""
        if provider_name == 'gemini':
            return ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-3-pro-preview"]
        if provider_name == 'grok':
            return ["grok-2", "grok-2-mini", "grok-2-image-1212"]
        if provider_name == 'claude':
            return ["claude-sonnet-4-5", "claude-3-5-sonnet-latest"]
        if provider_name == 'perplexity':
            return ["sonar", "sonar-pro", "sonar-reasoning"]
        return ["gpt-3.5-turbo", "gpt-4", "gpt-4o-mini"]

    # -----------------------------------------------------------------------
    # Chat lifecycle
    # -----------------------------------------------------------------------

    def new_chat(self, system_message: Optional[str] = None) -> None:
        """Reset the conversation for a new chat."""
        self.current_chat_id = None
        msg = system_message if system_message is not None else self.system_message
        self.conversation_history = [create_system_message(msg)]
        self.current_chat_metadata = {}
        self._pending_text_edit_events = []
        self._text_edit_history_by_message = {}
        self._event_bus.publish(Event(
            type=EventType.CHAT_CREATED,
            data={'system_message': msg},
            source='controller'
        ))

    def update_system_message(self, content: str) -> None:
        """Update the system message in the current conversation."""
        if not self.conversation_history:
            self.conversation_history = [create_system_message(content)]
            return

        if self.conversation_history[0].get("role") != "system":
            self.conversation_history.insert(0, create_system_message(content))
            return

        self.conversation_history[0]["content"] = content

    def delete_message(self, index: int) -> bool:
        """Delete message at index. Returns True if successful."""
        if 0 < index < len(self.conversation_history):  # Don't delete system message
            del self.conversation_history[index]
            self._event_bus.publish(Event(
                type=EventType.MESSAGE_DELETED,
                data={'index': index},
                source='controller'
            ))
            return True
        return False

    def add_notification(self, content: str, notification_type: str = 'info') -> int:
        """Add a notification message (cancel, error, etc.) as assistant message."""
        msg = create_assistant_message(content)
        if "provider_meta" not in msg:
            msg["provider_meta"] = {}
        msg["provider_meta"]["is_notification"] = True
        msg_index = len(self.conversation_history)
        self.conversation_history.append(msg)
        return msg_index

    def get_message_count(self) -> int:
        """Get the number of messages in conversation history."""
        return len(self.conversation_history)

    def get_last_user_content(self) -> Optional[str]:
        """Get content of the last user message, for chat name generation."""
        for msg in reversed(self.conversation_history):
            if msg.get('role') == 'user':
                return msg.get('content', '')
        return None

    def load_chat(self, chat_id: str) -> bool:
        """
        Load a chat from disk by its ID (filename without .json).
        
        Returns True if successful, False otherwise.
        """
        try:
            # Use chat service to load chat
            conv_history = self._chat_service.load_chat(chat_id)
            if conv_history:
                self.conversation_history = conv_history.to_list()
                self.current_chat_id = chat_id
                self.current_chat_metadata = conv_history.metadata or {}
                self._text_edit_history_by_message = {}
                for idx, message in enumerate(self.conversation_history):
                    events = message.get("text_edit_events")
                    if events:
                        self._text_edit_history_by_message[idx] = list(events)
                return True
        except Exception as e:
            print(f"Error loading chat {chat_id}: {e}")
        return False

    def save_current_chat(self, metadata: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """
        Save the current conversation history.
        
        If this is a new chat, generates a name based on the first user message.
        Returns the chat_id (filename) or None on error.
        """
        if not self.conversation_history:
            return None
        
        try:
            # Use existing ID or generate new one
            chat_id = self.current_chat_id
            if not chat_id:
                # Generate a temporary ID that will be replaced by service
                from datetime import datetime
                chat_id = f"new_chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Convert to ConversationHistory and save via service
            merged_metadata = dict(self.current_chat_metadata)
            if metadata:
                merged_metadata.update(metadata)
            conv_history = ConversationHistory.from_list(self.conversation_history, metadata=merged_metadata)
            actual_chat_id = self._chat_service.save_chat(chat_id, conv_history)
            self.current_chat_id = actual_chat_id
            self.current_chat_metadata = merged_metadata
            return actual_chat_id
        except Exception as e:
            print(f"Error saving chat: {e}")
            import traceback
            traceback.print_exc()
            return None

    def list_chats(self) -> List[Dict[str, Any]]:
        """List all available chats via service."""
        return self._chat_service.list_chats()

    def delete_chat(self, chat_id: str) -> bool:
        """Delete a chat via service, including associated memories."""
        # Delete memories for this conversation if memory service is available
        if self._memory_service:
            try:
                deleted = self._memory_service.delete_conversation_memories(chat_id)
                if deleted:
                    print(f"[Memory] Deleted {deleted} memories for chat {chat_id}")
            except Exception as e:
                print(f"[Memory] Error deleting memories for chat {chat_id}: {e}")
        
        return self._chat_service.delete_chat(chat_id)

    def search_history(self, query: str, limit: int = 10, context_window: int = 200) -> List[Dict[str, Any]]:
        """Search chat histories via service."""
        return self._chat_service.search_history(query, limit, exclude_chat_id=self.current_chat_id, context_window=context_window)

    # -----------------------------------------------------------------------
    # Tool handlers (UI-agnostic implementations)
    # -----------------------------------------------------------------------

    def handle_image_tool(self, prompt: str, image_path: Optional[str] = None) -> str:
        """
        Handle image generation tool calls.
        
        Parameters
        ----------
        prompt : str
            The image generation prompt.
        image_path : Optional[str]
            Path to source image for editing.
            
        Returns
        -------
        str
            Result message or image tag.
        """
        import base64
        
        preferred_model = self._settings_manager.get('IMAGE_MODEL', 'dall-e-3') or 'dall-e-3'
        provider_name = self.get_provider_name_for_model(preferred_model)
        
        # Verify model is valid for image generation
        is_standard = self._tool_service.is_image_model(preferred_model, provider_name, self.custom_models)
        is_custom = provider_name == "custom" and preferred_model in (self.custom_models or {})
        
        if not is_standard and not is_custom:
            preferred_model = "dall-e-3"
            provider_name = "openai"
        
        # Prepare image data for editing
        image_data = None
        mime_type = None
        if image_path:
            try:
                with open(image_path, "rb") as f:
                    image_data = base64.b64encode(f.read()).decode("utf-8")
                mime_type = "image/png"
            except Exception as e:
                print(f"[Image Tool] Error loading image: {e}")
        
        # Also check last message for attached images
        last_msg = self.conversation_history[-1] if self.conversation_history else {}
        if not image_data and last_msg.get("images"):
            img = last_msg["images"][0]
            if img.get("data"):
                image_data = img.get("data")
            elif img.get("path"):
                try:
                    with open(img["path"], "rb") as f:
                        image_data = base64.b64encode(f.read()).decode("utf-8")
                except Exception:
                    pass
            mime_type = img.get("mime_type", "image/png")
        
        provider = self.get_provider_for_model(preferred_model)
        if not provider:
            raise ValueError(f"{provider_name.title()} provider is not initialized")
        
        try:
            return self._image_service.generate_image(
                prompt=prompt,
                model=preferred_model,
                provider=provider,
                provider_name=provider_name,
                chat_id=self.current_chat_id or "temp",
                image_data=image_data,
                mime_type=mime_type,
            )
        except Exception as e:
            # Fallback to dall-e-3
            print(f"[Image Tool] Preferred model failed: {e}, falling back to dall-e-3")
            provider = self.get_provider_for_model("dall-e-3")
            return self._image_service.generate_image(
                prompt=prompt,
                model="dall-e-3",
                provider=provider,
                provider_name="openai",
                chat_id=self.current_chat_id or "temp",
            )

    def handle_search_tool(self, keyword: str, source: str = "history") -> str:
        """
        Handle search/memory tool calls.
        
        Parameters
        ----------
        keyword : str
            The search keyword.
        source : str
            Where to search: 'history', 'documents', or 'all'.
            
        Returns
        -------
        str
            Search results formatted for the model.
        """
        import re
        import os
        import glob
        
        if not keyword:
            return "No keyword provided for search."
        
        keyword = keyword.strip()
        source = (source or "history").strip().lower()
        
        search_history_enabled = self._settings_manager.get('SEARCH_HISTORY_ENABLED', True)
        search_directories = self._settings_manager.get('SEARCH_DIRECTORIES', '') or ''
        result_limit = max(1, min(5, int(self._settings_manager.get('SEARCH_RESULT_LIMIT', 1))))
        context_window = max(50, min(500, int(self._settings_manager.get('SEARCH_CONTEXT_WINDOW', 200))))
        show_results = self._settings_manager.get('SEARCH_SHOW_RESULTS', False)
        
        # Pattern with optional plural 's'
        pattern = re.compile(r'\b' + re.escape(keyword) + r's?\b', re.IGNORECASE)
        results = []
        
        # Search history - pass context_window to repository
        if search_history_enabled and source in ("history", "all"):
            search_results = self.search_history(keyword, result_limit, context_window)
            for sr in search_results:
                matches_text = "\n".join(sr.get('matches', [])[:3])
                results.append({
                    "source": f"Chat: {sr.get('chat_title', sr.get('chat_id', 'Unknown'))}",
                    "content": matches_text
                })
        
        # Search directories
        if source in ("documents", "all") and search_directories:
            dirs = [d.strip() for d in search_directories.split(",") if d.strip()]
            for directory in dirs:
                if len(results) >= result_limit:
                    break
                if not os.path.isdir(directory):
                    continue
                for ext in ["*.txt", "*.md", "*.json", "*.log", "*.csv"]:
                    if len(results) >= result_limit:
                        break
                    for filepath in glob.glob(os.path.join(directory, "**", ext), recursive=True):
                        if len(results) >= result_limit:
                            break
                        try:
                            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                                content = f.read()
                            match = pattern.search(content)
                            if match:
                                # Extract context around match
                                start = max(0, match.start() - context_window)
                                end = min(len(content), match.end() + context_window)
                                snippet = content[start:end]
                                if start > 0:
                                    snippet = '...' + snippet
                                if end < len(content):
                                    snippet = snippet + '...'
                                results.append({
                                    "source": filepath,
                                    "content": snippet
                                })
                        except Exception:
                            pass
        
        results = results[:result_limit]
        
        if not results:
            return f"No results found for '{keyword}'."
        
        formatted = []
        for i, result in enumerate(results, 1):
            formatted.append(f"--- Result {i} ---\nSource: {result['source']}\n{result['content']}")
        
        result_text = f"Found {len(results)} result(s) for '{keyword}':\n\n" + "\n\n".join(formatted)
        
        if not show_results:
            return "__HIDE_TOOL_RESULT__" + result_text
        return result_text

    def handle_music_tool(self, action: str, keyword: Optional[str] = None, volume: Optional[float] = None) -> str:
        """
        Handle music control tool calls.
        
        Parameters
        ----------
        action : str
            The action: play, pause, resume, stop, next, previous, volume_up, volume_down, set_volume.
        keyword : Optional[str]
            Beets query string for 'play' action.
        volume : Optional[float]
            Volume level for 'set_volume' action (0-100).
            
        Returns
        -------
        str
            Result message.
        """
        import subprocess
        import tempfile
        import threading
        
        action = (action or "").strip().lower()
        if not action:
            return "Error: music control action is required."
        
        player_path = self._settings_manager.get('MUSIC_PLAYER_PATH', '/usr/bin/mpv') or '/usr/bin/mpv'
        
        if action == "play":
            if not keyword or not keyword.strip():
                return "Error: 'play' action requires a beets query string."
            
            try:
                lib = self._get_beets_library()
            except RuntimeError as e:
                return f"Error: {e}"
            
            query = keyword.strip()
            try:
                import unicodedata
                import re
                
                def strip_diacritics(s):
                    return ''.join(c for c in unicodedata.normalize('NFD', s) 
                                  if unicodedata.category(c) != 'Mn').lower()
                
                # Map standard fields to normalized versions
                field_map = {
                    'artist': 'artist_norm', 'albumartist': 'artist_norm',
                    'title': 'title_norm', 'album': 'album_norm'
                }
                
                # Parse and convert field:value pairs to normalized versions
                def normalize_query(q):
                    parts = []
                    for part in re.split(r'\s+(or|and|,)\s+', q, flags=re.IGNORECASE):
                        if part.lower() in ('or', 'and', ','):
                            parts.append(',')
                            continue
                        match = re.match(r'(\w+):"?([^"]+)"?', part)
                        if match:
                            field, value = match.groups()
                            norm_field = field_map.get(field.lower(), f'{field}_norm')
                            parts.append(f'{norm_field}:{strip_diacritics(value)}')
                        else:
                            # Plain text - search all normalized fields
                            norm_val = strip_diacritics(part)
                            parts.append(f'artist_norm:{norm_val} , title_norm:{norm_val} , album_norm:{norm_val}')
                    return ' '.join(parts)
                
                # Always try normalized search first (catches all diacritic variants)
                norm_query = normalize_query(query)
                items = list(lib.items(norm_query))
                
                # Fallback to exact query if normalized found nothing
                if not items:
                    items = list(lib.items(query))
                
                # Try fuzzy on normalized as last resort
                if not items:
                    fuzzy_query = re.sub(r':(\S+)', r':\1~', norm_query)
                    items = list(lib.items(fuzzy_query))
            except Exception as e:
                return f"Error querying beets library: {e}"
            
            if not items:
                return f"No tracks found matching query: {query}"
            max_tracks = 100
            limited_msg = ""
            if len(items) > max_tracks:
                items = items[:max_tracks]
                limited_msg = f" (limited to first {max_tracks} tracks)"
            
            # Create playlist
            try:
                import os
                playlist_fd, playlist_path = tempfile.mkstemp(suffix=".m3u", prefix="chatgtk_music_")
                with os.fdopen(playlist_fd, 'w', encoding='utf-8') as f:
                    f.write("#EXTM3U\n")
                    for item in items:
                        path = item.path
                        if isinstance(path, bytes):
                            path = path.decode('utf-8', errors='replace')
                        f.write(f"{path}\n")
            except Exception as e:
                return f"Error creating playlist: {e}"
            
            # Launch player
            try:
                import shlex
                import os
                parts = shlex.split(player_path)
                if "<playlist>" in player_path:
                    cmd = [p.replace("<playlist>", playlist_path) for p in parts]
                else:
                    cmd = parts + [playlist_path]
                
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
                def cleanup():
                    proc.wait()
                    try:
                        os.unlink(playlist_path)
                    except Exception:
                        pass
                threading.Thread(target=cleanup, daemon=True).start()
                
                return f"Started playing {len(items)} track(s) matching '{query}'{limited_msg}"
            except FileNotFoundError:
                try:
                    import os
                    os.unlink(playlist_path)
                except Exception:
                    pass
                return f"Error: Music player not found at '{player_path}'."
            except Exception as e:
                try:
                    import os
                    os.unlink(playlist_path)
                except Exception:
                    pass
                return f"Error starting music player: {e}"
        
        # Non-play actions via playerctl
        import os
        player_name = os.path.basename(str(player_path).strip().split()[0])
        
        if action in ("pause", "resume", "stop", "next", "previous", "volume_up", "volume_down", "set_volume"):
            try:
                subprocess.run(["playerctl", "--version"], capture_output=True, check=True)
            except (FileNotFoundError, subprocess.CalledProcessError):
                return f"Action '{action}' requires playerctl for MPRIS control."
            
            base_cmd = ["playerctl", "-p", player_name]
            
            cmd_map = {
                "pause": (["pause"], "Paused playback."),
                "resume": (["play"], "Resumed playback."),
                "stop": (["stop"], "Stopped playback."),
                "next": (["next"], "Skipped to next track."),
                "previous": (["previous"], "Went back to previous track."),
                "volume_up": (["volume", "0.05+"], "Increased volume."),
                "volume_down": (["volume", "0.05-"], "Decreased volume."),
            }
            
            if action == "set_volume":
                if volume is None:
                    return "Error: 'set_volume' requires a volume value (0-100)."
                try:
                    vol = float(volume)
                except (TypeError, ValueError):
                    return "Error: volume must be a number."
                if vol > 1.0:
                    vol = vol / 100.0
                vol = max(0.0, min(1.0, vol))
                cmd = base_cmd + ["volume", f"{vol:.2f}"]
                success_msg = f"Set volume to {int(vol * 100)}%."
            else:
                args, success_msg = cmd_map[action]
                cmd = base_cmd + args
            
            try:
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    return f"Error: {result.stderr or result.stdout or 'Unknown error'}"
                return success_msg
            except Exception as e:
                return f"Error controlling playback: {e}"
        
        return f"Error: unsupported action '{action}'."

    def _get_beets_library(self):
        """Get a beets Library instance based on settings."""
        try:
            from beets.library import Library
        except ImportError:
            raise RuntimeError("beets library not installed. Install with: pip install beets")
        
        library_db = self._settings_manager.get('MUSIC_LIBRARY_DB', '') or ''
        library_dir = self._settings_manager.get('MUSIC_LIBRARY_DIR', '') or ''
        
        if library_db:
            import os
            if not os.path.exists(library_db):
                raise RuntimeError(f"Beets library not found at: {library_db}")
            return Library(library_db, directory=library_dir if library_dir else None)
        
        # Check for app-generated library
        from config import PARENT_DIR
        import os
        app_library_db = os.path.join(PARENT_DIR, "music_library.db")
        if os.path.exists(app_library_db):
            return Library(app_library_db, directory=library_dir if library_dir else None)
        
        # Try beets default config
        try:
            from beets import config as beets_config
            beets_config.read(user=True, defaults=True)
            default_db = beets_config['library'].get()
            default_dir = beets_config['directory'].get()
            return Library(default_db, directory=library_dir or default_dir)
        except Exception as e:
            raise RuntimeError(f"Could not load beets library: {e}")

    # -----------------------------------------------------------------------
    # Message preparation
    # -----------------------------------------------------------------------

    def get_conversation_buffer_limit(self) -> Optional[int]:
        """
        Return the configured conversation buffer length as an integer.
        
        Returns:
            None: send the full conversation history (ALL).
            0: send only the latest non-system message.
            N>0: send the last N non-system messages.
        """
        raw = getattr(self, "conversation_buffer_length", None)
        if raw is None:
            return None

        if isinstance(raw, (int, float)):
            value = int(raw)
            return max(value, 0)

        text = str(raw).strip()
        if not text or text.upper() == "ALL":
            return None

        try:
            value = int(text)
            return max(value, 0)
        except ValueError:
            return None

    def apply_conversation_buffer_limit(self, history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Apply the configured conversation buffer length to the given history.
        
        The system message (first entry) is always preserved when present.
        """
        if not history:
            return history

        limit = self.get_conversation_buffer_limit()
        if limit is None or len(history) <= 1:
            return history

        first = history[0]
        non_system = history[1:]
        if not non_system:
            return history

        if limit == 0:
            trimmed = [non_system[-1]]
        else:
            trimmed = non_system[-limit:]

        return [first] + trimmed

    def messages_for_model(self, model_name: str) -> List[Dict[str, Any]]:
        """
        Return the conversation history with tool guidance and memory context appended for chat models.
        """
        if not self.conversation_history:
            return []

        # For non-chat-completion models, skip extra system guidance
        if not is_chat_completion_model(model_name, self.custom_models):
            return self.apply_conversation_buffer_limit(self.conversation_history)

        # New retrieval flow:
        # 1. Get base history (compacted or full)
        # 2. Extract system prompt, apply tool guidance, memory, and compaction summary.
        
        compacted_history, compaction_summary = self._apply_compaction_view(self.conversation_history)
        limited_history = self.apply_conversation_buffer_limit(compacted_history)
        
        # Filter out notification messages
        limited_history = [
            m for m in limited_history 
            if not m.get("provider_meta", {}).get("is_notification", False)
        ]
        
        if not limited_history:
             return []

        first_message = limited_history[0]
        if first_message.get("role") != "system":
             return limited_history

        current_prompt = first_message.get("content", "") or ""
        if compaction_summary:
            current_prompt += (
                f"\n\n### Previous Conversation Summary\n{compaction_summary}\n"
                f"### Current Conversation\n(The conversation continues below...)"
            )
        
        # Add document mode guidance if in document mode
        if self.has_document() and "document" in self._text_targets:
            from config import DEFAULT_DOCUMENT_MODE_PROMPT_APPENDIX
            current_prompt = current_prompt + "\n\n" + DEFAULT_DOCUMENT_MODE_PROMPT_APPENDIX

        # Get enabled tools for this model and append guidance
        try:
            enabled_tools = self.tool_manager.get_enabled_tools_for_model(
                model_name, self.model_provider_map, self.custom_models
            )
            if self.tool_manager.text_edit_tool_enabled and self.has_text_targets():
                enabled_tools.update({"text_get", "apply_text_edit"})
            new_prompt = append_tool_guidance(
                current_prompt,
                enabled_tools,
                include_math=True,
                settings_manager=self._settings_manager
            )
        except Exception as e:
            print(f"Error while appending tool guidance: {e}")
            new_prompt = current_prompt

        # Query memory for relevant context
        memory_context = self._get_memory_context_for_query()
        
        if new_prompt == current_prompt and not memory_context:
            return limited_history

        messages = [msg.copy() for msg in limited_history]
        messages[0]["content"] = new_prompt
        
        # Inject memory context as second message (after system prompt)
        if memory_context:
            memory_appendix = self._settings_manager.get('MEMORY_PROMPT_APPENDIX', '')
            memory_message = {
                "role": "system",
                "content": f"{memory_appendix}\n\n{memory_context}" if memory_appendix else memory_context
            }
            messages.insert(1, memory_message)
            print(f"[Memory] Injected context into conversation")
        
        return messages

    def _get_memory_context_for_query(self) -> str:
        """Get memory context based on recent conversation."""
        if not self._memory_service:
            return ""
        
        if not self._settings_manager.get('MEMORY_ENABLED', False):
            return ""
        
        # Build query from last few messages for better context
        query_parts = []
        msg_count = 0
        for msg in reversed(self.conversation_history):
            role = msg.get("role", "")
            if role == "system":
                continue
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = [p.get("text", "") for p in content if p.get("type") == "text"]
                content = " ".join(text_parts)
            if content:
                query_parts.insert(0, content)
                msg_count += 1
                if msg_count >= 3:  # Last 3 messages for context
                    break
        
        if not query_parts:
            return ""
        
        # Combine recent messages, prioritizing the last user message
        query_text = " ".join(query_parts)[-1000:]  # Limit query length
        
        try:
            context = self._memory_service.get_context_for_llm(
                query_text=query_text,
                k=self._settings_manager.get('MEMORY_RETRIEVAL_TOP_K', 5),
                min_score=self._settings_manager.get('MEMORY_MIN_SIMILARITY', 0.5),
                exclude_conversation_id=self.current_chat_id,
            )
            if context:
                print(f"[Memory] Found relevant memories for query: {query_text[:80]}...")
            return context
        except Exception as e:
            print(f"[Memory] Error querying memory: {e}")
            return ""

    def _apply_compaction_view(self, history: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], Optional[str]]:
        """
        Return (history_view, summary_text).
        
        If a compaction is found:
            - history_view contains [SystemMsg] + [Messages After Compaction]
            - summary_text contains the summary
        Else:
            - history_view is original history
            - summary_text is None
        """
        if not history:
            return history, None
        
        # Search backwards for compaction data
        # 'history' is list of dicts here
        compaction_data = None
        cutoff_index = -1
        
        # history length L. indices 0..L-1.
        for i in range(len(history) - 1, -1, -1):
            msg = history[i]
            meta = msg.get("provider_meta", {})
            if isinstance(meta, dict) and meta.get("compacted_data"):
                compaction_data = meta["compacted_data"]
                cutoff_index = i
                break
        
        if compaction_data and cutoff_index >= 0:
            # Reconstruct: System Msg + Messages after compaction point
            system_msg = history[0] if history[0].get("role") == "system" else None
            post_compaction = history[cutoff_index + 1:]
            
            new_history = []
            if system_msg:
                new_history.append(system_msg)
            
            new_history.extend(post_compaction)
            
            return new_history, compaction_data.get("summary")
            
        return history, None

    # -----------------------------------------------------------------------
    # Service accessors
    # -----------------------------------------------------------------------

    @property
    def chat_service(self) -> ChatService:
        """Get the chat service instance."""
        return self._chat_service
    
    @property
    def image_service(self) -> ImageGenerationService:
        """Get the image generation service instance."""
        return self._image_service
    
    @property
    def audio_service(self) -> AudioService:
        """Get the audio service instance."""
        return self._audio_service
    
    @property
    def tool_service(self) -> ToolService:
        """Get the tool service instance."""
        return self._tool_service

    # -----------------------------------------------------------------------
    # High-level orchestration methods
    # -----------------------------------------------------------------------

    def get_provider_for_model(self, model: str) -> Optional[Any]:
        """
        Get or initialize the appropriate provider for a model.
        
        Parameters
        ----------
        model : str
            The model identifier.
            
        Returns
        -------
        Optional[Any]
            The provider instance, or None if unavailable.
        """
        provider_name = self.get_provider_name_for_model(model)
        
        # Check for custom provider
        if provider_name == "custom":
            provider = self.custom_providers.get(model)
            if provider:
                return provider
            # Initialize custom provider
            config = (self.custom_models or {}).get(model, {})
            if not config:
                return None
            from utils import resolve_api_key
            provider = get_ai_provider("custom")
            provider.initialize(
                api_key=resolve_api_key(config.get("api_key", "")).strip(),
                endpoint=config.get("endpoint"),
                model_id=model,
                api_type=config.get("api_type", "chat.completions"),
            )
            self.custom_providers[model] = provider
            return provider
        
        # Check cached provider
        if provider_name in self.providers:
            return self.providers[provider_name]
        
        # Get API key and initialize
        api_key = self._get_api_key_for_provider(provider_name)
        if not api_key:
            return None
        
        return self.initialize_provider(provider_name, api_key)

    def get_provider(self, provider_name: str) -> Optional[Any]:
        """
        Get or initialize a provider by name.
        
        Parameters
        ----------
        provider_name : str
            The provider name ('openai', 'gemini', 'grok', 'claude', 'perplexity').
            
        Returns
        -------
        Optional[Any]
            The provider instance, or None if unavailable.
        """
        if provider_name in self.providers:
            return self.providers[provider_name]
        
        api_key = self._get_api_key_for_provider(provider_name)
        if not api_key:
            return None
        
        return self.initialize_provider(provider_name, api_key)

    def _get_api_key_for_provider(self, provider_name: str) -> Optional[str]:
        """Get API key for a provider from env or saved keys."""
        env_map = {
            'openai': 'OPENAI_API_KEY',
            'gemini': 'GEMINI_API_KEY',
            'grok': 'GROK_API_KEY',
            'claude': 'CLAUDE_API_KEY',
            'perplexity': 'PERPLEXITY_API_KEY',
        }
        env_var = env_map.get(provider_name, f'{provider_name.upper()}_API_KEY')
        return os.environ.get(env_var, '').strip() or self.api_keys.get(provider_name, '').strip()

    def get_provider_name_for_model(self, model: str) -> str:
        """
        Determine which provider handles a given model.
        
        Uses model cards as the single source of truth, with fallback heuristics.
        
        Parameters
        ----------
        model : str
            The model identifier.
            
        Returns
        -------
        str
            The provider name ('openai', 'gemini', 'grok', 'claude', 'perplexity', 'custom').
        """
        from model_cards import get_card
        
        if not model:
            return 'openai'
        
        # Model card is the single source of truth
        card = get_card(model, self.custom_models)
        if card:
            return card.provider
        
        # Fallback: check model_provider_map (from API fetch)
        if model in self.model_provider_map:
            return self.model_provider_map[model]
        
        # Check custom models
        if model in (self.custom_models or {}):
            return "custom"
        
        # Fallback heuristics for unknown models
        model_lower = model.lower()
        if 'claude' in model_lower:
            return 'claude'
        if 'gemini' in model_lower:
            return 'gemini'
        if 'grok' in model_lower:
            return 'grok'
        if 'sonar' in model_lower:
            return 'perplexity'
        
        return 'openai'

    def prepare_message(
        self,
        content: str,
        images: Optional[List[Dict[str, Any]]] = None,
        files: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Prepare a user message for the conversation.
        
        Parameters
        ----------
        content : str
            The message content.
        images : Optional[List[Dict]]
            List of image attachments.
        files : Optional[List[Dict]]
            List of file attachments.
            
        Returns
        -------
        Dict[str, Any]
            The prepared message dictionary.
        """
        return create_user_message(content, images=images, files=files)

    def add_user_message(
        self,
        content: str,
        images: Optional[List[Dict[str, Any]]] = None,
        files: Optional[List[Dict[str, Any]]] = None,
        display_content: Optional[str] = None,
    ) -> int:
        """
        Add a user message to the conversation history.
        
        Parameters
        ----------
        content : str
            The message content.
        images : Optional[List[Dict]]
            List of image attachments.
        files : Optional[List[Dict]]
            List of file attachments.
        display_content : Optional[str]
            Alternative content for display (e.g., with attachment info).
            
        Returns
        -------
        int
            The index of the added message.
        """
        msg = self.prepare_message(content, images, files)
        if display_content and display_content != content:
            msg["display_content"] = display_content
        msg_index = len(self.conversation_history)
        self.conversation_history.append(msg)
        
        # Auto-assign chat ID on first user message
        if self.current_chat_id is None and msg_index == 1:
            from utils import generate_chat_name
            self.current_chat_id = generate_chat_name(content)
        
        self._event_bus.publish(Event(
            type=EventType.MESSAGE_SENT,
            data={
                'content': display_content or content,
                'index': msg_index,
                'role': 'user'
            },
            source='controller'
        ))
        
        # Add to memory if enabled
        self.add_to_memory(content, 'user')
        
        return msg_index

    def add_assistant_message(self, content: str) -> int:
        """
        Add an assistant message to the conversation history.
        
        Parameters
        ----------
        content : str
            The message content.
            
        Returns
        -------
        int
            The index of the added message.
        """
        msg = create_assistant_message(content)
        if self._pending_text_edit_events:
            msg["text_edit_events"] = list(self._pending_text_edit_events)
        msg_index = len(self.conversation_history)
        self.conversation_history.append(msg)
        if self._pending_text_edit_events:
            self._text_edit_history_by_message[msg_index] = list(self._pending_text_edit_events)
            self._pending_text_edit_events = []
        
        self._event_bus.publish(Event(
            type=EventType.MESSAGE_RECEIVED,
            data={'content': content, 'index': msg_index, 'role': 'assistant'},
            source='controller'
        ))
        
        # Add to memory if enabled
        self.add_to_memory(content, 'assistant')
        
        return msg_index

    def get_preferred_image_model(self) -> str:
        """Get the user's preferred image generation model."""
        return self._settings_manager.get('IMAGE_MODEL', 'dall-e-3') or 'dall-e-3'

    def get_temperature_for_model(self, model: str) -> Optional[float]:
        """
        Get the appropriate temperature setting for a model.
        
        Some models (like o1, o3) don't support temperature.
        """
        from model_cards import get_card
        
        card = get_card(model, self.custom_models)
        if card and card.quirks.get('no_temperature'):
            return None
        if card and card.temperature is not None:
            return float(card.temperature)
        return None

    def ensure_chat_id(self) -> str:
        """
        Ensure a chat ID exists, creating one if necessary.
        
        Returns
        -------
        str
            The current or newly created chat ID.
        """
        if self.current_chat_id is None and len(self.conversation_history) > 1:
            # Generate from first user message
            from utils import generate_chat_name
            first_user = next(
                (m for m in self.conversation_history if m.get('role') == 'user'),
                None
            )
            if first_user:
                self.current_chat_id = generate_chat_name(first_user.get('content', ''))
            else:
                from datetime import datetime
                self.current_chat_id = f"chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        return self.current_chat_id

    # -----------------------------------------------------------------------
    # Message sending (main API call flow)
    # -----------------------------------------------------------------------

    def send_message(
        self,
        model: str,
        tool_handlers: Optional[Dict[str, Callable]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        """
        Send the last user message to the AI and emit response via events.
        
        This is the main entry point for AI requests. It handles:
        - Provider selection and initialization
        - Image model routing
        - Message preparation
        - Tool handler wiring
        - Response processing
        
        Results are emitted via MESSAGE_RECEIVED or ERROR_OCCURRED events.
        
        Parameters
        ----------
        model : str
            The model to use for generation.
        tool_handlers : Optional[Dict[str, Callable]]
            Tool handler functions (image_tool_handler, music_tool_handler, etc.)
        cancel_check : Optional[Callable[[], bool]]
            Function that returns True if request should be cancelled.
        """
        from model_cards import get_card
        from markup_utils import format_response
        
        def is_cancelled():
            return cancel_check() if cancel_check else False
        
        try:
            # Emit thinking started
            self._event_bus.publish(Event(
                type=EventType.THINKING_STARTED,
                data={'model': model},
                source='controller'
            ))
            
            if is_cancelled():
                return
            
            # Ensure valid model
            if not model:
                model = "gpt-3.5-turbo"
            
            provider_name = self.get_provider_name_for_model(model)
            
            if is_cancelled():
                return
            
            # Get or initialize provider
            provider = self._get_or_init_provider(model, provider_name)
            
            last_msg = self.conversation_history[-1]
            prompt = last_msg.get("content", "")
            has_attached_images = bool(last_msg.get("images"))
            
            # Check for image model
            card = get_card(model, self.custom_models)
            is_image_model = card and card.capabilities.image_gen and not card.capabilities.text
            
            if is_image_model:
                # Route to image generation
                answer = self._image_service.generate_image(
                    prompt=prompt,
                    model=model,
                    provider=provider,
                    provider_name=provider_name,
                    chat_id=self.current_chat_id or "temp",
                    edit_image=last_msg.get("images", [None])[0] if has_attached_images else None,
                )
                assistant_provider_meta = None
            else:
                # Check for realtime models
                if card and card.api_family == "realtime":
                    return
                
                # Prepare messages
                messages_to_send = self.messages_for_model(model)
                if provider_name == 'perplexity':
                    messages_to_send = self._clean_messages_for_perplexity(messages_to_send)
                
                # Build kwargs
                response_meta = {}
                kwargs = {
                    "messages": messages_to_send,
                    "model": model,
                    "temperature": self.get_temperature_for_model(model),
                    "max_tokens": self._settings_manager.get('MAX_TOKENS', 0) or None,
                    "chat_id": self.current_chat_id,
                }
                
                # Add tool handlers and web search for non-perplexity
                if provider_name != 'perplexity':
                    kwargs["web_search_enabled"] = self._settings_manager.get('WEB_SEARCH_ENABLED', False)
                    if tool_handlers:
                        kwargs.update(tool_handlers)
                
                # Add response_meta for providers that use it
                if provider_name in ('gemini', 'perplexity', 'claude'):
                    kwargs["response_meta"] = response_meta
                
                if is_cancelled():
                    return
                
                # Call provider
                answer = provider.generate_chat_completion(**kwargs)
                assistant_provider_meta = response_meta if response_meta else None
                
                # Append Perplexity sources
                if provider_name == 'perplexity':
                    answer = self._append_perplexity_sources(answer, response_meta)
            
            if is_cancelled():
                return
            
            # Normalize image tags
            answer = self._normalize_image_tags(answer)
            
            # Add to conversation history
            assistant_message = create_assistant_message(answer, provider_meta=assistant_provider_meta)
            if self._pending_text_edit_events:
                assistant_message["text_edit_events"] = list(self._pending_text_edit_events)
                print(f"[TextEditTool] Saving {len(self._pending_text_edit_events)} edit events to message")
            message_index = len(self.conversation_history)
            self.conversation_history.append(assistant_message)
            if self._pending_text_edit_events:
                self._text_edit_history_by_message[message_index] = list(self._pending_text_edit_events)
                self._pending_text_edit_events = []
            
            # Add to memory if enabled
            self.add_to_memory(answer, 'assistant')
            
            # Store model in system message (first message)
            if self.conversation_history:
                self.conversation_history[0]['model'] = model
            
            # Save chat
            self.save_current_chat()
            
            # Emit response
            self._event_bus.publish(Event(
                type=EventType.MESSAGE_RECEIVED,
                data={
                    'content': answer,
                    'formatted_content': format_response(answer),
                    'index': message_index,
                    'model': model,
                    'provider_meta': assistant_provider_meta,
                },
                source='controller'
            ))
            
        except Exception as error:
            if not is_cancelled():
                error_message = f"** Error: {str(error)} **"
                message_index = len(self.conversation_history)
                self.conversation_history.append(create_assistant_message(error_message))
                
                self._event_bus.publish(Event(
                    type=EventType.ERROR_OCCURRED,
                    data={'error': str(error), 'context': 'send_message', 'index': message_index},
                    source='controller'
                ))
        finally:
            self._event_bus.publish(Event(
                type=EventType.THINKING_STOPPED,
                data={},
                source='controller'
            ))
            
            # Post-response maintenance
            self._check_and_perform_compaction()

    def _get_or_init_provider(self, model: str, provider_name: str) -> Any:
        """Get or initialize a provider for the given model."""
        if provider_name == "custom":
            provider = self.custom_providers.get(model)
            if not provider:
                config = (self.custom_models or {}).get(model, {})
                if not config:
                    raise ValueError(f"Custom model '{model}' is not configured")
                provider = get_ai_provider("custom")
                from utils import resolve_api_key
                provider.initialize(
                    api_key=resolve_api_key(config.get("api_key", "")).strip(),
                    endpoint=config.get("endpoint"),
                    model_id=config.get("model_name") or model,
                    api_type=config.get("api_type") or "chat.completions",
                    voice=config.get("voice"),
                )
                self.custom_providers[model] = provider
            return provider
        else:
            provider = self.get_provider(provider_name)
            if not provider:
                raise ValueError(f"{provider_name.title()} provider is not initialized")
            return provider

    def _clean_messages_for_perplexity(self, messages: List[Dict]) -> List[Dict]:
        """Clean messages for Perplexity API (strict alternation required)."""
        if not messages:
            return messages
        
        cleaned = []
        system_messages = []
        other_messages = []
        
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_messages.append({"role": "system", "content": content})
            elif content:
                other_messages.append({"role": role, "content": content})
        
        cleaned.extend(system_messages)
        
        # Ensure strict alternation
        alternating = []
        expected_role = "user"
        
        for msg in other_messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == expected_role:
                alternating.append({"role": role, "content": content})
                expected_role = "assistant" if role == "user" else "user"
            elif role == "user" and expected_role == "user":
                if alternating and alternating[-1]["role"] == "user":
                    alternating[-1]["content"] += "\n\n" + content
                else:
                    alternating.append({"role": role, "content": content})
                    expected_role = "assistant"
            elif role == "assistant" and expected_role == "assistant":
                if alternating and alternating[-1]["role"] == "assistant":
                    alternating[-1]["content"] += "\n\n" + content
                else:
                    alternating.append({"role": role, "content": content})
                    expected_role = "user"
        
        cleaned.extend(alternating)
        return cleaned

    def _append_perplexity_sources(self, answer: str, response_meta: dict) -> str:
        """Append Perplexity search results as sources section."""
        perplexity_meta = (response_meta or {}).get("perplexity", {})
        search_results = perplexity_meta.get("search_results") if isinstance(perplexity_meta, dict) else None
        if not search_results:
            return answer
        
        lines = []
        for idx, res in enumerate(search_results, start=1):
            title = res.get("title") or "Source"
            url = res.get("url") or ""
            date = res.get("date") or ""
            line = f"{idx}. {title}"
            if date:
                line += f" ({date})"
            if url:
                line += f" — {url}"
            lines.append(line)
        
        if lines:
            return (answer.rstrip() + "\n\nSources:\n" + "\n".join(lines)).rstrip()
        return answer

    def _normalize_image_tags(self, text: str) -> str:
        """Normalize image references to consistent format."""
        if not text:
            return text
        import re
        
        seen_src = set()
        
        def md_to_html(match):
            path = match.group(2)
            if path.startswith('sandbox:'):
                path = path[8:]
            if path in seen_src:
                return ""
            seen_src.add(path)
            return f'<img src="{path}"/>'
        
        text = re.sub(r'!\[([^\]]*)\]\((?:sandbox:)?([^)]+)\)', md_to_html, text)
        
        pattern = re.compile(r'<img\s+src="([^"]+)"[^>]*>', re.IGNORECASE)
        result_parts = []
        last_end = 0
        
        for match in pattern.finditer(text):
            result_parts.append(text[last_end:match.start()])
            src = match.group(1)
            if src in seen_src:
                replacement = ""
            else:
                seen_src.add(src)
                replacement = f'<img src="{src}"/>'
            result_parts.append(replacement)
            last_end = match.end()
        
        result_parts.append(text[last_end:])
        return "".join(result_parts)

    @property
    def event_bus(self) -> EventBus:
        """Get the event bus instance."""
        return self._event_bus

    @property
    def settings_manager(self) -> SettingsManager:
        """Get the settings manager instance."""
        return self._settings_manager

    # -----------------------------------------------------------------------
    # Settings management
    # -----------------------------------------------------------------------

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a setting value via settings manager."""
        return self._settings_manager.get(key, default)
    
    def set_setting(self, key: str, value: Any) -> None:
        """Set a setting value via settings manager."""
        self._settings_manager.set(key, value)
        # Also update local attribute for backward compatibility
        setattr(self, key.lower(), value)

    def update_tool_manager(self) -> None:
        """Update the ToolManager with current settings."""
        self.tool_manager = ToolManager(
            image_tool_enabled=self._settings_manager.get('IMAGE_TOOL_ENABLED', True),
            music_tool_enabled=self._settings_manager.get('MUSIC_TOOL_ENABLED', False),
            read_aloud_tool_enabled=self._settings_manager.get('READ_ALOUD_TOOL_ENABLED', False),
            search_tool_enabled=self._settings_manager.get('SEARCH_TOOL_ENABLED', False),
            text_edit_tool_enabled=self._settings_manager.get('TEXT_EDIT_TOOL_ENABLED', False),
        )
        # Update tool service with new tool manager and event bus
        self._tool_service = ToolService(
            tool_manager=self.tool_manager,
            event_bus=self._event_bus,
            settings_manager=self._settings_manager,
        )
        # Re-initialize memory service if settings changed
        self._init_memory_service()

    # -----------------------------------------------------------------------
    # Conversation Compaction
    # -----------------------------------------------------------------------

    def _check_and_perform_compaction(self):
        """Check if conversation exceeds size limit and compact if needed."""
        if not self._settings_manager.get('COMPACTION_ENABLED', False):
            return

        limit_kb = self._settings_manager.get('COMPACTION_MAX_SIZE_KB', 100)
        
        # Use ChatService to get size of the EFFECTIVE conversation (what is sent to model)
        from conversation import ConversationHistory
        
        # Remove notification-only messages from compaction sizing.
        filtered_history = [
            m for m in self.conversation_history
            if not m.get("provider_meta", {}).get("is_notification", False)
        ]

        # Get the compacted view (System + Summary + Post-Compaction)
        compacted_list, summary = self._apply_compaction_view(filtered_history)
        
        # If we have a summary, ensure it's counted in the size.
        # _apply_compaction_view returns the list.
        # If there's a summary, we usually inject it into the message content during prepare_messages_for_model.
        # But here we just want a rough estimate.
        # If we reconstruct a history object from the list, get_conversation_size_kb will dump it.
        
        # We need to manually inject the summary into the first message content for size calculation accuracy
        # if it's not already there (it's returned separately by _apply_compaction_view).
        
        current_history = ConversationHistory.from_list(compacted_list)

        size_kb = self._chat_service.get_conversation_size_kb(current_history)
        
        if size_kb > limit_kb:
            # Avoid concurrent compaction
            if getattr(self, '_compaction_in_progress', False):
                return
            
            print(f"[Compaction] Triggering compaction for {self.current_chat_id} (Size: {size_kb:.2f}KB > {limit_kb}KB)")
            self._compaction_in_progress = True
            
            import threading
            base_history = ConversationHistory.from_list(filtered_history)
            thread = threading.Thread(
                target=self._run_compaction_background,
                args=(base_history, self.current_chat_id),
                daemon=True
            )
            thread.start()

    def _run_compaction_background(self, history_obj, chat_id):
        """Execute compaction in background thread."""
        try:
            from conversation import Message, ProviderMeta
            
            # Determine range to summarize: after last compaction or from beginning
            last_compaction = history_obj.get_last_compaction()
            start_index = 0
            previous_summary = ""
            if last_compaction:
                # Map indices from history snapshot to current range
                start_index = last_compaction.get('end_index', -1) + 1
                previous_summary = last_compaction.get("summary", "") or ""
            # Skip system message
            start_index = max(start_index, 1)
            
            # Keep last N turns (user+assistant pairs) uncompressed.
            keep_turns = self._settings_manager.get('COMPACTION_KEEP_TURNS', 0) or 0
            keep_count = max(int(keep_turns), 0) * 2
            end_index = len(history_obj.messages) - keep_count - 1
            
            if end_index <= start_index:
                return

            messages_to_compact = history_obj.messages[start_index:end_index+1]
            if not messages_to_compact:
                return

            # Build transcript
            transcript = ""
            for msg in messages_to_compact:
                transcript += f"{msg.role.upper()}: {msg.content}\n\n"
            last_msg = messages_to_compact[-1]
            
            # Summarize
            model = self._settings_manager.get('DEFAULT_MODEL', 'gpt-4o-mini')
            from config import DEFAULT_COMPACTION_PROMPT
            compaction_prompt = self._settings_manager.get('COMPACTION_PROMPT', DEFAULT_COMPACTION_PROMPT)
            
            if previous_summary:
                prompt = (
                    f"{compaction_prompt}\n\n"
                    "Existing summary:\n"
                    f"{previous_summary}\n\n"
                    "New conversation segment:\n"
                    f"{transcript}\n\n"
                    "Update the summary so it includes both the existing summary and the new segment."
                )
            else:
                prompt = (
                    f"{compaction_prompt}\n\n"
                    f"{transcript}"
                )
            
            # Get provider and generate summary
            provider_name = self.get_provider_name_for_model(model)
            provider = self._get_or_init_provider(model, provider_name)
            
            print(f"[Compaction] Summarizing {len(messages_to_compact)} messages with {model}...")
            
            start_time = datetime.now()
            summary = provider.generate_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=model,
                temperature=0.3,
                max_tokens=1000
            )
            duration = (datetime.now() - start_time).total_seconds()
            print(f"[Compaction] Summary generated in {duration:.1f}s")
            
            # Create compaction metadata
            compaction_data = {
                "summary": summary,
                "timestamp": datetime.now().isoformat(),
                "start_index": start_index, 
                "end_index": end_index,
                "model": model,
                "message_count": len(messages_to_compact),
            }
            
            # Update history on main thread
            def update_history():
                # Attach metadata to stable message at end_index in live history
                history_len = len(history_obj.messages)
                live_len = len(self.conversation_history)
                delta = max(live_len - history_len, 0)
                target_index = min(end_index + delta, live_len - 1)

                if target_index < len(self.conversation_history):
                    target_msg = self.conversation_history[target_index]

                    if "provider_meta" not in target_msg:
                        target_msg["provider_meta"] = {}

                    if isinstance(target_msg["provider_meta"], dict):
                        target_msg["provider_meta"]["compacted_data"] = compaction_data
                    
                    self.save_current_chat()
                    print(f"[Compaction] Applied compaction data to message {target_index}")
                    
                self._compaction_in_progress = False
                return False

            from gi.repository import GLib
            GLib.idle_add(update_history)

        except Exception as e:
            print(f"[Compaction] Error: {e}")
            import traceback
            traceback.print_exc()
            self._compaction_in_progress = False
