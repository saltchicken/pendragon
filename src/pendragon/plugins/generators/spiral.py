from typing import List

from loguru import logger
import numpy as np
from pydantic import Field
from shapely.geometry import LineString, MultiLineString

from pendragon.core import PipelineOperation, PipelineState, register_operation
from pendragon.core import BasePluginConfig


class SpiralConfig(BasePluginConfig):
    center_x: float = Field(default=100.0, description="X coordinate of the spiral center.")
    center_y: float = Field(default=100.0, description="Y coordinate of the spiral center.")
    start_radius: float = Field(default=0.0, description="Starting radius (can be > 0 for a hollow center).")
    end_radius: float = Field(default=100.0, description="Outer radius where the spiral terminates.")
    revolutions: float = Field(default=10.0, description="Total number of full rotations.")
    steps: int = Field(default=1000, description="Total number of linear segments used to draw the curve.")


@register_operation("spiral", config_class=SpiralConfig)
class SpiralGen(PipelineOperation):

    def process(self, state: PipelineState) -> PipelineState:
        cfg = self.config or SpiralConfig()
        boundary = self.get_effective_boundary(state)

        logger.info(
            f"Generating spiral at ({cfg.center_x}, {cfg.center_y}) "
            f"with {cfg.revolutions} revolutions."
        )

        # 1. Parameterize theta and radius
        theta = np.linspace(0, cfg.revolutions * 2 * np.pi, cfg.steps)
        r = np.linspace(cfg.start_radius, cfg.end_radius, cfg.steps)

        # 2. Calculate Cartesian coordinates
        x = cfg.center_x + r * np.cos(theta)
        y = cfg.center_y + r * np.sin(theta)

        coords = np.column_stack((x, y))
        raw_pattern_line = LineString(coords)

        # 3. Clip the generated spiral against the current pipeline boundary
        clipped_lines: List[LineString] = []
        if raw_pattern_line.intersects(boundary):
            clipped = raw_pattern_line.intersection(boundary)

            if isinstance(clipped, LineString) and not clipped.is_empty:
                clipped_lines.append(clipped)
            elif isinstance(clipped, MultiLineString):
                for sub_line in clipped.geoms:
                    if not sub_line.is_empty:
                        clipped_lines.append(sub_line)

        logger.success(f"Generated spiral segments. Retained {len(clipped_lines)} continuous paths.")

        return PipelineState(
            boundary=boundary,
            lines=clipped_lines,
            operation_name="spiral"
        )
