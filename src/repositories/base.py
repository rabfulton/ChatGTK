"""
Base repository interface for data access operations.
"""

from abc import ABC, abstractmethod
from typing import Generic, TypeVar, Optional, List

T = TypeVar('T')


class Repository(ABC, Generic[T]):
    """
    Base repository interface for data access.
    
    This abstract base class defines the standard CRUD operations
    that all repositories should implement.
    """
    
    @abstractmethod
    def get(self, id: str) -> Optional[T]:
        """
        Retrieve an entity by its ID.
        
        Parameters
        ----------
        id : str
            The unique identifier of the entity.
            
        Returns
        -------
        Optional[T]
            The entity if found, None otherwise.
        """
        pass
    
    @abstractmethod
    def save(self, entity: T) -> None:
        """
        Save or update an entity.
        
        Parameters
        ----------
        entity : T
            The entity to save or update.
        """
        pass
    
    @abstractmethod
    def delete(self, id: str) -> bool:
        """
        Delete an entity by its ID.
        
        Parameters
        ----------
        id : str
            The unique identifier of the entity to delete.
            
        Returns
        -------
        bool
            True if the entity was deleted, False if not found.
        """
        pass
    
    @abstractmethod
    def list_all(self) -> List[T]:
        """
        List all entities.
        
        Returns
        -------
        List[T]
            A list of all entities.
        """
        pass
