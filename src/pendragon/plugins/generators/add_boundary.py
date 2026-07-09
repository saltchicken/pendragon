from typing import List

from loguru import logger
from shapely.geometry import LineString
from shapely.geometry import MultiPolygon
from shapely.geometry import Polygon

from pendragon.core import BasePluginConfig
from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation


class AddBoundaryConfig(BasePluginConfig):
    # Inherits `overscan` from BasePluginConfig for free.
    # No additional custom settings are strictly needed here!
    pass


@register_operation("add_boundary", config_class=AddBoundaryConfig)
class AddBoundaryGen(PipelineOperation):
    """Extracts the linear rings from the current boundary and adds them to the toolpath."""

    def process(self, state: PipelineState) -> PipelineState:
        # Fetch the boundary, automatically applying any configured overscan buffer
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            logger.warning("No boundary available to add to the toolpath.")
            return state

        logger.info("Extracting boundary perimeter into writable paths...")

        new_lines: List[LineString] = []

        # Helper function to unpack Polygon rings into standard LineStrings
        def extract_rings(poly: Polygon) -> List[LineString]:
            lines = [LineString(poly.exterior.coords)]
            for interior in poly.interiors:
                lines.append(LineString(interior.coords))
            return lines

        # Handle both single Polygons and disjoint MultiPolygons
        if isinstance(effective_boundary, Polygon):
            new_lines.extend(extract_rings(effective_boundary))
        elif isinstance(effective_boundary, MultiPolygon):
            for poly in effective_boundary.geoms:
                new_lines.extend(extract_rings(poly))
        else:
            logger.error(f"Unsupported boundary geometry type: {type(effective_boundary)}")
            return state

        logger.success(f"Successfully added {len(new_lines)} boundary paths.")

        # Append the new boundary paths to the existing lines
        return PipelineState(
            boundary=state.boundary,  # Always pass the original, un-overscanned boundary forward
            lines=state.lines + new_lines,
            operation_name="add_boundary"
        )
