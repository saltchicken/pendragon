from typing import Optional

from loguru import logger
import numpy as np
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry import MultiLineString
from skimage import measure

from pendragon.engine import BasePluginConfig
from pendragon.engine import PipelineContext
from pendragon.engine import PipelineOperation
from pendragon.engine import PipelineState
from pendragon.engine import register_operation
from pendragon.utils import ImageSampler


class PhotoContourConfig(BasePluginConfig):
    levels: int = Field(default=15,
                        gt=0,
                        description="Number of contour levels to generate.")
    resolution: float = Field(default=0.5,
                              gt=0.0,
                              description="Sampling grid resolution.")
    min_length: float = Field(default=2.0,
                              ge=0.0,
                              description="Minimum physical length to keep.")
    image_path: str | None = Field(default=None,
                                   description="File path to the source image.")


@register_operation("photo_contour", config_class=PhotoContourConfig)
class PhotoContourGen(PipelineOperation):

    def process(self,
                state: PipelineState,
                context: Optional[PipelineContext] = None) -> PipelineState:
        cfg = self.config or PhotoContourConfig()
        ctx = context or PipelineContext()
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            return state

        if not cfg.image_path:
            return state

        levels = int(ctx.variables.get("levels", cfg.levels))
        resolution = ctx.variables.get("resolution", cfg.resolution)

        logger.info(
            f"Generating {levels} photo contours from {cfg.image_path} at resolution {resolution}..."
        )

        minx, miny, maxx, maxy = effective_boundary.bounds
        sampler = ImageSampler(cfg.image_path, effective_boundary.bounds)
        width, height = maxx - minx, maxy - miny

        res_x = max(2, int(width / resolution))
        res_y = max(2, int(height / resolution))

        grid = np.zeros((res_y, res_x))
        for i in range(res_y):
            py = miny + (i / (res_y - 1)) * height
            for j in range(res_x):
                px = minx + (j / (res_x - 1)) * width
                grid[i, j] = sampler.get_darkness(px, py)

        out_lines: list[LineString] = []
        thresholds = np.linspace(0.05, 0.95, levels)

        for level in thresholds:
            contours = measure.find_contours(grid, level)
            for contour in contours:
                coords = []
                for pt in contour:
                    y_idx, x_idx = pt[0], pt[1]
                    px = minx + (x_idx / (res_x - 1)) * width
                    py = miny + (y_idx / (res_y - 1)) * height
                    coords.append((px, py))

                if len(coords) >= 2:
                    line = LineString(coords)
                    if line.length >= cfg.min_length:
                        if line.intersects(effective_boundary):
                            clipped = line.intersection(effective_boundary)
                            if isinstance(clipped,
                                          LineString) and not clipped.is_empty:
                                out_lines.append(clipped)
                            elif isinstance(clipped, MultiLineString):
                                for sub_line in clipped.geoms:
                                    if not sub_line.is_empty:
                                        out_lines.append(sub_line)

        logger.success(f"Generated {len(out_lines)} bounded contour paths.")
        return PipelineState(boundary=state.boundary,
                             lines=state.lines + out_lines,
                             operation_name="photo_contour")
