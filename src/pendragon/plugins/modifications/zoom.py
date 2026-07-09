from typing import List

from loguru import logger
from pydantic import BaseModel
from pydantic import Field
from shapely.affinity import scale
from shapely.geometry import LineString
from shapely.geometry import MultiLineString

from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation


class ZoomConfig(BaseModel):
    factor: float = Field(
        default=1.0,
        description="Zoom multiplier (e.g., 2.0 zooms in 2x, 0.5 zooms out).")
    origin: str = Field(
        default="center",
        description=
        "Origin point for zoom: 'center', 'centroid', or an exact coordinate.")


@register_operation("zoom", config_class=ZoomConfig)
class ZoomMod(PipelineOperation):
    """Magnifies geometries and clips them to the original bounding viewport."""

    def process(self, state: PipelineState) -> PipelineState:
        cfg = self.config or ZoomConfig()
        current_lines = state.lines
        boundary = state.boundary

        if not current_lines:
            logger.warning("No lines provided to the zoom operation. Skipping.")
            return state

        logger.info(
            f"Zooming {len(current_lines)} lines by a factor of {cfg.factor}..."
        )

        scaled_lines: List[LineString] = []

        # 1. Magnify the lines outward from the origin
        for line in current_lines:
            if line.is_empty:
                continue

            scaled_geom = scale(line,
                                xfact=cfg.factor,
                                yfact=cfg.factor,
                                origin=cfg.origin)
            scaled_lines.append(scaled_geom)

        # 2. Clip the magnified lines back to the original viewport
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
            # Fallback if there is no boundary defined in the state
            clipped_lines = scaled_lines

        logger.success(
            f"Zoom complete. Yielded {len(clipped_lines)} bounded lines.")

        return PipelineState(boundary=boundary,
                             lines=clipped_lines,
                             operation_name="zoom")
