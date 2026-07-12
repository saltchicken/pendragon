from typing import List, Optional

from loguru import logger
from nodeweaver.models import PipelineContext
from pendragon.registry import dxf_registry
from pendragon.registry import PendragonBaseConfig
from pendragon.registry import PendragonOperation
from pendragon.state import GeometryState
from shapely.geometry import LineString
from shapely.geometry import MultiPolygon
from shapely.geometry import Polygon


class AddBoundaryConfig(PendragonBaseConfig):
    pass


@dxf_registry.register("add_boundary", config_class=AddBoundaryConfig)
class AddBoundaryGen(PendragonOperation):
    """Extracts the linear rings from the current boundary and adds them to the toolpath."""

    def process(self,
                state: GeometryState,
                context: Optional[PipelineContext] = None) -> GeometryState:
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            logger.warning("No boundary available to add to the toolpath.")
            return state

        logger.info("Extracting boundary perimeter into writable paths...")
        new_lines: List[LineString] = []

        def extract_rings(poly: Polygon) -> List[LineString]:
            lines = [LineString(poly.exterior.coords)]
            for interior in poly.interiors:
                lines.append(LineString(interior.coords))
            return lines

        if isinstance(effective_boundary, Polygon):
            new_lines.extend(extract_rings(effective_boundary))
        elif isinstance(effective_boundary, MultiPolygon):
            for poly in effective_boundary.geoms:
                new_lines.extend(extract_rings(poly))
        else:
            logger.error(
                f"Unsupported boundary geometry type: {type(effective_boundary)}"
            )
            return state

        logger.success(f"Successfully added {len(new_lines)} boundary paths.")
        return GeometryState(boundary=state.boundary,
                             lines=state.lines + new_lines,
                             operation_name="add_boundary")
