from abc import ABC, abstractmethod
from typing import Type, Optional

from pydantic import BaseModel
from pydantic import Field

from pendragon.core.models import PipelineState, PipelineContext

OPERATION_REGISTRY = {}


class BasePluginConfig(BaseModel):
    """Base configuration for all pipeline operations."""
    overscan: float = Field(
        default=0.0,
        description=
        "Distance to expand (positive) or shrink (negative) the operation's clipping boundary."
    )


def register_operation(name: str, config_class: Optional[Type[BaseModel]] = None):

    def decorator(cls: Type['PipelineOperation']):
        if not issubclass(cls, PipelineOperation):
            raise TypeError(
                f"Plugin '{name}' ({cls.__name__}) must inherit from PipelineOperation."
            )
        OPERATION_REGISTRY[name] = {"class": cls, "config": config_class}
        return cls

    return decorator


class PipelineOperation(ABC):

    def __init__(self, config: Optional[BaseModel] = None) -> None:
        """
        Base initialization for all pipeline operations.
        Automatically binds the Pydantic configuration model to the instance.
        """
        self.config = config

    def get_effective_boundary(self, state: PipelineState):
        """
        Returns the boundary, buffered by the overscan setting if applicable.
        join_style=2 (mitre) ensures square bounds maintain sharp corners.
        """
        overscan = getattr(self.config, 'overscan', 0.0)
        if overscan != 0.0 and state.boundary:
            return state.boundary.buffer(overscan, join_style=2)
        return state.boundary

    @abstractmethod
    def process(self, state: PipelineState, context: Optional[PipelineContext] = None) -> PipelineState:
        """
        Takes the current state and context, and returns a NEW PipelineState snapshot.
        """
        pass
