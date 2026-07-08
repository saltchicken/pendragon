import math
from typing import List
from loguru import logger
from pydantic import BaseModel, Field
from shapely.geometry import LineString

from pendragon.core import PipelineOperation, PipelineState, register_operation


class ConnectContinuousConfig(BaseModel):
    snap_distance: float = Field(
        default=0.05, 
        description="Max distance between consecutive segment endpoints to weld them."
    )


@register_operation("connect_continuous", config_class=ConnectContinuousConfig)
class ConnectContinuousMod(PipelineOperation):

    def process(self, state: PipelineState) -> PipelineState:
        current_lines = state.lines
        if not current_lines:
            return state

        logger.info(f"Connecting sequential segments for {len(current_lines)} lines...")
        
        cfg = self.config or ConnectContinuousConfig()
        connected_lines: List[LineString] = []

        # Start with the first segment
        current_poly = list(current_lines[0].coords)

        for next_line in current_lines[1:]:
            next_coords = list(next_line.coords)
            
            end_pt = current_poly[-1]
            start_pt = next_coords[0]
            next_end_pt = next_coords[-1]
            
            # Calculate distance from our current tail to both ends of the next segment
            dist_to_start = math.hypot(end_pt[0] - start_pt[0], end_pt[1] - start_pt[1])
            dist_to_end = math.hypot(end_pt[0] - next_end_pt[0], end_pt[1] - next_end_pt[1])
            
            if dist_to_start <= cfg.snap_distance and dist_to_start <= dist_to_end:
                # Normal connection: weld them together without lifting the pen
                current_poly.extend(next_coords[1:])
            elif dist_to_end <= cfg.snap_distance and dist_to_end < dist_to_start:
                # Reversed connection: the segment was drawn backward. Reverse before welding.
                current_poly.extend(next_coords[::-1][1:])
            else:
                # Too far apart (true pen lift). Commit this path and start a new one
                if len(current_poly) >= 2:
                    connected_lines.append(LineString(current_poly))
                current_poly = next_coords

        # Catch the trailing path
        if len(current_poly) >= 2:
            connected_lines.append(LineString(current_poly))

        logger.success(f"Path welding complete. Reduced path segments to {len(connected_lines)} unified lines.")
        return PipelineState(
            boundary=state.boundary,
            lines=connected_lines,
            operation_name="connect_continuous"
        )
