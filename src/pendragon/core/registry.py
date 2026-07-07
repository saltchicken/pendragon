from typing import List, Protocol, runtime_checkable, Type

from pydantic import BaseModel
from shapely.geometry import LineString

from pendragon.core.models import OperationContext

OPERATION_REGISTRY = {}


def register_operation(name: str, config_class: Type[BaseModel] = None):

    def decorator(cls: Type[PipelineOperation]):
        if not issubclass(cls, PipelineOperation):
            raise TypeError(
                f"Plugin '{name}' ({cls.__name__}) does not satisfy the PipelineOperation protocol. "
                "Ensure it implements a 'process' method with the correct signature."
            )
        OPERATION_REGISTRY[name] = {"class": cls, "config": config_class}
        return cls

    return decorator


@runtime_checkable
class PipelineOperation(Protocol):

    def process(self, context: OperationContext) -> List[LineString]:
        ...
