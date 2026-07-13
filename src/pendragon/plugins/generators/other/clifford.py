import math
from typing import Optional

from loguru import logger
from pydantic import Field
from shapely.geometry import LineString

from pendragon.engine import PipelineContext
from pendragon.engine import PipelineOperation
from pendragon.engine import PipelineState
from pendragon.engine import register_operation
from pendragon.engine.mixins import CenteredPluginConfig


class CliffordConfig(CenteredPluginConfig):
    a: float = Field(default=1.5, description="Parameter A (chaotic variance)")
    b: float = Field(default=-1.8, description="Parameter B (chaotic variance)")
    c: float = Field(default=1.6, description="Parameter C (chaotic variance)")
    d: float = Field(default=0.9, description="Parameter D (chaotic variance)")
    iterations: int = Field(default=15000, description="Number of points to calculate")
    scale: float = Field(default=35.0, description="Size multiplier for the attractor")


@register_operation("clifford", config_class=CliffordConfig)
class CliffordGen(PipelineOperation):
    """Generates an asymmetric, continuous chaotic web using a Clifford Attractor."""

    def process(self,
                state: PipelineState,
                context: Optional[PipelineContext] = None) -> PipelineState:
        cfg = self.config or CliffordConfig()
        ctx = context or PipelineContext()
        
        # Resolve dynamic variables
        a = ctx.variables.get("a", cfg.a)
        b = ctx.variables.get("b", cfg.b)
        c = ctx.variables.get("c", cfg.c)
        d = ctx.variables.get("d", cfg.d)
        iters = ctx.variables.get("iterations", cfg.iterations)
        scale = ctx.variables.get("scale", cfg.scale)

        cx = ctx.variables.get("center_x", ctx.local_center_x if ctx.local_center_x is not None else cfg.center_x)
        cy = ctx.variables.get("center_y", ctx.local_center_y if ctx.local_center_y is not None else cfg.center_y)

        # Default to bounding box center if not provided
        if cx is None or cy is None:
            minx, miny, maxx, maxy = state.boundary.bounds
            cx = cx if cx is not None else minx + (maxx - minx) / 2
            cy = cy if cy is not None else miny + (maxy - miny) / 2

        logger.info(f"Generating Clifford Attractor ({iters} iterations)...")

        points = []
        x, y = 0.0, 0.0

        for _ in range(iters):
            # Calculate the next coordinate in the chaotic system
            next_x = math.sin(a * y) + c * math.cos(a * x)
            next_y = math.sin(b * x) + d * math.cos(b * y)
            
            x, y = next_x, next_y
            
            # Scale and translate to the canvas center
            points.append((cx + x * scale, cy + y * scale))

        # We keep this as one giant continuous line for plotter efficiency
        attractor_line = LineString(points)
        
        # Clip it to the current boundary so it doesn't wander off the page
        effective_boundary = self.get_effective_boundary(state)
        clipped = attractor_line.intersection(effective_boundary)

        new_lines = []
        if not clipped.is_empty:
            if clipped.geom_type == 'LineString':
                new_lines.append(clipped)
            elif clipped.geom_type == 'MultiLineString':
                new_lines.extend(list(clipped.geoms))

        logger.success(f"Clifford Attractor generated with {len(new_lines)} path segments.")
        return PipelineState(boundary=state.boundary,
                             lines=state.lines + new_lines,
                             operation_name="clifford")
