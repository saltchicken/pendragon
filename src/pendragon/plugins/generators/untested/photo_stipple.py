from typing import List

from loguru import logger
import numpy as np
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry import Point

from pendragon.core import BasePluginConfig
from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation
from pendragon.utils import ImageSampler


class PhotoStippleConfig(BasePluginConfig):
    dots: int = Field(
        default=5000, 
        gt=0,
        description="Target number of stipple dots to generate."
    )
    image_path: str | None = Field(
        default=None,
        description="File path to the source image to sample."
    )
    dot_size: float = Field(
        default=0.1,
        gt=0.0,
        description="Length of the microscopic line used to draw a single dot."
    )
    seed: int = Field(
        default=42,
        description="Random seed for repeatable point placement."
    )


@register_operation("photo_stipple", config_class=PhotoStippleConfig)
class PhotoStippleGen(PipelineOperation):
    """Generates a dense point stipple pattern driven by image darkness."""

    def process(self, state: PipelineState) -> PipelineState:
        cfg = self.config or PhotoStippleConfig()
        
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            logger.warning("No boundary available. Skipping photo_stipple.")
            return state

        if not cfg.image_path:
            logger.warning("No image_path provided. Skipping photo_stipple.")
            return state

        logger.info(f"Generating {cfg.dots} stipple dots from {cfg.image_path}...")

        minx, miny, maxx, maxy = effective_boundary.bounds
        sampler = ImageSampler(cfg.image_path, effective_boundary.bounds)
        
        np.random.seed(cfg.seed)
        new_dots: List[LineString] = []
        
        # Batch generation parameters
        batch_size = cfg.dots * 2
        max_batches = 100
        batches = 0

        # Vectorized Rejection Sampling
        while len(new_dots) < cfg.dots and batches < max_batches:
            batches += 1
            xs = np.random.uniform(minx, maxx, batch_size)
            ys = np.random.uniform(miny, maxy, batch_size)
            rand_thresholds = np.random.random(batch_size)
            
            for i in range(batch_size):
                if len(new_dots) >= cfg.dots:
                    break
                
                x, y = xs[i], ys[i]
                
                # Fast check: reject based on image darkness first
                if rand_thresholds[i] < sampler.get_darkness(x, y):
                    # Strict check: ensure it falls perfectly inside complex boundaries
                    if effective_boundary.contains(Point(x, y)):
                        # A "dot" for a plotter is just a very short line segment
                        dot_geom = LineString([(x, y), (x + cfg.dot_size, y)])
                        new_dots.append(dot_geom)

        if len(new_dots) < cfg.dots:
            logger.warning(
                f"Only generated {len(new_dots)} out of {cfg.dots} requested dots. "
                "The target area might be too light or small."
            )

        logger.success(f"Generated {len(new_dots)} bounded stipple points.")

        return PipelineState(
            boundary=state.boundary, 
            lines=state.lines + new_dots,
            operation_name="photo_stipple"
        )
