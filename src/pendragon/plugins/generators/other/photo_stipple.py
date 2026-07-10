from typing import List, Optional

from loguru import logger
import numpy as np
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry import Point

from pendragon.core import BasePluginConfig
from pendragon.core import PipelineContext
from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation
from pendragon.utils import ImageSampler


class PhotoStippleConfig(BasePluginConfig):
    dots: int = Field(default=5000,
                      gt=0,
                      description="Target number of stipple dots to generate.")
    image_path: str | None = Field(default=None, description="Source image.")
    dot_size: float = Field(default=0.1,
                            gt=0.0,
                            description="Length of microscopic line.")
    seed: int = Field(default=42, description="Random seed.")


@register_operation("photo_stipple", config_class=PhotoStippleConfig)
class PhotoStippleGen(PipelineOperation):

    def process(self,
                state: PipelineState,
                context: Optional[PipelineContext] = None) -> PipelineState:
        cfg = self.config or PhotoStippleConfig()
        ctx = context or PipelineContext()
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            return state
        if not cfg.image_path:
            return state

        dots = int(ctx.variables.get("dots", cfg.dots))
        dot_size = ctx.variables.get("dot_size", cfg.dot_size)

        logger.info(f"Generating {dots} stipple dots from {cfg.image_path}...")

        minx, miny, maxx, maxy = effective_boundary.bounds
        sampler = ImageSampler(cfg.image_path, effective_boundary.bounds)
        np.random.seed(cfg.seed)

        new_dots: List[LineString] = []
        batch_size, max_batches, batches = dots * 2, 100, 0

        while len(new_dots) < dots and batches < max_batches:
            batches += 1
            xs = np.random.uniform(minx, maxx, batch_size)
            ys = np.random.uniform(miny, maxy, batch_size)
            rand_thresholds = np.random.random(batch_size)

            for i in range(batch_size):
                if len(new_dots) >= dots:
                    break
                x, y = xs[i], ys[i]
                if rand_thresholds[i] < sampler.get_darkness(x, y):
                    if effective_boundary.contains(Point(x, y)):
                        new_dots.append(LineString([(x, y), (x + dot_size, y)]))

        if len(new_dots) < dots:
            logger.warning(
                f"Only generated {len(new_dots)} out of {dots} requested dots.")

        logger.success(f"Generated {len(new_dots)} bounded stipple points.")
        return PipelineState(boundary=state.boundary,
                             lines=state.lines + new_dots,
                             operation_name="photo_stipple")
