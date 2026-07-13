import math
from typing import Optional

from loguru import logger
from pydantic import BaseModel
from pydantic import Field
from shapely.geometry import LineString

from pendragon.engine import PipelineContext
from pendragon.engine import PipelineOperation
from pendragon.engine import PipelineState
from pendragon.engine import register_operation
from pendragon.utils import ImageSampler


class ImageMaskConfig(BaseModel):
    mask_image: str = Field(default="",
                            description="Source image.",
                            json_schema_extra={"widget": "file_picker"})
    threshold: float = Field(default=0.5,
                             ge=0.0,
                             le=1.0,
                             description="Darkness threshold to keep lines.")
    sample_step: float = Field(default=0.5,
                               description="Resolution step size for sampling.")


@register_operation("image_mask", config_class=ImageMaskConfig)
class ImageMaskMod(PipelineOperation):

    def process(self,
                state: PipelineState,
                context: Optional[PipelineContext] = None) -> PipelineState:
        cfg = self.config or ImageMaskConfig()
        ctx = context or PipelineContext()

        current_boundary = state.boundary
        current_lines = state.lines

        threshold = ctx.variables.get("threshold", cfg.threshold)
        step_size = ctx.variables.get("sample_step", cfg.sample_step)

        if not cfg.mask_image or not current_lines:
            return state

        logger.info(f"Applying mask from {cfg.mask_image}")
        sampler = ImageSampler(cfg.mask_image, current_boundary.bounds)
        new_lines: list[LineString] = []

        for line in current_lines:
            current_segment_coords = []
            line_length = line.length
            if line_length == 0:
                continue

            num_samples = max(2, math.ceil(line_length / step_size))
            for i in range(num_samples):
                distance_fraction = i / (num_samples - 1)
                point = line.interpolate(distance_fraction, normalized=True)
                darkness = sampler.get_darkness(point.x, point.y)

                if darkness >= threshold:
                    current_segment_coords.append((point.x, point.y))
                else:
                    if len(current_segment_coords) >= 2:
                        new_lines.append(LineString(current_segment_coords))
                    current_segment_coords = []

            if len(current_segment_coords) >= 2:
                new_lines.append(LineString(current_segment_coords))

        logger.success(
            f"Mask filtering complete. Retained {len(new_lines)} segmented lines."
        )
        return PipelineState(boundary=current_boundary,
                             lines=new_lines,
                             operation_name="image_mask")
