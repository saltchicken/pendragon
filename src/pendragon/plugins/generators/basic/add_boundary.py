from typing import List, Optional

from loguru import logger
from shapely.geometry import LineString
from shapely.geometry import MultiPolygon
from shapely.geometry import Polygon

from pendragon.engine import BasePluginConfig
from pendragon.engine import PipelineContext
from pendragon.engine import PipelineOperation
from pendragon.engine import PipelineState
from pendragon.engine import register_operation


class AddBoundaryConfig(BasePluginConfig):
    pass


@register_operation("add_boundary", config_class=AddBoundaryConfig)
class AddBoundaryGen(PipelineOperation):
    """Extracts the linear rings from the current boundary and adds them to the toolpath."""

    def process(self,
                state: PipelineState,
                context: Optional[PipelineContext] = None) -> PipelineState:
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            logger.warning("No boundary available to add to the toolpath.")
            return state

        logger.info("Extracting boundary perimeter into writable paths...")
        new_lines: list[LineString] = []

        def extract_rings(poly: Polygon) -> list[LineString]:
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
        return PipelineState(boundary=state.boundary,
                             lines=state.lines + new_lines,
                             operation_name="add_boundary")
