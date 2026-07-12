from typing import List, Optional

from loguru import logger
from nodeweaver.models import PipelineContext
import numpy as np
from pendragon.registry import dxf_registry
from pendragon.registry import PendragonBaseConfig
from pendragon.registry import PendragonOperation
from pendragon.state import GeometryState
from pendragon.utils import extract_target_polygons
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry import MultiLineString
from shapely.geometry import MultiPolygon
from shapely.geometry import Polygon


class SpiralConfig(PendragonBaseConfig):
    center_x: float | None = Field(default=None)
    center_y: float | None = Field(default=None)
    group_boundaries: bool = Field(default=False)
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


@dxf_registry.register("spiral", config_class=SpiralConfig)
class SpiralGen(PendragonOperation):

    def process(self,
                state: GeometryState,
                context: Optional[PipelineContext] = None) -> GeometryState:
        cfg = self.config or SpiralConfig()
        ctx = context or PipelineContext()
        boundary = self.get_effective_boundary(state)

        polygons = extract_target_polygons(boundary, cfg.group_boundaries)
        clipped_lines: List[LineString] = []

        revolutions = ctx.get("revolutions", cfg.revolutions)

        logger.info(f"Generating spiral with {revolutions} revolutions "
                    f"across {len(polygons)} boundary region(s).")

        for poly in polygons:
            # Fallback hierarchy: Context -> YAML Config -> Geometry Centroid
            cx = ctx.get("center_x") if ctx.get("center_x") is not None else (
                cfg.center_x if cfg.center_x is not None else poly.centroid.x)
            cy = ctx.get("center_y") if ctx.get("center_y") is not None else (
                cfg.center_y if cfg.center_y is not None else poly.centroid.y)

            theta = np.linspace(0, revolutions * 2 * np.pi, cfg.steps)
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

        return GeometryState(boundary=state.boundary,
                             lines=state.lines + clipped_lines,
                             operation_name="spiral")
