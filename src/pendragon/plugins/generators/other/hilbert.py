import math
from typing import List, Optional

from loguru import logger
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry import MultiLineString

from pendragon.core import BasePluginConfig
from pendragon.core import PipelineContext
from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation


class HilbertConfig(BasePluginConfig):
    spacing: float = Field(default=2.0,
                           gt=0.0,
                           description="Target distance between segments.")


@register_operation("hilbert", config_class=HilbertConfig)
class HilbertGen(PipelineOperation):

    def process(self,
                state: PipelineState,
                context: Optional[PipelineContext] = None) -> PipelineState:
        cfg = self.config or HilbertConfig()
        ctx = context or PipelineContext()
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            return state

        minx, miny, maxx, maxy = effective_boundary.bounds
        width, height = maxx - minx, maxy - miny
        size = max(width, height)
        spacing = ctx.variables.get("spacing", cfg.spacing)
        safe_spacing = max(spacing, 0.1)

        order = int(math.ceil(math.log2(
            size / safe_spacing))) if size > safe_spacing else 1
        order = min(order, 8)

        logger.info(
            f"Generating Hilbert curve (order={order}, spacing={spacing})...")

        def hilbert(x0, y0, xi, xj, yi, yj, n):
            if n == 0:
                return [(x0 + (xi + yi) / 2.0, y0 + (xj + yj) / 2.0)]
            return (hilbert(x0, y0, yi / 2, yj / 2, xi / 2, xj / 2, n - 1) +
                    hilbert(x0 + xi / 2, y0 + xj / 2, xi / 2, xj / 2, yi / 2,
                            yj / 2, n - 1) +
                    hilbert(x0 + xi / 2 + yi / 2, y0 + xj / 2 + yj / 2, xi / 2,
                            xj / 2, yi / 2, yj / 2, n - 1) +
                    hilbert(x0 + xi / 2 + yi, y0 + xj / 2 + yj, -yi / 2,
                            -yj / 2, -xi / 2, -xj / 2, n - 1))

        pts = hilbert(minx, miny, size, 0.0, 0.0, size, order)
        clipped_lines: List[LineString] = []

        if len(pts) >= 2:
            raw_hilbert_line = LineString(pts)
            if raw_hilbert_line.intersects(effective_boundary):
                clipped = raw_hilbert_line.intersection(effective_boundary)
                if isinstance(clipped, LineString) and not clipped.is_empty:
                    clipped_lines.append(clipped)
                elif isinstance(clipped, MultiLineString):
                    for sub_line in clipped.geoms:
                        if not sub_line.is_empty:
                            clipped_lines.append(sub_line)

        logger.success(f"Generated {len(clipped_lines)} bounded Hilbert paths.")
        return PipelineState(boundary=state.boundary,
                             lines=state.lines + clipped_lines,
                             operation_name="hilbert")
