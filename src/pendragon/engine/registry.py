from abc import ABC, abstractmethod
from typing import Optional, Type, Dict, Any, List

from pydantic import BaseModel, Field

from .models import PipelineContext, PipelineState


class BasePluginConfig(BaseModel):
    """Base configuration for all pipeline operations."""
    overscan: float = Field(
        default=0.0,
        description="Distance to expand (positive) or shrink (negative) the operation's clipping boundary."
    )


def register_operation(name: str, config_class: Optional[Type[BaseModel]] = None):
    """Decorator that marks a class as a plugin and attaches its metadata."""
    def decorator(cls: Type['PipelineOperation']):
        if not issubclass(cls, PipelineOperation):
            raise TypeError(
                f"Plugin '{name}' ({cls.__name__}) must inherit from PipelineOperation."
            )
        cls._plugin_name = name
        cls._plugin_config = config_class
        return cls

    return decorator


class PipelineOperation(ABC):

    def __init__(self, config: Optional[BaseModel] = None) -> None:
        self.config = config

    def get_effective_boundary(self, state: PipelineState):
        overscan = getattr(self.config, 'overscan', 0.0)
        if overscan != 0.0 and state.boundary:
            return state.boundary.buffer(overscan, join_style=2)
        return state.boundary

    @abstractmethod
    def process(self,
                state: PipelineState,
                context: Optional[PipelineContext] = None) -> PipelineState:
        pass


class PluginRegistry:
    """An isolated registry for discovering and managing pipeline operations."""
    
    def __init__(self):
        self.operations: Dict[str, Dict[str, Any]] = {}

    def discover(self):
        """Scans memory for imported PipelineOperation subclasses."""
        subclasses = set()
        work = [PipelineOperation]
        while work:
            parent = work.pop()
            for child in parent.__subclasses__():
                if child not in subclasses:
                    subclasses.add(child)
                    work.append(child)

        for cls in subclasses:
            name = getattr(cls, '_plugin_name', None)
            if name:
                self.operations[name] = {
                    "class": cls,
                    "config": getattr(cls, '_plugin_config', None)
                }

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        return self.operations.get(name)

    def get_operation_names(self) -> List[str]:
        return sorted(self.operations.keys())
