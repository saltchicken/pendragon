from typing import List, Optional

from loguru import logger
from nodeweaver.models import PipelineContext
from pendragon.registry import dxf_registry
from pendragon.registry import PendragonBaseConfig
from pendragon.registry import PendragonOperation
from pendragon.state import GeometryState
from pydantic import Field


class ScaleConfig(PendragonBaseConfig):
    factor: float = Field(default=1.0,
                          description="Uniform scaling multiplier.")
    origin: str = Field(
        default="center",
        description="Origin point for scaling ('center', 'centroid', etc).")


@dxf_registry.register("scale", config_class=ScaleConfig)
class ScaleMod(PendragonOperation):

    def process(self,
                state: GeometryState,
                context: Optional[PipelineContext] = None) -> GeometryState:
        cfg = self.config or ScaleConfig()
        ctx = context or PipelineContext()
        current_lines = state.lines

        if not current_lines:
            return state

        factor = ctx.get("factor", cfg.factor)
        origin = ctx.get("origin", cfg.origin)

        # Allow dynamic cells to scale perfectly from their local centers
        lc_x = ctx.get("local_center_x")
        lc_y = ctx.get("local_center_y")
        if origin == "center" and lc_x is not None and lc_y is not None:
            origin_coords = (lc_x, lc_y)
        else:
            origin_coords = origin

        logger.info(
            f"Scaling {len(current_lines)} lines by a factor of {factor}...")

        scaled_lines: List[LineString] = []
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
