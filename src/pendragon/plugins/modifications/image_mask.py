# src/pendragon/plugins/modifications/image_mask.py

import math
from typing import List

from loguru import logger
from pydantic import BaseModel, Field
from shapely.geometry import LineString

from pendragon.core import PipelineState
from pendragon.core import PipelineOperation, register_operation
from pendragon.utils import ImageSampler


class ImageMaskConfig(BaseModel):
    mask_image: str | None = None
    threshold: float = Field(default=0.5, description="Darkness threshold (0.0 to 1.0) to keep lines.")
    sample_step: float = Field(default=0.5, description="Resolution step size for sampling along lines.")


@register_operation("image_mask", config_class=ImageMaskConfig)
class ImageMaskMod(PipelineOperation):
    
    def process(self, state: PipelineState) -> PipelineState:
        active_config = self.config or ImageMaskConfig()
        
        current_boundary = state.boundary
        current_lines = state.lines 
        
        logger.debug(f"Processing boundary: {current_boundary.bounds}")
        logger.debug(f"Using threshold: {active_config.threshold}")
        
        if not active_config.mask_image or not current_lines:
            logger.warning("No mask image provided or no incoming lines to process. Skipping modification.")
            return state

        logger.info(f"Applying mask from {active_config.mask_image}")
        
        # Initialize your existing image sampler using the boundary's outer box
        sampler = ImageSampler(active_config.mask_image, current_boundary.bounds)
        step_size = active_config.sample_step
        
        new_lines: List[LineString] = []

        for line in current_lines:
            # Track points for the current valid segment we are building up
            current_segment_coords = []
            
            # Figure out how many samples we need along this specific line
            line_length = line.length
            if line_length == 0:
                continue
                
            num_samples = max(2, math.ceil(line_length / step_size))
            
            for i in range(num_samples):
                # Calculate normalized distance along the line (0.0 to 1.0)
                distance_fraction = i / (num_samples - 1)
                point = line.interpolate(distance_fraction, normalized=True)
                
                # Check pixel darkness via your utility (0.0 = white, 1.0 = black)
                darkness = sampler.get_darkness(point.x, point.y)
                
                if darkness >= active_config.threshold:
                    # Point is within threshold bounds -> keep drawing
                    current_segment_coords.append((point.x, point.y))
                else:
                    # Hit a mask void -> commit the current active segment if it's long enough
                    if len(current_segment_coords) >= 2:
                        new_lines.append(LineString(current_segment_coords))
                    current_segment_coords = [] # Reset/Lift the pen
            
            # After finishing the line loop, sweep up any trailing segment
            if len(current_segment_coords) >= 2:
                new_lines.append(LineString(current_segment_coords))

        logger.success(f"Mask filtering complete. Retained {len(new_lines)} segmented lines.")
        
        return PipelineState(
            boundary=current_boundary,
            lines=new_lines,
            operation_name="image_mask"
        )
