from typing import List, Optional

from loguru import logger
from pendragon.engine import PipelineContext
from pendragon.engine import PipelineOperation
from pendragon.engine import PipelineState
from pendragon.engine import register_operation
from pydantic import BaseModel
from pydantic import Field
from shapely.affinity import scale
from shapely.geometry import LineString
from shapely.geometry import MultiLineString


class ZoomConfig(BaseModel):
    factor: float = Field(default=1.0, description="Zoom multiplier.")
    origin: str = Field(default="center", description="Origin point for zoom.")


@register_operation("zoom", config_class=ZoomConfig)
class ZoomMod(PipelineOperation):

    def process(self,
                state: PipelineState,
                context: Optional[PipelineContext] = None) -> PipelineState:
        cfg = self.config or ZoomConfig()
        ctx = context or PipelineContext()
        current_lines = state.lines
        boundary = state.boundary

        if not current_lines:
            return state

        factor = ctx.variables.get("factor", cfg.factor)
        origin = ctx.variables.get("origin", cfg.origin)

        if origin == "center" and ctx.local_center_x is not None and ctx.local_center_y is not None:
            origin_coords = (ctx.local_center_x, ctx.local_center_y)
        else:
            origin_coords = origin

        logger.info(
            f"Zooming {len(current_lines)} lines by a factor of {factor}...")

        scaled_lines: List[LineString] = []
        for line in current_lines:
            if line.is_empty:
                continue
            scaled_geom = scale(line,
                                xfact=factor,
                                yfact=factor,
                                origin=origin_coords)
            scaled_lines.append(scaled_geom)

        clipped_lines: List[LineString] = []
        if boundary and not boundary.is_empty:
            for line in scaled_lines:
                if line.intersects(boundary):
                    clipped = line.intersection(boundary)
                    if isinstance(clipped, LineString) and not clipped.is_empty:
                        clipped_lines.append(clipped)
                    elif isinstance(clipped, MultiLineString):
                        for sub_line in clipped.geoms:
                            if not sub_line.is_empty:
                                clipped_lines.append(sub_line)
        else:
            clipped_lines = scaled_lines

        logger.success(
            f"Zoom complete. Yielded {len(clipped_lines)} bounded lines.")
        return PipelineState(boundary=boundary,
                             lines=clipped_lines,
                             operation_name="zoom")
