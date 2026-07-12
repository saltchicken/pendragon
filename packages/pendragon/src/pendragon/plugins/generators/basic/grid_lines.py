import math
from typing import List, Literal, Optional
from loguru import logger
from pydantic import Field
from shapely.geometry import LineString, MultiLineString

from nodeweaver.models import PipelineContext
from pendragon.state import GeometryState
from pendragon.registry import PendragonBaseConfig, PendragonOperation, dxf_registry


class GridLinesConfig(PendragonBaseConfig):
    spacing: float = Field(default=5, description="Distance between consecutive lines.")
    orientation: Literal["horizontal", "vertical", "crosshatch"] = Field(
        default="horizontal",
        description="Orientation of lines: 'horizontal', 'vertical', or 'crosshatch'.")

@dxf_registry.register("grid_lines", config_class=GridLinesConfig)
class GridLinesGen(PendragonOperation):

    def process(self, state: GeometryState, context: Optional[PipelineContext] = None) -> GeometryState:
        cfg = self.config or GridLinesConfig()
        ctx = context or PipelineContext()

        spacing = ctx.get("spacing", cfg.spacing)
        orientation = ctx.get("orientation", cfg.orientation)

        orig_minx, orig_miny, orig_maxx, orig_maxy = state.boundary.bounds
        effective_boundary = self.get_effective_boundary(state)
        eff_minx, eff_miny, eff_maxx, eff_maxy = effective_boundary.bounds

        logger.info(f"Generating {orientation} lines with spacing {spacing}")
        generated_lines: List[LineString] = []

        def make_horizontal():
            lines = []
            phase_y = orig_miny
            start_k = math.ceil((eff_miny - phase_y) / spacing)
            end_k = math.floor((eff_maxy - phase_y) / spacing)

            for k in range(start_k, end_k + 1):
                current_y = phase_y + k * spacing
                if abs(current_y - eff_miny) < 1e-7 or abs(current_y - eff_maxy) < 1e-7:
                    continue
                lines.append(LineString([(eff_minx, current_y), (eff_maxx, current_y)]))
            return lines

        def make_vertical():
            lines = []
            phase_x = orig_minx
            start_k = math.ceil((eff_minx - phase_x) / spacing)
            end_k = math.floor((eff_maxx - phase_x) / spacing)

            for k in range(start_k, end_k + 1):
                current_x = phase_x + k * spacing
                if abs(current_x - eff_minx) < 1e-7 or abs(current_x - eff_maxx) < 1e-7:
                    continue
                lines.append(LineString([(current_x, eff_miny), (current_x, eff_maxy)]))
            return lines

        if orientation in ("horizontal", "crosshatch"):
            generated_lines.extend(make_horizontal())
        if orientation in ("vertical", "crosshatch"):
            generated_lines.extend(make_vertical())

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

        logger.success(f"Generated and clipped {len(clipped_lines)} pattern lines.")
        return GeometryState(boundary=state.boundary,
                             lines=state.lines + clipped_lines,
                             operation_name="grid_lines")
