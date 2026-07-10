import math
from typing import List

from loguru import logger
from pydantic import Field
from shapely.geometry import LineString, MultiLineString

from pendragon.core import (
    BasePluginConfig,
    PipelineOperation,
    PipelineState,
    register_operation,
)

class PeanoConfig(BasePluginConfig):
    spacing: float = Field(
        default=2.0, 
        gt=0.0,
        description="Target spacing between the parallel lines of the curve."
    )


@register_operation("peano", config_class=PeanoConfig)
class PeanoGen(PipelineOperation):
    """Generates a mathematically exact, continuous base-3 Peano space-filling curve."""

    def process(self, state: PipelineState) -> PipelineState:
        cfg = self.config or PeanoConfig()
        
        # 1. Acquire the boundary geometry (factoring in overscan if configured)
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            logger.warning("No boundary available. Skipping peano.")
            return state

        minx, miny, maxx, maxy = effective_boundary.bounds
        width = maxx - minx
        height = maxy - miny
        size = max(width, height)
        safe_spacing = max(cfg.spacing, 0.1)

        logger.info(f"Generating Peano curve with target spacing {safe_spacing}...")

        # Calculate required recursion depth based on bounding box size
        if size > safe_spacing:
            order = int(math.ceil(math.log(size / safe_spacing, 3)))
        else:
            order = 1

        # Cap order at 5 (59,049 points) to prevent massive memory/CPU usage
        order = min(max(order, 1), 5)
        num_points = 9**order
        pts = []

        cells_per_axis = 3**order
        cell_size = size / cells_per_axis

        for i in range(num_points):
            # Extract base-3 digits (2 digits per order level)
            temp = i
            digits = []
            for _ in range(2 * order):
                digits.append(temp % 3)
                temp //= 3
            digits.reverse()

            x_grid, y_grid = 0, 0
            sum_t_even = 0
            sum_t_odd = 0

            # Compute exact grid coordinates using parity rules
            for k in range(1, order + 1):
                t_odd = digits[2 * k - 2]
                t_even = digits[2 * k - 1]

                # Compute x_k (inverts if sum of previous evens is odd)
                if sum_t_even % 2 == 0:
                    x_k = t_odd
                else:
                    x_k = 2 - t_odd
                sum_t_odd += t_odd

                # Compute y_k (inverts if sum of previous odds is odd)
                if sum_t_odd % 2 == 0:
                    y_k = t_even
                else:
                    y_k = 2 - t_even
                sum_t_even += t_even

                # Accumulate the coordinate values
                x_grid = x_grid * 3 + x_k
                y_grid = y_grid * 3 + y_k

            # Map to physical coordinates (centered in the cell)
            px = minx + (x_grid + 0.5) * cell_size
            py = miny + (y_grid + 0.5) * cell_size
            pts.append((px, py))

        if len(pts) < 2:
            return state

        # 2. Clip the generated curve against the complex boundary
        raw_line = LineString(pts)
        clipped_lines: List[LineString] = []
        
        if raw_line.intersects(effective_boundary):
            clipped = raw_line.intersection(effective_boundary)
            
            if isinstance(clipped, LineString) and not clipped.is_empty:
                clipped_lines.append(clipped)
            elif isinstance(clipped, MultiLineString):
                for sub_line in clipped.geoms:
                    if not sub_line.is_empty:
                        clipped_lines.append(sub_line)

        logger.success(f"Generated Peano curve. Retained {len(clipped_lines)} continuous paths.")

        # 3. Return a new immutable state
        return PipelineState(
            boundary=state.boundary, 
            lines=state.lines + clipped_lines,
            operation_name="peano"
        )
