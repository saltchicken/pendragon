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


class GridLinesConfig(BasePluginConfig):
    spacing: float = Field(default=0.5,
                           description="Distance between consecutive lines.")
    orientation: str = Field(
        default="horizontal",
        description=
        "Orientation of lines: 'horizontal', 'vertical', or 'crosshatch'.")


@register_operation("grid_lines", config_class=GridLinesConfig)
class GridLinesGen(PipelineOperation):

    def process(self, state: PipelineState) -> PipelineState:
        active_config = self.config or GridLinesConfig()

        # 1. Distinguish between the original boundary (for phase locking)
        # and the effective boundary (for expansion/clipping)
        orig_minx, orig_miny, orig_maxx, orig_maxy = state.boundary.bounds

        effective_boundary = self.get_effective_boundary(state)
        eff_minx, eff_miny, eff_maxx, eff_maxy = effective_boundary.bounds

        logger.info(
            f"Generating {active_config.orientation} lines with spacing {active_config.spacing}"
        )

        generated_lines: List[LineString] = []

        # 2. Helper to generate horizontal lines
        def make_horizontal():
            lines = []
            phase_y = orig_miny
            
            # Find the starting and ending multipliers based on the effective boundary
            start_k = math.ceil((eff_miny - phase_y) / active_config.spacing)
            end_k = math.floor((eff_maxy - phase_y) / active_config.spacing)
            
            for k in range(start_k, end_k + 1):
                current_y = phase_y + k * active_config.spacing
                
                # Skip the line if it falls exactly on the bottom or top boundary
                if abs(current_y - eff_miny) < 1e-7 or abs(current_y - eff_maxy) < 1e-7:
                    continue
                    
                line = LineString([(eff_minx, current_y), (eff_maxx, current_y)])
                lines.append(line)
                
            return lines

        # 3. Helper to generate vertical lines
        def make_vertical():
            lines = []
            phase_x = orig_minx
            
            # Find the starting and ending multipliers based on the effective boundary
            start_k = math.ceil((eff_minx - phase_x) / active_config.spacing)
            end_k = math.floor((eff_maxx - phase_x) / active_config.spacing)
            
            for k in range(start_k, end_k + 1):
                current_x = phase_x + k * active_config.spacing
                
                # Skip the line if it falls exactly on the left or right boundary
                if abs(current_x - eff_minx) < 1e-7 or abs(current_x - eff_maxx) < 1e-7:
                    continue
                    
                line = LineString([(current_x, eff_miny), (current_x, eff_maxy)])
                lines.append(line)
                
            return lines

        # Populate baseline geometric patterns
        if active_config.orientation in ("horizontal", "crosshatch"):
            generated_lines.extend(make_horizontal())
        if active_config.orientation in ("vertical", "crosshatch"):
            generated_lines.extend(make_vertical())

        # 4. Intersection / Clipping against the EFFECTIVE boundary geometry
        clipped_lines: List[LineString] = []
        for line in generated_lines:
            if line.intersects(effective_boundary):
                clipped = line.intersection(effective_boundary)

                if isinstance(clipped, LineString) and not clipped.is_empty:
                    clipped_lines.append(clipped)
                elif isinstance(clipped, MultiLineString):
                    for sub_line in clipped.geoms:
                        if not sub_line.is_empty:
                            clipped_lines.append(sub_line)

        logger.success(
            f"Generated and clipped {len(clipped_lines)} pattern lines.")

        # 5. Pass the ORIGINAL boundary forward, along with the lines
        return PipelineState(boundary=state.boundary,
                             lines=state.lines + clipped_lines,
                             operation_name="grid_lines")
