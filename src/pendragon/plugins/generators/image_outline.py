from typing import List

from loguru import logger
import numpy as np
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry import MultiLineString
from skimage import feature
from skimage import measure

from pendragon.core import BasePluginConfig
from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation
from pendragon.utils import ImageSampler


class ImageOutlineConfig(BasePluginConfig):
    image_path: str | None = Field(
        default=None, 
        description="File path to the source image."
    )
    resolution: float = Field(
        default=0.5, 
        gt=0.0, 
        description="Sampling grid resolution. Lower = higher detail."
    )
    sigma: float = Field(
        default=1.0, 
        ge=0.0, 
        description="Blur factor to smooth out noise. Increase if you get too many tiny stray lines."
    )
    min_length: float = Field(
        default=2.0, 
        ge=0.0, 
        description="Minimum physical length of a line to keep."
    )


@register_operation("image_outline", config_class=ImageOutlineConfig)
class ImageOutlineGen(PipelineOperation):
    """Traces a single-line outline of image features using Canny edge detection."""

    def process(self, state: PipelineState) -> PipelineState:
        cfg = self.config or ImageOutlineConfig()
        
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            logger.warning("No boundary available. Skipping image_outline.")
            return state

        if not cfg.image_path:
            logger.warning("No image_path provided. Skipping image_outline.")
            return state

        logger.info(f"Detecting outlines in {cfg.image_path} with sigma {cfg.sigma}...")

        minx, miny, maxx, maxy = effective_boundary.bounds
        sampler = ImageSampler(cfg.image_path, effective_boundary.bounds)
        
        width = maxx - minx
        height = maxy - miny

        res_x = max(2, int(width / cfg.resolution))
        res_y = max(2, int(height / cfg.resolution))

        # 1. Build the grayscale grid
        grid = np.zeros((res_y, res_x))
        for i in range(res_y):
            py = miny + (i / (res_y - 1)) * height
            for j in range(res_x):
                px = minx + (j / (res_x - 1)) * width
                grid[i, j] = sampler.get_darkness(px, py)

        # 2. Apply Canny edge detection to find the exact outlines
        # This returns a boolean array where True = an edge
        edges = feature.canny(grid, sigma=cfg.sigma)

        out_lines: List[LineString] = []
        
        # 3. Trace the boolean edges (0.5 is exactly halfway between False and True)
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
                    # 4. Clip strictly to boundary
                    if line.intersects(effective_boundary):
                        clipped = line.intersection(effective_boundary)
                        
                        if isinstance(clipped, LineString) and not clipped.is_empty:
                            out_lines.append(clipped)
                        elif isinstance(clipped, MultiLineString):
                            for sub_line in clipped.geoms:
                                if not sub_line.is_empty:
                                    out_lines.append(sub_line)

        logger.success(f"Generated {len(out_lines)} bounded outline paths.")

        return PipelineState(
            boundary=state.boundary,
            lines=state.lines + out_lines,
            operation_name="image_outline"
        )
