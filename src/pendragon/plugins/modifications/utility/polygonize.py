from typing import List, Optional

from loguru import logger
from pydantic import BaseModel
from shapely.geometry import LineString
from shapely.ops import polygonize

from pendragon.core import PipelineContext
from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation


class PolygonizeConfig(BaseModel):
    pass


@register_operation("polygonize", config_class=PolygonizeConfig)
class PolygonizeMod(PipelineOperation):

    def process(self,
                state: PipelineState,
                context: Optional[PipelineContext] = None) -> PipelineState:
        current_lines = state.lines

        if not current_lines:
            logger.warning("No lines available to polygonize. Skipping.")
            return state

        logger.info(
            f"Polygonizing from {len(current_lines)} existing pipeline paths..."
        )

        polygons = list(polygonize(current_lines))
        if not polygons:
            logger.error(
                "Could not form any closed polygons from the current lines!")
            return state

        new_boundary_lines: List[LineString] = []
        for poly in polygons:
            new_boundary_lines.append(LineString(poly.exterior.coords))
            for interior in poly.interiors:
                new_boundary_lines.append(LineString(interior.coords))

        logger.success(
            f"Converted closed cells into {len(new_boundary_lines)} boundary lines."
        )
        return PipelineState(boundary=state.boundary,
                             lines=new_boundary_lines,
                             operation_name="polygonize")
