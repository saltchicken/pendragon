import math
from typing import List

from pydantic import BaseModel
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

from pendragon.core import register_operation
from pendragon.core import OperationContext


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

class ImageSampler:

    def __init__(self, image_path: str, bounds: tuple):
        self.img = Image.open(image_path).convert("L")
        self.minx, self.miny, self.maxx, self.maxy = bounds
        self.width = self.maxx - self.minx
        self.height = self.maxy - self.miny

    def get_darkness(self, x: float, y: float) -> float:
        if self.width == 0 or self.height == 0:
            return 0.0
        px = max(
            0,
            min(int(((x - self.minx) / self.width) * (self.img.width - 1)),
                self.img.width - 1))
        py = max(
            0,
            min(
                int((1.0 - ((y - self.miny) / self.height)) *
                    (self.img.height - 1)), self.img.height - 1))
        return (255 - self.img.getpixel((px, py))) / 255.0

