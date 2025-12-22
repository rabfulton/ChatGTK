"""
Repository for managing projects (separate history folders).
"""

import os
import json
import shutil
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from config import PARENT_DIR


PROJECTS_FILE = os.path.join(PARENT_DIR, "projects.json")
PROJECTS_DIR = os.path.join(PARENT_DIR, "projects")


@dataclass
class Project:
    """A project with its own history folder."""
    id: str
    name: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {'id': self.id, 'name': self.name}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Project':
        return cls(id=data['id'], name=data['name'])


class ProjectsRepository:
    """Repository for managing projects."""
    """Repository for managing projects."""
    
    def __init__(self):
        self._projects: Dict[str, Project] = {}
        self._load()
    
    def _load(self) -> None:
        """Load projects from disk."""
        if os.path.exists(PROJECTS_FILE):
            try:
                with open(PROJECTS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for p in data.get('projects', []):
                    proj = Project.from_dict(p)
                    self._projects[proj.id] = proj
            except (json.JSONDecodeError, IOError):
                pass
    
    def _save(self) -> None:
        """Save projects to disk."""
        data = {'projects': [p.to_dict() for p in self._projects.values()]}
        os.makedirs(os.path.dirname(PROJECTS_FILE), exist_ok=True)
        with open(PROJECTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    
    def get(self, project_id: str) -> Optional[Project]:
        """Get a project by ID."""
        return self._projects.get(project_id)
    
    def list_all(self) -> List[Project]:
        """List all projects sorted by name."""
        return sorted(self._projects.values(), key=lambda p: p.name.lower())
    
    def create(self, name: str) -> Project:
        """Create a new project."""
        # Generate ID from name
        project_id = name.lower().replace(' ', '_')
        base_id = project_id
        counter = 1
        while project_id in self._projects:
            project_id = f"{base_id}_{counter}"
            counter += 1
        
        # Create project folder
        project_dir = self.get_history_dir(project_id)
        os.makedirs(project_dir, exist_ok=True)
        
        project = Project(id=project_id, name=name)
        self._projects[project_id] = project
        self._save()
        return project
    
    def delete(self, project_id: str) -> bool:
        """Delete a project and its history folder."""
        if project_id not in self._projects:
            return False
        
        # Remove project folder
        project_dir = self.get_history_dir(project_id)
        if os.path.exists(project_dir):
            shutil.rmtree(project_dir)
        
        del self._projects[project_id]
        self._save()
        return True
    
    def rename(self, project_id: str, new_name: str) -> bool:
        """Rename a project."""
        if project_id not in self._projects:
            return False
        self._projects[project_id].name = new_name
        self._save()
        return True
    
    def get_history_dir(self, project_id: str) -> str:
        """Get the history directory for a project."""
        return os.path.join(PROJECTS_DIR, project_id, "history")
    
    def copy_chat_to_project(self, chat_id: str, source_dir: str, project_id: str) -> bool:
        """Copy a chat and its associated files to a project."""
        dest_dir = self.get_history_dir(project_id)
        os.makedirs(dest_dir, exist_ok=True)
        
        # Copy chat JSON file
        src_file = os.path.join(source_dir, f"{chat_id}.json")
        if not os.path.exists(src_file):
            src_file = os.path.join(source_dir, chat_id)
            if not os.path.exists(src_file):
                return False
        
        dest_file = os.path.join(dest_dir, f"{chat_id}.json")
        shutil.copy2(src_file, dest_file)
        
        # Copy associated folder (images, audio, etc.)
        src_assets = os.path.join(source_dir, chat_id.replace('.json', ''))
        if os.path.isdir(src_assets):
            dest_assets = os.path.join(dest_dir, chat_id.replace('.json', ''))
            if os.path.exists(dest_assets):
                shutil.rmtree(dest_assets)
            shutil.copytree(src_assets, dest_assets)
        
        return True

    def move_chat_to_project(self, chat_id: str, source_dir: str, project_id: str) -> bool:
        """Move a chat and its associated files to a project (or default history)."""
        from config import HISTORY_DIR
        
        # Determine destination directory
        if project_id:
            dest_dir = self.get_history_dir(project_id)
        else:
            dest_dir = HISTORY_DIR
        
        os.makedirs(dest_dir, exist_ok=True)
        
        # Normalize chat_id
        chat_id_clean = chat_id.replace('.json', '')
        
        # Move chat JSON file
        src_file = os.path.join(source_dir, f"{chat_id_clean}.json")
        if not os.path.exists(src_file):
            return False
        
        dest_file = os.path.join(dest_dir, f"{chat_id_clean}.json")
        shutil.move(src_file, dest_file)
        
        # Move associated folder (images, audio, etc.)
        src_assets = os.path.join(source_dir, chat_id_clean)
        if os.path.isdir(src_assets):
            dest_assets = os.path.join(dest_dir, chat_id_clean)
            if os.path.exists(dest_assets):
                shutil.rmtree(dest_assets)
            shutil.move(src_assets, dest_assets)
        
        return True
