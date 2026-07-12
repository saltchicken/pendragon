import math
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


class ConcentricConfig(PendragonBaseConfig):
    center_x: float | None = Field(default=None)
    center_y: float | None = Field(default=None)
    group_boundaries: bool = Field(default=False)
    min_radius: float = Field(default=5.0,
                              description="Radius of the innermost shape.")
    max_radius: float = Field(default=100.0,
                              description="Radius of the outermost shape.")
    spacing: float = Field(
        default=5.0,
        description="Distance between consecutive concentric rings.")
    sides: int = Field(
        default=64,
        ge=3,
        description=
        "Number of sides. Use high values (e.g., 64) for circles, or low values (e.g., 3, 4, 6) for polygons."
    )
    rotation: float = Field(
        default=0.0,
        description="Rotation angle in degrees for the generated shapes.")


@dxf_registry.register("concentric", config_class=ConcentricConfig)
class ConcentricGen(PendragonOperation):
    """Generates concentric rings or polygons clipped to the boundary."""

    def process(self,
                state: GeometryState,
                context: Optional[PipelineContext] = None) -> GeometryState:
        cfg = self.config or ConcentricConfig()
        ctx = context or PipelineContext()
        boundary = self.get_effective_boundary(state)

        polygons = extract_target_polygons(boundary, cfg.group_boundaries)
        clipped_lines: List[LineString] = []

        logger.info(f"Generating concentric shapes with {cfg.sides} sides "
                    f"across {len(polygons)} boundary region(s).")

        spacing = ctx.get("spacing", cfg.spacing)
        if spacing <= 0:
            logger.error("Spacing must be greater than 0.")
            return state

        radiuses = np.arange(cfg.min_radius, cfg.max_radius + 1e-9, spacing)

        for poly in polygons:
            # Fallback hierarchy: Context -> YAML Config -> Geometry Centroid
            cx = ctx.get("center_x") if ctx.get("center_x") is not None else (
                cfg.center_x if cfg.center_x is not None else poly.centroid.x)
            cy = ctx.get("center_y") if ctx.get("center_y") is not None else (
                cfg.center_y if cfg.center_y is not None else poly.centroid.y)
            rot = ctx.get("rotation", cfg.rotation)

            theta = np.linspace(0, 2 * math.pi,
                                cfg.sides + 1) + math.radians(rot)
            cos_theta = np.cos(theta)
            sin_theta = np.sin(theta)

            for r in radiuses:
                if r <= 0:
                    continue

                x = cx + r * cos_theta
                y = cy + r * sin_theta

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
            f"Generated concentric shapes. Retained {len(clipped_lines)} continuous paths."
        )

        return GeometryState(boundary=state.boundary,
                             lines=state.lines + clipped_lines,
                             operation_name="concentric")
