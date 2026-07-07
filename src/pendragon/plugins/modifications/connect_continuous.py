# src/pendragon/plugins/modifications/connect_continuous.py

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
        
        if not current_lines:
            return state

        # Start with the first segment
        current_poly = list(current_lines[0].coords)

        for next_line in current_lines[1:]:
            next_coords = list(next_line.coords)
            
            # Check if the start of the next line matches the end of our current running line
            end_pt = current_poly[-1]
            start_pt = next_coords[0]
            
            dist = ((end_pt[0] - start_pt[0])**2 + (end_pt[1] - start_pt[1])**2)**0.5
            
            if dist <= cfg.snap_distance:
                # Weld them together without lifting the pen (skip the duplicate joint point)
                current_poly.extend(next_coords[1:])
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
