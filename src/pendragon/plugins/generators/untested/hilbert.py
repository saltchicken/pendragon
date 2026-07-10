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


class HilbertConfig(BasePluginConfig):
    spacing: float = Field(
        default=2.0, 
        gt=0.0,
        description="Target distance between parallel segments. Determines the resolution (order) of the fractal."
    )


@register_operation("hilbert", config_class=HilbertConfig)
class HilbertGen(PipelineOperation):
    """Generates a highly intricate Hilbert space-filling curve."""

    def process(self, state: PipelineState) -> PipelineState:
        # Load configuration, falling back to defaults if missing
        cfg = self.config or HilbertConfig()
        
        # Fetch the boundary, automatically applying any configured overscan buffer
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            logger.warning("No boundary available. Skipping hilbert generation.")
            return state

        minx, miny, maxx, maxy = effective_boundary.bounds
        width = maxx - minx
        height = maxy - miny
        size = max(width, height)
        safe_spacing = max(cfg.spacing, 0.1)

        # Calculate the required fractal order based on physical size and spacing
        if size > safe_spacing:
            order = int(math.ceil(math.log2(size / safe_spacing)))
        else:
            order = 1
            
        # Hard limit to prevent memory exhaustion (Order 8 = 65,536 vertices)
        order = min(order, 8)

        logger.info(
            f"Generating Hilbert curve (order={order}, spacing={cfg.spacing}) "
            f"over a {width:.1f}x{height:.1f} bounding area..."
        )

        # Recursive Hilbert curve algorithm
        def hilbert(x0, y0, xi, xj, yi, yj, n):
            if n == 0:
                return [(x0 + (xi + yi) / 2.0, y0 + (xj + yj) / 2.0)]

            return (
                hilbert(x0, y0, yi / 2, yj / 2, xi / 2, xj / 2, n - 1) +
                hilbert(x0 + xi / 2, y0 + xj / 2, xi / 2, xj / 2, yi / 2, yj / 2, n - 1) +
                hilbert(x0 + xi / 2 + yi / 2, y0 + xj / 2 + yj / 2, xi / 2, xj / 2, yi / 2, yj / 2, n - 1) +
                hilbert(x0 + xi / 2 + yi, y0 + xj / 2 + yj, -yi / 2, -yj / 2, -xi / 2, -xj / 2, n - 1)
            )

        pts = hilbert(minx, miny, size, 0.0, 0.0, size, order)
        
        clipped_lines: List[LineString] = []
        if len(pts) >= 2:
            raw_hilbert_line = LineString(pts)

            # Clip strictly to the effective boundary
            if raw_hilbert_line.intersects(effective_boundary):
                clipped = raw_hilbert_line.intersection(effective_boundary)
                
                if isinstance(clipped, LineString) and not clipped.is_empty:
                    clipped_lines.append(clipped)
                elif isinstance(clipped, MultiLineString):
                    for sub_line in clipped.geoms:
                        if not sub_line.is_empty:
                            clipped_lines.append(sub_line)

        logger.success(f"Generated {len(clipped_lines)} bounded Hilbert paths.")

        # Return a new immutable PipelineState
        return PipelineState(
            boundary=state.boundary, 
            lines=state.lines + clipped_lines,
            operation_name="hilbert"
        )
