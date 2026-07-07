from dataclasses import dataclass

from typing import Protocol, List
from shapely.geometry import LineString, Point, Polygon


@dataclass
class OperationContext:
    """Holds read-only state for the current fill operation."""
    boundary: Polygon
    centroid: Point
    max_r: float

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return self.boundary.bounds


class PipelineOperation(Protocol):

    def process(self, context: OperationContext) -> List[LineString]:
        ...


