# src/pendragon/plugins/modifications/polygonize.py

from typing import List

from loguru import logger
from pydantic import BaseModel
from pydantic import Field
from shapely.geometry import MultiPolygon
from shapely.geometry import Polygon
from shapely.ops import polygonize
from shapely.ops import unary_union

from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation


class PolygonizeConfig(BaseModel):
    # Optional: you could add a buffer tolerance or configuration if needed
    pass


@register_operation("polygonize", config_class=PolygonizeConfig)
class PolygonizeMod(PipelineOperation):

    def process(self, state: PipelineState) -> PipelineState:
        current_lines = state.lines

        if not current_lines:
            logger.warning("No lines available to polygonize. Skipping.")
            return state

        logger.info(
            f"Polygonizing from {len(current_lines)} existing pipeline paths..."
        )

        # 1. Generate polygons from line intersections/enclosures
        # polygonize() finds closed loops formed by the lines
        polygons = list(polygonize(current_lines))

        if not polygons:
            logger.error(
                "Could not form any closed polygons from the current lines! Ensure lines intersect or close."
            )
            return state

        # 2. Combine all found loops into a single unified boundary shape
        new_boundary = unary_union(polygons)

        # Enforce that it's a structural Polygon or MultiPolygon
        if not isinstance(new_boundary, (Polygon, MultiPolygon)):
            logger.error(
                f"Unexpected geometric shape derived from polygonize: {type(new_boundary)}"
            )
            return state

        logger.success(
            "Successfully generated new generation boundary from prior lines.")

        # 3. Return a fresh state where the 'boundary' is updated,
        # and 'lines' is cleared out so the next step builds from scratch.
        return PipelineState(
            boundary=new_boundary,
            lines=[],  # Clear previous geometry lines
            operation_name="polygonize")
