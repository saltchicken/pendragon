import math
from typing import List

from pydantic import BaseModel
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

from pendragon.core import OperationContext
from pendragon.core import register_operation


class ImageMaskConfig(BaseModel):
    mask_image: str | None = None
    threshold: float = Field(default=0.5)


@register_operation("image_mask", config_class=ImageMaskConfig)
class ImageMaskMod:

    def process(self, context: OperationContext) -> List[LineString]:

        test_mask_list: List[LineString] = []

        boundary = context.boundary
        print(boundary)

        return test_mask_list


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
