from typing import Optional

from loguru import logger
from pydantic import Field
from shapely.geometry import LineString

from pendragon.engine import BasePluginConfig
from pendragon.engine import PipelineContext
from pendragon.engine import PipelineOperation
from pendragon.engine import PipelineState
from pendragon.engine import register_operation


class OffsetFillConfig(BasePluginConfig):
    spacing: float = Field(default=2.0,
                           gt=0.0,
                           description="Distance between offset rings.")
    ring_simplify: float = Field(default=0.2,
                                 ge=0.0,
                                 description="Simplification tolerance.")


@register_operation("offset_fill", config_class=OffsetFillConfig)
class OffsetFillGen(PipelineOperation):

    def process(self,
                state: PipelineState,
                context: Optional[PipelineContext] = None) -> PipelineState:
        cfg = self.config or OffsetFillConfig()
        ctx = context or PipelineContext()
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            return state

        spacing = ctx.variables.get("spacing", cfg.spacing)
        logger.info(
            f"Generating concentric offset fill with spacing {spacing}...")

        new_lines: list[LineString] = []
        current_geom = effective_boundary.buffer(-spacing).simplify(
            cfg.ring_simplify, preserve_topology=False)

        while not current_geom.is_empty and current_geom.area > 0:
            polygons = [current_geom
                       ] if current_geom.geom_type == 'Polygon' else list(
                           current_geom.geoms)
            for p in polygons:
                if p.exterior:
                    new_lines.append(LineString(p.exterior.coords))
                for interior in p.interiors:
                    new_lines.append(LineString(interior.coords))
            current_geom = current_geom.buffer(-spacing).simplify(
                cfg.ring_simplify, preserve_topology=False)

        logger.success(
            f"Offset fill complete. Generated {len(new_lines)} contour paths.")
        return PipelineState(boundary=state.boundary,
                             lines=state.lines + new_lines,
                             operation_name="offset_fill")
