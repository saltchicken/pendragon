import math
from typing import Optional

from loguru import logger
from pydantic import BaseModel, Field
from shapely.geometry import LineString, Point

from pendragon.core import PipelineContext, PipelineOperation, PipelineState, register_operation
from pendragon.utils import ImageSampler

class ImageHalftoneConfig(BaseModel):
    source_image: str = Field(
        default="", 
        description="Source image to map.",
        json_schema_extra={"widget": "file_picker"}
    )
    spacing: float = Field(
        default=5.0, 
        ge=0.1,
        description="Grid spacing between generated shapes."
    )
    min_radius: float = Field(
        default=0.1, 
        ge=0.0,
        description="Radius size in pure white areas."
    )
    max_radius: float = Field(
        default=2.5, 
        ge=0.1,
        description="Radius size in pure black areas."
    )

@register_operation("image_halftone", config_class=ImageHalftoneConfig)
class ImageHalftoneGen(PipelineOperation):
    def process(self, state: PipelineState, context: Optional[PipelineContext] = None) -> PipelineState:
        cfg = self.config or ImageHalftoneConfig()
        
        if not cfg.source_image:
            logger.warning("No source image provided. Skipping halftone generation.")
            return state

        effective_boundary = self.get_effective_boundary(state)
        minx, miny, maxx, maxy = effective_boundary.bounds

        logger.info(f"Generating halftone pattern from {cfg.source_image}")
        sampler = ImageSampler(cfg.source_image, effective_boundary.bounds)
        
        new_lines = []
        
        # 1. Iterate over the boundary in a grid
        current_x = minx
        while current_x <= maxx:
            current_y = miny
            while current_y <= maxy:
                
                # 2. Sample the image darkness (0.0 to 1.0) at this specific X/Y coordinate
                darkness = sampler.get_darkness(current_x, current_y)
                
                # 3. Map the 0-1 darkness to our target radius range (Lerp)
                radius = cfg.min_radius + (darkness * (cfg.max_radius - cfg.min_radius))
                
                # 4. Generate the geometry if the radius is large enough to warrant it
                if radius > 0.05:
                    # Create a circle and extract its perimeter as a drawable LineString
                    circle_poly = Point(current_x, current_y).buffer(radius, resolution=16)
                    new_lines.append(LineString(circle_poly.exterior.coords))
                
                current_y += cfg.spacing
            current_x += cfg.spacing

        logger.success(f"Halftone generation complete. Created {len(new_lines)} shapes.")
        
        # 5. Append the new lines to the existing state
        return PipelineState(
            boundary=state.boundary,
            lines=state.lines + new_lines,
            operation_name="image_halftone"
        )
