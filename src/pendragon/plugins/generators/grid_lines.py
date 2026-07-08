from typing import List

from loguru import logger
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry import MultiLineString

from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation
from pendragon.core import BasePluginConfig


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
        boundary = self.get_effective_boundary(state)

        # 1. Get the bounding box of the current boundary
        minx, miny, maxx, maxy = boundary.bounds
        logger.info(
            f"Generating {active_config.orientation} lines with spacing {active_config.spacing}"
        )

        generated_lines: List[LineString] = []

        # 2. Helper to generate horizontal lines
        def make_horizontal():
            lines = []
            current_y = miny + active_config.spacing
            while current_y < maxy:
                # Create a long line spanning across the bounding box width
                line = LineString([(minx, current_y), (maxx, current_y)])
                lines.append(line)
                current_y += active_config.spacing
            return lines

        # 3. Helper to generate vertical lines
        def make_vertical():
            lines = []
            current_x = minx + active_config.spacing
            while current_x < maxx:
                # Create a long line spanning across the bounding box height
                line = LineString([(current_x, miny), (current_x, maxy)])
                lines.append(line)
                current_x += active_config.spacing
            return lines

        # Populate baseline geometric patterns
        if active_config.orientation in ("horizontal", "crosshatch"):
            generated_lines.extend(make_horizontal())
        if active_config.orientation in ("vertical", "crosshatch"):
            generated_lines.extend(make_vertical())

        # 4. Intersection / Clipping against the boundary geometry
        clipped_lines: List[LineString] = []
        for line in generated_lines:
            if line.intersects(boundary):
                clipped = line.intersection(boundary)

                # Intersection can return a LineString or MultiLineString if split by complex geometry
                if isinstance(clipped, LineString) and not clipped.is_empty:
                    clipped_lines.append(clipped)
                elif isinstance(clipped, MultiLineString):
                    for sub_line in clipped.geoms:
                        if not sub_line.is_empty:
                            clipped_lines.append(sub_line)

        logger.success(
            f"Generated and clipped {len(clipped_lines)} pattern lines.")

        # 5. Return the new state payload containing the calculated line assets
        return PipelineState(boundary=state.boundary,
                             lines=clipped_lines,
                             operation_name="grid_lines")
