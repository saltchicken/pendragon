from abc import ABC, abstractmethod
from typing import Optional, Type, Dict, Any, List, Generic, TypeVar

from pydantic import BaseModel, Field

from .models import PipelineContext, PipelineState

from shapely.geometry import LineString
from shapely.geometry import MultiLineString
from shapely.geometry import Polygon


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


T = TypeVar('T', bound=BaseModel)

class PipelineOperation(ABC, Generic[T]):
    
    # 2. Type hint config with the Generic T
    def __init__(self, config: Optional[T] = None) -> None:
        self.config = config

    def resolve(self, field_name: str, context: Optional[PipelineContext] = None) -> Any:
        """Fetches a variable from transient context, falling back to static config."""
        if context and field_name in context.variables:
            return context.variables[field_name]
        return getattr(self.config, field_name)

    def get_effective_boundary(self, state: PipelineState):
        overscan = getattr(self.config, 'overscan', 0.0)
        if overscan != 0.0 and state.boundary:
            return state.boundary.buffer(overscan, join_style=2)
        return state.boundary

    def clip_to_boundary(self, raw_lines: list[LineString], boundary: Polygon) -> list[LineString]:
        """Uniformly clips a list of lines to a boundary and handles MultiLineString unpacking."""
        clipped_lines = []
        for line in raw_lines:
            if not line.intersects(boundary):
                continue
                
            clipped = line.intersection(boundary)
            if isinstance(clipped, LineString) and not clipped.is_empty:
                clipped_lines.append(clipped)
            elif isinstance(clipped, MultiLineString):
                for sub_line in clipped.geoms:
                    if not sub_line.is_empty:
                        clipped_lines.append(sub_line)
                        
        return clipped_lines

    def resolve_center(self, 
                       context: Optional[PipelineContext], 
                       poly: Polygon) -> tuple[float, float]:
        """
        Extracts the X/Y origin using the standard fallback hierarchy.
        """
        # 1. Check transient context (safeguarded against None)
        if context and context.local_center_x is not None and context.local_center_y is not None:
            return context.local_center_x, context.local_center_y

        # 2. Check static config safely
        cfg_cx = getattr(self.config, 'center_x', None)
        cfg_cy = getattr(self.config, 'center_y', None)
        
        if cfg_cx is not None and cfg_cy is not None:
            return cfg_cx, cfg_cy

        # 3. Fallback to geometric centroid
        return poly.centroid.x, poly.centroid.y

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
