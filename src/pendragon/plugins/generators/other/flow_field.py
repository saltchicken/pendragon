import math
import random
from typing import List

from loguru import logger
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry import MultiLineString

from pendragon.core import BasePluginConfig
from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation


class FlowFieldConfig(BasePluginConfig):
    spacing: float = Field(
        default=3.0, 
        gt=0.0,
        description="Distance between initial seed points."
    )
    step_length: float = Field(
        default=1.0, 
        gt=0.0,
        description="Distance the path travels in a single calculation step."
    )
    max_steps: int = Field(
        default=50, 
        gt=0,
        description="Maximum number of steps each flow line can take."
    )
    scale: float = Field(
        default=0.1,
        description="Scaling factor for the vector field math. Smaller = broader curves."
    )
    seed: int = Field(
        default=42,
        description="Random seed for reproducible jitter and flow generation."
    )


@register_operation("flow_field", config_class=FlowFieldConfig)
class FlowFieldGen(PipelineOperation):
    """
    Generates organic, sweeping curves by dropping 'seeds' and tracing 
    their paths through a mathematical vector field.
    """

    def process(self, state: PipelineState) -> PipelineState:
        # Load configuration, falling back to defaults if missing
        cfg = self.config or FlowFieldConfig()
        
        # Fetch the boundary, automatically applying any configured overscan buffer
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            logger.warning("No boundary available. Skipping flow_field generation.")
            return state

        logger.info(
            f"Generating flow field (spacing={cfg.spacing}, steps={cfg.max_steps}) "
            f"using scale {cfg.scale}..."
        )

        random.seed(cfg.seed)
        minx, miny, maxx, maxy = effective_boundary.bounds
        width = maxx - minx
        height = maxy - miny

        if width <= 0 or height <= 0:
            return state

        # 1. Distribute starting seeds across the bounding box
        seeds = []
        x = minx
        while x <= maxx:
            y = miny
            while y <= maxy:
                # Add a little jitter to the grid to prevent artificial symmetry
                jx = x + random.uniform(-cfg.spacing / 2, cfg.spacing / 2)
                jy = y + random.uniform(-cfg.spacing / 2, cfg.spacing / 2)
                seeds.append((jx, jy))
                y += cfg.spacing
            x += cfg.spacing

        # 2. Define the mathematical flow
        cx, cy = effective_boundary.centroid.x, effective_boundary.centroid.y

        def get_field_angle(px: float, py: float) -> float:
            """Calculates a pseudo-random angle based on position."""
            nx = (px - cx) * cfg.scale
            ny = (py - cy) * cfg.scale
            # This combination of trig functions creates asymmetric, non-repeating swirls
            angle = math.sin(nx) + math.cos(ny) + math.sin(nx * ny * 0.5)
            return angle * math.pi

        # 3. Trace the paths through the field
        raw_lines = []
        for sx, sy in seeds:
            path = [(sx, sy)]
            cx_pt, cy_pt = sx, sy

            for _ in range(cfg.max_steps):
                theta = get_field_angle(cx_pt, cy_pt)
                nx_pt = cx_pt + cfg.step_length * math.cos(theta)
                ny_pt = cy_pt + cfg.step_length * math.sin(theta)

                path.append((nx_pt, ny_pt))
                cx_pt, cy_pt = nx_pt, ny_pt

                # Terminate early if the line wanders way outside the draw area
                if not (minx - 10 <= cx_pt <= maxx + 10 and
                        miny - 10 <= cy_pt <= maxy + 10):
                    break

            if len(path) > 1:
                raw_lines.append(LineString(path))

        # 4. Clip strictly to the effective boundary
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

        logger.success(f"Generated {len(clipped_lines)} bounded flow field paths.")

        # 5. Return a new immutable PipelineState
        return PipelineState(
            boundary=state.boundary, 
            lines=state.lines + clipped_lines,
            operation_name="flow_field"
        )
