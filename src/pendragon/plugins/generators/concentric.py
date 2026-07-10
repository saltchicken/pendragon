import math
from typing import List

from loguru import logger
import numpy as np
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry import MultiLineString

from pendragon.core import CenteredPluginConfig
from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation
from pendragon.utils import extract_target_polygons


class ConcentricConfig(CenteredPluginConfig):
    min_radius: float = Field(
        default=5.0, 
        description="Radius of the innermost shape."
    )
    max_radius: float = Field(
        default=100.0, 
        description="Radius of the outermost shape."
    )
    spacing: float = Field(
        default=5.0, 
        description="Distance between consecutive concentric rings."
    )
    sides: int = Field(
        default=64,
        ge=3,
        description="Number of sides. Use high values (e.g., 64) for circles, or low values (e.g., 3, 4, 6) for polygons."
    )
    rotation: float = Field(
        default=0.0,
        description="Rotation angle in degrees for the generated shapes."
    )


@register_operation("concentric", config_class=ConcentricConfig)
class ConcentricGen(PipelineOperation):
    """Generates concentric rings or polygons clipped to the boundary."""

    def process(self, state: PipelineState) -> PipelineState:
        cfg = self.config or ConcentricConfig()
        boundary = self.get_effective_boundary(state)

        polygons = extract_target_polygons(boundary, cfg.group_boundaries)

        clipped_lines: List[LineString] = []

        logger.info(
            f"Generating concentric shapes with {cfg.sides} sides "
            f"across {len(polygons)} boundary region(s)."
        )

        if cfg.spacing <= 0:
            logger.error("Spacing must be greater than 0.")
            return state

        # Generate the list of radiuses we need to draw
        radiuses = np.arange(cfg.min_radius, cfg.max_radius + 1e-9, cfg.spacing)

        for poly in polygons:
            # Fallback to centroid if coordinates are not strictly defined
            cx = cfg.center_x if cfg.center_x is not None else poly.centroid.x
            cy = cfg.center_y if cfg.center_y is not None else poly.centroid.y

            # Calculate the angular steps once per polygon center
            # Adding 1 to sides ensures the path closes back on itself (0 to 2π)
            theta = np.linspace(0, 2 * math.pi, cfg.sides + 1) + math.radians(cfg.rotation)
            cos_theta = np.cos(theta)
            sin_theta = np.sin(theta)

            for r in radiuses:
                if r <= 0:
                    continue  # Can't draw a LineString with a radius of 0

                x = cx + r * cos_theta
                y = cy + r * sin_theta

                coords = np.column_stack((x, y))
                raw_pattern_line = LineString(coords)

                # Standard boundary intersection and clipping
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

        return PipelineState(
            boundary=state.boundary,
            lines=state.lines + clipped_lines,
            operation_name="concentric"
        )
