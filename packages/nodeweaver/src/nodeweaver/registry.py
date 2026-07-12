from abc import ABC, abstractmethod
from typing import Generic, Optional, Type, Dict

from pydantic import BaseModel
from .models import PipelineContext, T_State

class PipelineOperation(ABC, Generic[T_State]):
    def __init__(self, config: Optional[BaseModel] = None) -> None:
        """
        Base initialization for all pipeline operations.
        Automatically binds the Pydantic configuration model to the instance.
        """
        self.config = config

    @abstractmethod
    def process(self, state: T_State, context: Optional[PipelineContext] = None) -> T_State:
        """Takes the current state and context, and returns a NEW State snapshot."""
        pass

class OperationRegistry(Generic[T_State]):
    """A domain-specific registry of operations."""
    def __init__(self):
        self._registry: Dict[str, dict] = {}

    def register(self, name: str, config_class: Optional[Type[BaseModel]] = None):
        def decorator(cls: Type[PipelineOperation[T_State]]):
            if not issubclass(cls, PipelineOperation):
                raise TypeError(f"Plugin '{name}' ({cls.__name__}) must inherit from PipelineOperation.")
            self._registry[name] = {"class": cls, "config": config_class}
            return cls
        return decorator

    def get(self, name: str) -> Optional[dict]:
        return self._registry.get(name)

    def items(self):
        return self._registry.items()
