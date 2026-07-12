import math
from typing import List, Optional

from loguru import logger
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry import MultiLineString

from pendragon.engine import BasePluginConfig
from pendragon.engine import PipelineContext
from pendragon.engine import PipelineOperation
from pendragon.engine import PipelineState
from pendragon.engine import register_operation


class PeanoConfig(BasePluginConfig):
    spacing: float = Field(default=2.0,
                           gt=0.0,
                           description="Target spacing between lines.")


@register_operation("peano", config_class=PeanoConfig)
class PeanoGen(PipelineOperation):

    def process(self,
                state: PipelineState,
                context: Optional[PipelineContext] = None) -> PipelineState:
        cfg = self.config or PeanoConfig()
        ctx = context or PipelineContext()
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            return state

        spacing = ctx.variables.get("spacing", cfg.spacing)
        safe_spacing = max(spacing, 0.1)

        minx, miny, maxx, maxy = effective_boundary.bounds
        width, height = maxx - minx, maxy - miny
        size = max(width, height)
        order = int(math.ceil(math.log(size / safe_spacing,
                                       3))) if size > safe_spacing else 1
        order = min(max(order, 1), 5)

        logger.info(
            f"Generating Peano curve (order={order}) with spacing {safe_spacing}..."
        )

        num_points = 9**order
        pts = []
        cell_size = size / (3**order)

        for i in range(num_points):
            temp, digits = i, []
            for _ in range(2 * order):
                digits.append(temp % 3)
                temp //= 3
            digits.reverse()

            x_grid, y_grid, sum_t_even, sum_t_odd = 0, 0, 0, 0
            for k in range(1, order + 1):
                t_odd, t_even = digits[2 * k - 2], digits[2 * k - 1]
                x_k = t_odd if sum_t_even % 2 == 0 else 2 - t_odd
                sum_t_odd += t_odd
                y_k = t_even if sum_t_odd % 2 == 0 else 2 - t_even
                sum_t_even += t_even

                x_grid = x_grid * 3 + x_k
                y_grid = y_grid * 3 + y_k

            pts.append((minx + (x_grid + 0.5) * cell_size,
                        miny + (y_grid + 0.5) * cell_size))

        if len(pts) < 2:
            return state

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

        logger.success(
            f"Generated Peano curve. Retained {len(clipped_lines)} continuous paths."
        )
        return PipelineState(boundary=state.boundary,
                             lines=state.lines + clipped_lines,
                             operation_name="peano")
