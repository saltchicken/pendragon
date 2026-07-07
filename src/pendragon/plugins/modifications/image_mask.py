import math
from typing import List

from pydantic import BaseModel
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

from pendragon.core import OperationContext
from pendragon.core import register_operation
from pendragon.utils import ImageSampler


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


