from typing import List

from loguru import logger
import numpy as np
from pydantic import Field
from scipy import ndimage
from shapely.geometry import LineString
from shapely.geometry import MultiLineString
from skimage import measure

from pendragon.core import BasePluginConfig
from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation
from pendragon.utils import ImageSampler


class PhotoConcentricConfig(BasePluginConfig):
    spacing: float = Field(
        default=2.0, 
        gt=0.0,
        description="Physical distance between concentric contour lines."
    )
    threshold: float = Field(
        default=0.5,
        description="Darkness threshold (0.0-1.0) to define the boundaries of the fill area."
    )
    resolution: float = Field(
        default=0.25, 
        gt=0.0,
        description="Sampling grid resolution. Lower values yield higher detail but run slower."
    )
    min_length: float = Field(
        default=2.0, 
        ge=0.0, 
        description="Minimum physical length of a contour line to keep (filters out noise)."
    )
    image_path: str | None = Field(
        default=None,
        description="File path to the source image to sample."
    )


@register_operation("photo_concentric", config_class=PhotoConcentricConfig)
class PhotoConcentricGen(PipelineOperation):
    """Generates geometric concentric fills driven by image boundaries."""

    def process(self, state: PipelineState) -> PipelineState:
        cfg = self.config or PhotoConcentricConfig()
        
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            logger.warning("No boundary available. Skipping photo_concentric.")
            return state

        if not cfg.image_path:
            logger.warning("No image_path provided. Skipping photo_concentric.")
            return state

        logger.info(
            f"Generating photo concentric fills from {cfg.image_path} "
            f"with spacing {cfg.spacing} and threshold {cfg.threshold}..."
        )

        minx, miny, maxx, maxy = effective_boundary.bounds
        width = maxx - minx
        height = maxy - miny

        # Define grid size based on the bounding box and requested resolution
        res_x = max(2, int(width / cfg.resolution))
        res_y = max(2, int(height / cfg.resolution))

        sampler = ImageSampler(cfg.image_path, effective_boundary.bounds)

        # Sample the image darkness into a 2D NumPy array
        grid = np.zeros((res_y, res_x))
        for i in range(res_y):
            py = miny + (i / (res_y - 1)) * height
            for j in range(res_x):
                px = minx + (j / (res_x - 1)) * width
                grid[i, j] = sampler.get_darkness(px, py)

        # 1. Create a binary mask (True where the image is darker than the threshold)
        binary_mask = grid > cfg.threshold

        # 2. Calculate Euclidean Distance Transform
        # This gives every 'inside' pixel a value equal to its distance to the nearest edge
        distance_field = ndimage.distance_transform_edt(binary_mask)

        # 3. Convert physical spacing to pixel spacing for the contour extraction
        pixel_spacing = cfg.spacing / cfg.resolution
        max_dist = np.max(distance_field)

        raw_lines: List[LineString] = []

        # 4. Generate contours stepping inward by the spacing amount
        current_dist = pixel_spacing
        while current_dist < max_dist:
            contours = measure.find_contours(distance_field, current_dist)

            for contour in contours:
                coords = []
                for pt in contour:
                    y_idx, x_idx = pt[0], pt[1]

                    # Map the fractional array indices back to physical CNC coordinates
                    px = minx + (x_idx / (res_x - 1)) * width
                    py = miny + (y_idx / (res_y - 1)) * height
                    coords.append((px, py))

                if len(coords) >= 2:
                    line = LineString(coords)
                    if line.length >= cfg.min_length:
                        raw_lines.append(line)

            current_dist += pixel_spacing

        # 5. Clip strictly to the effective boundary
        clipped_lines: List[LineString] = []
        for line in raw_lines:
            if line.intersects(effective_boundary):
                clipped = line.intersection(effective_boundary)
                
                if isinstance(clipped, LineString) and not clipped.is_empty:
                    clipped_lines.append(clipped)
                elif isinstance(clipped, MultiLineString):
                    for sub_line in clipped.geoms:
                        if not sub_line.is_empty:
                            clipped_lines.append(sub_line)

        logger.success(f"Generated {len(clipped_lines)} bounded concentric fill lines.")

        return PipelineState(
            boundary=state.boundary, 
            lines=state.lines + clipped_lines,
            operation_name="photo_concentric"
        )
