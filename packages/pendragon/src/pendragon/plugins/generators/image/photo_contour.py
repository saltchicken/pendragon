from typing import List, Optional

from loguru import logger
from nodeweaver.models import PipelineContext
import numpy as np
from pendragon.registry import dxf_registry
from pendragon.registry import PendragonBaseConfig
from pendragon.registry import PendragonOperation
from pendragon.state import GeometryState
from pendragon.utils import ImageSampler
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry import MultiLineString
from skimage import measure


class PhotoContourConfig(PendragonBaseConfig):
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


@dxf_registry.register("photo_contour", config_class=PhotoContourConfig)
class PhotoContourGen(PendragonOperation):

    def process(self,
                state: GeometryState,
                context: Optional[PipelineContext] = None) -> GeometryState:
        cfg = self.config or PhotoContourConfig()
        ctx = context or PipelineContext()
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            return state

        if not cfg.image_path:
            return state

        levels = int(ctx.get("levels", cfg.levels))
        resolution = ctx.get("resolution", cfg.resolution)

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

        out_lines: List[LineString] = []
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
        return GeometryState(boundary=state.boundary,
                             lines=state.lines + out_lines,
                             operation_name="photo_contour")
