from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from shapely.geometry import LineString
from shapely.geometry import Polygon

@dataclass(frozen=True)
class PipelineContext:
    """Transient execution metadata passed down the pipeline."""
    local_center_x: Optional[float] = None
    local_center_y: Optional[float] = None
    local_rotation: Optional[float] = None
    variables: Dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class PipelineState:
    """An immutable snapshot of the geometry at one stage of the pipeline."""
    boundary: Polygon
    lines: List[LineString] = field(default_factory=list)
    operation_name: str = "initialization"
