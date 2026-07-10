import math
from typing import List

from loguru import logger
from pydantic import Field
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge

from pendragon.core import (
    BasePluginConfig,
    PipelineOperation,
    PipelineState,
    register_operation,
)
from pendragon.utils import ImageSampler


class ChladniConfig(BasePluginConfig):
    n: float = Field(
        default=3.0, 
        description="Horizontal resonant mode."
    )
    m: float = Field(
        default=5.0, 
        description="Vertical resonant mode."
    )
    sign: float = Field(
        default=-1.0, 
        description="Sign of the wave interference (+1.0 or -1.0)."
    )
    res: float = Field(
        default=0.5, 
        gt=0.0, 
        description="Grid sampling resolution. Lower is more detailed."
    )
    simplify: float = Field(
        default=0.0, 
        ge=0.0, 
        description="Tolerance for path simplification to reduce vertex count."
    )
    image_path: str | None = Field(
        default=None, 
        description="Optional file path to an image for modulating the nodes."
    )


@register_operation("chladni", config_class=ChladniConfig)
class ChladniGen(PipelineOperation):
    """
    Generates Chladni resonant plate patterns using a marching squares algorithm.
    If an image path is provided, it warps the resonant nodes based on the photo's darkness.
    """

    def process(self, state: PipelineState) -> PipelineState:
        cfg = self.config or ChladniConfig()
        
        # 1. Acquire the boundary geometry
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            logger.warning("No boundary available. Skipping chladni.")
            return state

        minx, miny, maxx, maxy = effective_boundary.bounds
        width = maxx - minx
        height = maxy - miny

        if width <= 0 or height <= 0:
            return state

        logger.info(f"Generating Chladni pattern (n={cfg.n}, m={cfg.m}) at resolution {cfg.res}...")

        # 2. Setup the image sampler if requested
        sampler = None
        if cfg.image_path:
            logger.info(f"Modulating pattern using image: {cfg.image_path}")
            sampler = ImageSampler(cfg.image_path, effective_boundary.bounds)

        grid_res = max(cfg.res, 0.1)
        cols = int(math.ceil(width / grid_res)) + 1
        rows = int(math.ceil(height / grid_res)) + 1

        x_grid = [minx + i * grid_res for i in range(cols)]
        y_grid = [miny + j * grid_res for j in range(rows)]

        def get_val(x: float, y: float) -> float:
            # Normalize coordinates to 0.0 - 1.0 mapping across the bounding box
            u = (x - minx) / width
            v = (y - miny) / height

            # Standard Chladni plate equation
            val = (math.cos(cfg.n * math.pi * u) * math.cos(cfg.m * math.pi * v) +
                   cfg.sign * math.cos(cfg.m * math.pi * u) * math.cos(cfg.n * math.pi * v))

            if sampler:
                # Modulate the zero-crossing threshold with the image.
                # Scaling by 2.0 allows the image darkness to significantly warp the topology.
                val += (sampler.get_darkness(x, y) - 0.5) * 2.0

            return val

        # Precompute the scalar field
        vals = [[get_val(x, y) for y in y_grid] for x in x_grid]

        def interp(v1: float, v2: float, p1: tuple, p2: tuple) -> tuple:
            """Linear interpolation to find the exact sub-grid zero crossing."""
            if v1 == v2:
                return p1
            t = (0.0 - v1) / (v2 - v1)
            return (p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1]))

        segments = []

        # 3. Marching Squares Execution
        for i in range(cols - 1):
            for j in range(rows - 1):
                x0, y0 = x_grid[i], y_grid[j]
                x1, y1 = x_grid[i + 1], y_grid[j + 1]

                v00 = vals[i][j]
                v10 = vals[i + 1][j]
                v11 = vals[i + 1][j + 1]
                v01 = vals[i][j + 1]

                pts = []
                # Check for sign changes across the 4 cell edges
                if (v00 > 0) != (v10 > 0): pts.append(interp(v00, v10, (x0, y0), (x1, y0)))  # Bottom
                if (v10 > 0) != (v11 > 0): pts.append(interp(v10, v11, (x1, y0), (x1, y1)))  # Right
                if (v11 > 0) != (v01 > 0): pts.append(interp(v11, v01, (x1, y1), (x0, y1)))  # Top
                if (v01 > 0) != (v00 > 0): pts.append(interp(v01, v00, (x0, y1), (x0, y0)))  # Left

                if len(pts) == 2:
                    segments.append(LineString(pts))
                elif len(pts) == 4:
                    # Ambiguous saddle point: resolve by sampling the center average
                    center_val = (v00 + v10 + v11 + v01) / 4.0
                    if (center_val > 0) == (v00 > 0):
                        segments.append(LineString([pts[0], pts[3]]))
                        segments.append(LineString([pts[1], pts[2]]))
                    else:
                        segments.append(LineString([pts[0], pts[1]]))
                        segments.append(LineString([pts[2], pts[3]]))

        if not segments:
            logger.warning("No Chladni segments generated within bounds.")
            return state

        # CNC Optimization: Stitch disconnected grid segments into flowing linestrings
        merged = linemerge(segments)

        if cfg.simplify > 0:
            merged = merged.simplify(cfg.simplify, preserve_topology=False)

        raw_lines = []
        if isinstance(merged, LineString):
            raw_lines.append(merged)
        elif isinstance(merged, MultiLineString):
            raw_lines.extend(list(merged.geoms))
        else:
            raw_lines = segments

        # 4. Clip against the complex polygon boundary
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

        logger.success(f"Generated Chladni fill. Retained {len(clipped_lines)} continuous bounded paths.")

        # 5. Return a new immutable state
        return PipelineState(
            boundary=state.boundary, 
            lines=state.lines + clipped_lines,
            operation_name="chladni"
        )
