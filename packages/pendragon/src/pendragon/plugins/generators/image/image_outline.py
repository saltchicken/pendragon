# src/pendragon/plugins/generators/image/image_outline.py
from typing import List, Optional

from loguru import logger
import numpy as np
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry import MultiLineString
from skimage import feature
from skimage import measure

from nodeweaver.models import PipelineContext
from pendragon.state import GeometryState
from pendragon.registry import PendragonBaseConfig, PendragonOperation, dxf_registry
from pendragon.utils import ImageSampler


class ImageOutlineConfig(PendragonBaseConfig):
    image_path: str | None = Field(default=None,
                                   description="File path to the source image.")
    resolution: float = Field(default=0.5,
                              gt=0.0,
                              description="Sampling grid resolution.")
    sigma: float = Field(default=1.0,
                         ge=0.0,
                         description="Blur factor to smooth out noise.")
    min_length: float = Field(default=2.0,
                              ge=0.0,
                              description="Minimum physical length to keep.")


@dxf_registry.register("image_outline", config_class=ImageOutlineConfig)
class ImageOutlineGen(PendragonOperation):

    def process(self,
                state: GeometryState,
                context: Optional[PipelineContext] = None) -> GeometryState:
        cfg = self.config or ImageOutlineConfig()
        ctx = context or PipelineContext()
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            logger.warning("No boundary available. Skipping image_outline.")
            return state

        if not cfg.image_path:
            logger.warning("No image_path provided. Skipping image_outline.")
            return state

        sigma = ctx.get("sigma", cfg.sigma)
        resolution = ctx.get("resolution", cfg.resolution)

        logger.info(
            f"Detecting outlines in {cfg.image_path} with sigma {sigma}...")

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

        edges = feature.canny(grid, sigma=sigma)
        out_lines: List[LineString] = []
        contours = measure.find_contours(edges, 0.5)

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

        logger.success(f"Generated {len(out_lines)} bounded outline paths.")
        return GeometryState(boundary=state.boundary,
                             lines=state.lines + out_lines,
                             operation_name="image_outline")
