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
from pendragon.utils import ImageSampler


class PhotoWaveConfig(BasePluginConfig):
    lines: int = Field(
        default=80, 
        gt=0,
        description="Number of horizontal wave lines to generate."
    )
    amp: float = Field(
        default=2.0,
        description="Amplitude multiplier for the generated waves."
    )
    image_path: str | None = Field(
        default=None,
        description="File path to the source image to sample."
    )


@register_operation("photo_wave", config_class=PhotoWaveConfig)
class PhotoWaveGen(PipelineOperation):
    """Generates horizontal waves modulated by image darkness."""

    def process(self, state: PipelineState) -> PipelineState:
        cfg = self.config or PhotoWaveConfig()
        
        # Fetch the boundary, automatically applying any configured overscan buffer
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            logger.warning("No boundary available. Skipping photo_wave.")
            return state

        if not cfg.image_path:
            logger.warning("No image_path provided. Skipping photo_wave.")
            return state

        logger.info(f"Generating {cfg.lines} photo waves from {cfg.image_path}...")

        minx, miny, maxx, maxy = effective_boundary.bounds
        width, height = maxx - minx, maxy - miny
        row_spacing = height / cfg.lines
        
        sampler = ImageSampler(cfg.image_path, effective_boundary.bounds)
        raw_lines: List[LineString] = []

        # Generate raw unclipped wave geometries
        for r in range(cfg.lines):
            y_base = miny + (r * row_spacing)
            coords = []
            steps = int(width * 5)
            
            if steps <= 0:
                continue

            for s in range(steps):
                x = minx + (s * (width / steps))
                darkness = sampler.get_darkness(x, y_base)
                
                y_offset = math.sin(x * 3.0) * (row_spacing * cfg.amp * 0.5) * darkness
                coords.append((x, y_base + y_offset))

            if len(coords) >= 2:
                raw_lines.append(LineString(coords))

        # Clip strictly to boundary
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

        logger.success(f"Generated {len(clipped_lines)} bounded wave paths.")

        # Append the new paths to the existing lines
        return PipelineState(
            boundary=state.boundary, # Always pass the original, un-overscanned boundary forward
            lines=state.lines + clipped_lines,
            operation_name="photo_wave"
        )
