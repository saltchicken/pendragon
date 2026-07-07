from dataclasses import dataclass
from dataclasses import field
from typing import List, Protocol

from shapely.geometry import LineString
from shapely.geometry import Point
from shapely.geometry import Polygon


@dataclass
class OperationContext:
    """Holds state for the current fill operation."""
    boundary: Polygon
    lines: List[LineString] = field(default_factory=list)
