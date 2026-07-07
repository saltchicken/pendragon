import math
from typing import List

from pydantic import BaseModel
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

from pendragon import ImageSampler
from pendragon import register_operation
from pendragon import OperationContext


class ImageMaskConfig(BaseModel):
    mask_image: str | None = None
    threshold: float = Field(default=0.5)


@register_operation("image_mask", config_class=ImageMaskConfig)
class ImageMaskMod:

    def process(self, context: OperationContext) -> List[LineString]:
        params = context.config.params

        mask_image = params.mask_image
        if not mask_image:
            return lines

        mask_sampler = ImageSampler(mask_image, context.bounds)
        threshold = params.threshold
        masked_lines = []
        step_res = 1.0

        for line in lines:
            length = line.length
            if length == 0:
                continue

            steps = max(2, int(math.ceil(length / step_res)))
            current_segment = []

            for i in range(steps + 1):
                pt = line.interpolate(i / steps, normalized=True)
                if mask_sampler.get_darkness(pt.x, pt.y) > threshold:
                    current_segment.append((pt.x, pt.y))
                else:
                    if len(current_segment) > 1:
                        masked_lines.append(LineString(current_segment))
                    current_segment = []

            if len(current_segment) > 1:
                masked_lines.append(LineString(current_segment))

        return masked_lines

