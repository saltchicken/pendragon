import math
from typing import List, Optional

from loguru import logger
from pydantic import BaseModel
from pydantic import Field
from shapely.geometry import LineString

from pendragon.core import PipelineContext
from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation


class ConnectContinuousConfig(BaseModel):
    snap_distance: float = Field(default=0.05,
                                 description="Max distance to weld segments.")


@register_operation("connect_continuous", config_class=ConnectContinuousConfig)
class ConnectContinuousMod(PipelineOperation):

    def process(self,
                state: PipelineState,
                context: Optional[PipelineContext] = None) -> PipelineState:
        current_lines = state.lines
        if not current_lines:
            return state

        logger.info(
            f"Connecting sequential segments for {len(current_lines)} lines...")
        cfg = self.config or ConnectContinuousConfig()
        ctx = context or PipelineContext()
        snap_distance = ctx.variables.get("snap_distance", cfg.snap_distance)

        connected_lines: List[LineString] = []
        current_poly = list(current_lines[0].coords)

        for next_line in current_lines[1:]:
            next_coords = list(next_line.coords)
            end_pt = current_poly[-1]
            start_pt, next_end_pt = next_coords[0], next_coords[-1]

            dist_to_start = math.hypot(end_pt[0] - start_pt[0],
                                       end_pt[1] - start_pt[1])
            dist_to_end = math.hypot(end_pt[0] - next_end_pt[0],
                                     end_pt[1] - next_end_pt[1])

            if dist_to_start <= snap_distance and dist_to_start <= dist_to_end:
                current_poly.extend(next_coords[1:])
            elif dist_to_end <= snap_distance and dist_to_end < dist_to_start:
                current_poly.extend(next_coords[::-1][1:])
            else:
                if len(current_poly) >= 2:
                    connected_lines.append(LineString(current_poly))
                current_poly = next_coords

        if len(current_poly) >= 2:
            connected_lines.append(LineString(current_poly))

        logger.success(
            f"Path welding complete. Reduced to {len(connected_lines)} lines.")
        return PipelineState(boundary=state.boundary,
                             lines=connected_lines,
                             operation_name="connect_continuous")
