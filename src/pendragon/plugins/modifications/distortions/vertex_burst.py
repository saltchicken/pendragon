from typing import Optional

from loguru import logger
from pydantic import BaseModel
from pydantic import Field
from shapely.affinity import scale
from shapely.geometry import LineString

from pendragon.engine import PipelineContext
from pendragon.engine import PipelineOperation
from pendragon.engine import PipelineState
from pendragon.engine import register_operation


class ScaleConfig(BaseModel):
    factor: float = Field(default=1.0,
                          description="Uniform scaling multiplier.")
    origin: str = Field(
        default="center",
        description="Origin point for scaling ('center', 'centroid', etc).")


@register_operation("vertex_burst", config_class=ScaleConfig)
class ScaleMod(PipelineOperation):

    def process(self,
                state: PipelineState,
                context: Optional[PipelineContext] = None) -> PipelineState:
        cfg = self.config or ScaleConfig()
        ctx = context or PipelineContext()
        current_lines = state.lines

        if not current_lines:
            return state

        factor = ctx.variables.get("factor", cfg.factor)
        origin = ctx.variables.get("origin", cfg.origin)

        # Allow dynamic cells to scale perfectly from their local centers
        if origin == "center" and ctx.local_center_x is not None and ctx.local_center_y is not None:
            origin_coords = (ctx.local_center_x, ctx.local_center_y)
        else:
            origin_coords = origin

        logger.info(
            f"Scaling {len(current_lines)} lines by a factor of {factor}...")

        scaled_lines: list[LineString] = []
        for line in current_lines:
            if line.is_empty:
                continue
            scaled_geom = scale(line,
                                xfact=factor,
                                yfact=factor,
                                origin=origin_coords)
            scaled_lines.append(scaled_geom)

        logger.success("Scaling complete.")
        return PipelineState(boundary=state.boundary,
                             lines=scaled_lines,
                             operation_name="scale")
