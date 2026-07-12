import math
from typing import List, Optional, Tuple

from loguru import logger
from nodeweaver.models import PipelineContext
from pendragon.registry import dxf_registry
from pendragon.registry import PendragonBaseConfig
from pendragon.registry import PendragonOperation
from pendragon.state import GeometryState
from pydantic import Field


class FisheyeConfig(PendragonBaseConfig):
    strength: float = Field(
        default=0.5,
        description=
        "Distortion strength. Positive for barrel (fisheye), negative for pincushion."
    )
    radius: float = Field(
        default=10.0,
        description=
        "Maximum radius of the distortion effect. Defaults to the distance to the boundary corner."
    )

    center_x: Optional[float] = Field(
        default=None,
        description=
        "X coordinate of the lens center. Defaults to boundary centroid.")
    center_y: Optional[float] = Field(
        default=None,
        description=
        "Y coordinate of the lens center. Defaults to boundary centroid.")


@dxf_registry.register("fisheye", config_class=FisheyeConfig)
class FisheyeMod(PendragonOperation):
    """Applies a non-linear barrel or pincushion spatial distortion to the geometry."""

    def process(self,
                state: GeometryState,
                context: Optional[PipelineContext] = None) -> GeometryState:
        cfg = self.config or FisheyeConfig()
        ctx = context or PipelineContext()
        current_lines = state.lines

        if not current_lines:
            return state

        # Determine center coordinates
        cx = ctx.get("center_x", cfg.center_x)
        cy = ctx.get("center_y", cfg.center_y)

        if cx is None or cy is None:
            centroid = state.boundary.centroid
            cx = centroid.x if cx is None else cx
            cy = centroid.y if cy is None else cy

        # Determine effect radius
        max_r = ctx.get("radius", cfg.radius)
        if max_r is None:
            minx, miny, maxx, maxy = state.boundary.bounds
            # Max distance from centroid to the furthest corner
            max_r = max(math.hypot(minx - cx, miny - cy),
                        math.hypot(maxx - cx, maxy - cy))

        strength = ctx.get("strength", cfg.strength)

        if max_r <= 0 or strength == 0.0:
            logger.info("Fisheye skipped: radius is 0 or strength is 0.0.")
            return state

        logger.info(
            f"Applying fisheye distortion (strength: {strength}, center: {cx:.2f}, {cy:.2f})..."
        )

        def distort_point(x: float, y: float) -> Tuple[float, float]:
            dx = x - cx
            dy = y - cy
            r = math.hypot(dx, dy)

            if r == 0:
                return (x, y)

            # Normalized radius
            rn = r / max_r
            # Polynomial barrel/pincushion distortion
            rn_prime = rn * (1.0 + strength * (rn**2))
            r_prime = rn_prime * max_r

            scale = r_prime / r
            return (cx + dx * scale, cy + dy * scale)

        distorted_lines: List[LineString] = []
        for line in current_lines:
            if line.is_empty:
                continue

            new_coords = [distort_point(x, y) for x, y in line.coords]
            distorted_lines.append(LineString(new_coords))

        logger.success("Fisheye distortion complete.")
        return PipelineState(boundary=state.boundary,
                             lines=distorted_lines,
                             operation_name="fisheye")
