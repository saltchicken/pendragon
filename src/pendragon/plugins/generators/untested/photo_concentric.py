from typing import List, Optional

from loguru import logger
import numpy as np
from pydantic import Field
from scipy import ndimage
from shapely.geometry import LineString, MultiLineString
from skimage import measure

from pendragon.core import BasePluginConfig, PipelineOperation, PipelineState, PipelineContext, register_operation
from pendragon.utils import ImageSampler


class PhotoConcentricConfig(BasePluginConfig):
    spacing: float = Field(default=2.0, gt=0.0, description="Distance between contour lines.")
    threshold: float = Field(default=0.5, description="Darkness threshold (0.0-1.0).")
    resolution: float = Field(default=0.25, gt=0.0, description="Sampling grid resolution.")
    min_length: float = Field(default=2.0, ge=0.0, description="Minimum length to keep.")
    image_path: str | None = Field(default=None, description="File path to the source image.")


@register_operation("photo_concentric", config_class=PhotoConcentricConfig)
class PhotoConcentricGen(PipelineOperation):
    def process(self, state: PipelineState, context: Optional[PipelineContext] = None) -> PipelineState:
        cfg = self.config or PhotoConcentricConfig()
        ctx = context or PipelineContext()
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            return state

        if not cfg.image_path:
            return state

        spacing = ctx.variables.get("spacing", cfg.spacing)
        threshold = ctx.variables.get("threshold", cfg.threshold)
        resolution = ctx.variables.get("resolution", cfg.resolution)

        logger.info(f"Generating photo concentric fills from {cfg.image_path} with spacing {spacing} and threshold {threshold}...")

        minx, miny, maxx, maxy = effective_boundary.bounds
        width, height = maxx - minx, maxy - miny

        res_x, res_y = max(2, int(width / resolution)), max(2, int(height / resolution))
        sampler = ImageSampler(cfg.image_path, effective_boundary.bounds)

        grid = np.zeros((res_y, res_x))
        for i in range(res_y):
            py = miny + (i / (res_y - 1)) * height
            for j in range(res_x):
                px = minx + (j / (res_x - 1)) * width
                grid[i, j] = sampler.get_darkness(px, py)

        binary_mask = grid > threshold
        distance_field = ndimage.distance_transform_edt(binary_mask)

        pixel_spacing = spacing / resolution
        max_dist = np.max(distance_field)
        raw_lines: List[LineString] = []

        current_dist = pixel_spacing
        while current_dist < max_dist:
            contours = measure.find_contours(distance_field, current_dist)
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
                        raw_lines.append(line)
            current_dist += pixel_spacing

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
        return PipelineState(boundary=state.boundary, lines=state.lines + clipped_lines, operation_name="photo_concentric")
