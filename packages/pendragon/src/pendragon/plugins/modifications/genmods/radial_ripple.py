import math
from typing import List, Optional

from loguru import logger
import numpy as np
from pydantic import Field
from shapely.geometry import LineString

from nodeweaver.models import PipelineContext
from pendragon.state import GeometryState
from pendragon.registry import PendragonBaseConfig, PendragonOperation, dxf_registry


class RadialRippleConfig(PendragonBaseConfig):
    center_x: float | None = Field(default=None)
    center_y: float | None = Field(default=None)
    group_boundaries: bool = Field(default=False)
    frequency: float = Field(default=0.2,
                             description="How many ripples per unit.")
    amplitude: float = Field(default=2.0, description="Height of the ripples.")


@dxf_registry.register("radial_ripple", config_class=RadialRippleConfig)
class RadialRippleMod(PendragonOperation):
    """Displaces vertices in a sine wave based on their distance from center."""

    def process(self,
                state: GeometryState,
                context: Optional[PipelineContext] = None) -> GeometryState:
        cfg = self.config or RadialRippleConfig()
        ctx = context or PipelineContext()

        if not state.lines:
            return state

        # Use the context's center if provided, otherwise default to boundary center
        cx = ctx.get("center_x") if ctx.get("center_x") is not None else (
            cfg.center_x
            if cfg.center_x is not None else state.boundary.centroid.x)
        cy = ctx.get("center_y") if ctx.get("center_y") is not None else (
            cfg.center_y
            if cfg.center_y is not None else state.boundary.centroid.y)

        logger.info(
            f"Applying radial ripples (amp={cfg.amplitude}) from ({cx}, {cy}).")

        rippled_lines: List[LineString] = []
        for line in state.lines:
            new_coords = []
            for x, y in line.coords:
                # Calculate distance from center
                dx, dy = x - cx, y - cy
                dist = math.hypot(dx, dy)

                # If center, don't divide by zero
                if dist < 0.001:
                    new_coords.append((x, y))
                    continue

                # Calculate wave displacement
                offset = math.sin(dist * cfg.frequency) * cfg.amplitude

                # Apply displacement along the radial vector
                new_x = x + (dx / dist) * offset
                new_y = y + (dy / dist) * offset
                new_coords.append((new_x, new_y))

            rippled_lines.append(LineString(new_coords))

        return GeometryState(boundary=state.boundary,
                             lines=rippled_lines,
                             operation_name="radial_ripple")
