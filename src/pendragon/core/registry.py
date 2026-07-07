from abc import ABC
from abc import abstractmethod
from typing import Type

from pydantic import BaseModel

from pendragon.core.models import PipelineState

OPERATION_REGISTRY = {}


def register_operation(name: str, config_class: Type[BaseModel] | None = None):

    def decorator(cls: Type['PipelineOperation']):
        if not issubclass(cls, PipelineOperation):
            raise TypeError(
                f"Plugin '{name}' ({cls.__name__}) must inherit from PipelineOperation."
            )
        OPERATION_REGISTRY[name] = {"class": cls, "config": config_class}
        return cls

    return decorator


class PipelineOperation(ABC):

    def __init__(self, config: BaseModel | None = None) -> None:
        """
        Base initialization for all pipeline operations.
        Automatically binds the Pydantic configuration model to the instance.
        """
        self.config = config

    @abstractmethod
    def process(self, state: PipelineState) -> PipelineState:
        """
        Takes the current state and returns a NEW PipelineState snapshot.
        """
        pass
