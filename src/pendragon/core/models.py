from dataclasses import dataclass
from typing import List, Protocol

from shapely.geometry import LineString
from shapely.geometry import Point
from shapely.geometry import Polygon


@dataclass
class OperationContext:
    """Holds read-only state for the current fill operation."""
    boundary: Polygon


class PipelineOperation(Protocol):

    def process(self, context: OperationContext) -> List[LineString]:
        ...
