import math
from typing import List

from loguru import logger
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry import MultiLineString

from pendragon.core import BasePluginConfig
from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation


class TriangleConfig(BasePluginConfig):
    cell_size: float = Field(
        default=5.0, 
        gt=0.0,
        description="Side length of the equilateral triangles forming the grid."
    )


@register_operation("triangle", config_class=TriangleConfig)
class TriangleGen(PipelineOperation):
    """Generates an equilateral triangular (isometric grid) tessellation."""

    def process(self, state: PipelineState) -> PipelineState:
        # Load configuration, falling back to defaults if missing
        cfg = self.config or TriangleConfig()
        
        # Fetch the boundary, automatically applying any configured overscan buffer
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            logger.warning("No boundary available. Skipping triangle generation.")
            return state

        logger.info(f"Generating triangle grid with cell size {cfg.cell_size}...")

        minx, miny, maxx, maxy = effective_boundary.bounds
        cx, cy = effective_boundary.centroid.x, effective_boundary.centroid.y

        # Calculate a bounding radius large enough to cover the shape when rotated
        diag = math.hypot(maxx - minx, maxy - miny)
        r = diag / 2.0 + cfg.cell_size

        # Perpendicular distance between triangle grid lines
        spacing = cfg.cell_size * math.sqrt(3.0) / 2.0
        if spacing <= 0:
            logger.warning("Spacing calculated to 0 or less. Aborting triangle generation.")
            return state

        raw_lines = []

        # Generate parallel bounding lines at 0, 60, and 120 degrees
        for angle_deg in [0, 60, 120]:
            angle_rad = math.radians(angle_deg)
            cos_a = math.cos(angle_rad)
            sin_a = math.sin(angle_rad)

            # Normal vector to calculate parallel offsets
            nx = -sin_a
            ny = cos_a

            num_lines = int(math.ceil(2 * r / spacing))
            for i in range(-num_lines // 2, num_lines // 2 + 1):
                offset = i * spacing
                px = cx + nx * offset
                py = cy + ny * offset

                start_x = px - cos_a * r
                start_y = py - sin_a * r
                end_x = px + cos_a * r
                end_y = py + sin_a * r

                raw_lines.append(LineString([(start_x, start_y), (end_x, end_y)]))

        # Clip strictly to the effective boundary
        clipped_lines: List[LineString] = []
        for line in raw_lines:
            if line.intersects(effective_boundary):
                clipped = line.intersection(effective_boundary)
                
                if isinstance(clipped, LineString) and not clipped.is_empty:
                    clipped_lines.append(clipped)
                elif isinstance(clipped, MultiLineString):
                    for sub_line in clipped.geoms:
                        if not sub_line.is_empty:
                            clipped_lines.append(sub_line)

        logger.success(f"Generated {len(clipped_lines)} bounded triangle grid lines.")

        # Return a new immutable PipelineState
        return PipelineState(
            boundary=state.boundary, 
            lines=state.lines + clipped_lines,
            operation_name="triangle"
        )
