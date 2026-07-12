from dataclasses import dataclass, field
from typing import List
from shapely.geometry import LineString, Polygon

@dataclass(frozen=True)
class GeometryState:
    """An immutable snapshot of the geometry at one stage of the pipeline."""
    boundary: Polygon
    lines: List[LineString] = field(default_factory=list)
    operation_name: str = "initialization"
