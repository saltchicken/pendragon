from typing import List

from loguru import logger
import numpy as np
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry import MultiLineString
from skimage import measure

from pendragon.core import BasePluginConfig
from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation
from pendragon.utils import ImageSampler


class PhotoContourConfig(BasePluginConfig):
    levels: int = Field(
        default=15, 
        gt=0, 
        description="Number of contour levels to generate between light and dark."
    )
    resolution: float = Field(
        default=0.5, 
        gt=0.0, 
        description="Sampling grid resolution (smaller is higher detail but slower)."
    )
    min_length: float = Field(
        default=2.0, 
        ge=0.0, 
        description="Minimum physical length of a contour line to keep."
    )
    image_path: str | None = Field(
        default=None, 
        description="File path to the source image to sample."
    )


@register_operation("photo_contour", config_class=PhotoContourConfig)
class PhotoContourGen(PipelineOperation):
    """Generates topographic contours driven by image darkness."""

    def process(self, state: PipelineState) -> PipelineState:
        cfg = self.config or PhotoContourConfig()
        
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            logger.warning("No boundary available. Skipping photo_contour.")
            return state

        if not cfg.image_path:
            logger.warning("No image_path provided. Skipping photo_contour.")
            return state

        logger.info(
            f"Generating {cfg.levels} photo contours from {cfg.image_path} "
            f"at resolution {cfg.resolution}..."
        )

        # 1. Initialize sampler over the bounding box of the current geometry
        minx, miny, maxx, maxy = effective_boundary.bounds
        sampler = ImageSampler(cfg.image_path, effective_boundary.bounds)
        
        width = maxx - minx
        height = maxy - miny

        res_x = max(2, int(width / cfg.resolution))
        res_y = max(2, int(height / cfg.resolution))

        # 2. Build the darkness grid
        grid = np.zeros((res_y, res_x))
        for i in range(res_y):
            py = miny + (i / (res_y - 1)) * height
            for j in range(res_x):
                px = minx + (j / (res_x - 1)) * width
                grid[i, j] = sampler.get_darkness(px, py)

        out_lines: List[LineString] = []
        
        # We sample thresholds from 5% to 95% darkness
        thresholds = np.linspace(0.05, 0.95, cfg.levels)

        # 3. Extract isolines
        for level in thresholds:
            # scikit-image measure returns a list of (N, 2) arrays
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
                        # 4. Clip the resulting line strictly to the boundary
                        if line.intersects(effective_boundary):
                            clipped = line.intersection(effective_boundary)
                            
                            if isinstance(clipped, LineString) and not clipped.is_empty:
                                out_lines.append(clipped)
                            elif isinstance(clipped, MultiLineString):
                                for sub_line in clipped.geoms:
                                    if not sub_line.is_empty:
                                        out_lines.append(sub_line)

        logger.success(f"Generated {len(out_lines)} bounded contour paths.")

        # 5. Return the newly generated lines appended to the current state
        return PipelineState(
            boundary=state.boundary,  # Pass the un-overscanned boundary forward
            lines=state.lines + out_lines,
            operation_name="photo_contour"
        )
