from typing import List

from loguru import logger
import numpy as np
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry import MultiLineString
from shapely.geometry import MultiPolygon
from shapely.geometry import Polygon

from pendragon.core import CenteredPluginConfig
from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation
from pendragon.utils import extract_target_polygons


class SpiralConfig(CenteredPluginConfig):
    start_radius: float = Field(
        default=0.0,
        description="Starting radius (can be > 0 for a hollow center).")
    end_radius: float = Field(
        default=100.0, description="Outer radius where the spiral terminates.")
    revolutions: float = Field(default=10.0,
                               description="Total number of full rotations.")
    steps: int = Field(
        default=1000,
        description="Total number of linear segments used to draw the curve.")


@register_operation("spiral", config_class=SpiralConfig)
class SpiralGen(PipelineOperation):

    def process(self, state: PipelineState) -> PipelineState:
        cfg = self.config or SpiralConfig()
        boundary = self.get_effective_boundary(state)

        polygons = extract_target_polygons(boundary, cfg.group_boundaries)

        clipped_lines: List[LineString] = []

        logger.info(f"Generating spiral with {cfg.revolutions} revolutions "
                    f"across {len(polygons)} boundary region(s).")

        for poly in polygons:
            # Fallback to centroid if coordinates are not strictly defined
            cx = cfg.center_x if cfg.center_x is not None else poly.centroid.x
            cy = cfg.center_y if cfg.center_y is not None else poly.centroid.y

            theta = np.linspace(0, cfg.revolutions * 2 * np.pi, cfg.steps)
            r = np.linspace(cfg.start_radius, cfg.end_radius, cfg.steps)

            x = cx + r * np.cos(theta)
            y = cy + r * np.sin(theta)

            coords = np.column_stack((x, y))
            raw_pattern_line = LineString(coords)

            if raw_pattern_line.intersects(poly):
                clipped = raw_pattern_line.intersection(poly)

                if isinstance(clipped, LineString) and not clipped.is_empty:
                    clipped_lines.append(clipped)
                elif isinstance(clipped, MultiLineString):
                    for sub_line in clipped.geoms:
                        if not sub_line.is_empty:
                            clipped_lines.append(sub_line)

        logger.success(
            f"Generated spiral segments. Retained {len(clipped_lines)} continuous paths."
        )

        return PipelineState(boundary=state.boundary,
                             lines=state.lines + clipped_lines,
                             operation_name="spiral")
