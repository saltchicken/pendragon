import math
from typing import List, Literal, Optional, Tuple

from loguru import logger
from pydantic import BaseModel, Field
from shapely.affinity import affine_transform
from shapely.geometry import LineString

from pendragon.engine import PipelineContext, PipelineOperation, PipelineState, register_operation


class IFSTransform(BaseModel):
    """Configuration for a single branch of the fractal."""
    matrix: List[float] = Field(
        ..., 
        min_length=6, 
        max_length=6,
        description="Affine matrix: [a, b, d, e, xoff, yoff]"
    )
    variation: Literal["linear", "sinusoidal", "spherical", "swirl"] = Field(
        default="linear",
        description="The non-linear math function applied after the affine transform."
    )


class IFSConfig(BaseModel):
    iterations: int = Field(default=3, ge=1, le=8)
    transforms: List[IFSTransform] = Field(default_factory=list)


@register_operation("ifs", config_class=IFSConfig)
class IFSMod(PipelineOperation):

    def apply_variation(self, x: float, y: float, var_type: str) -> Tuple[float, float]:
        """
        Applies non-linear math to the coordinates. 
        Note: Because CNC coordinates are typically large (e.g., 0-200mm), 
        we apply scaling factors so the math behaves beautifully.
        """
        if var_type == "linear":
            return x, y
            
        elif var_type == "sinusoidal":
            # Creates rippling, wave-like interference patterns
            scale = 20.0
            return (math.sin(x / scale) * scale * 2, 
                    math.sin(y / scale) * scale * 2)
                    
        elif var_type == "spherical":
            # Inverts the geometry inside-out like a glass marble
            # Shift slightly to prevent division by zero
            r2 = (x**2 + y**2) + 1e-6 
            radius = 10000.0  # Controls the "size" of the glass sphere
            return ((x / r2) * radius, (y / r2) * radius)
            
        elif var_type == "swirl":
            # Twists the coordinates based on their distance from origin
            r2 = (x**2 + y**2) / 5000.0
            sin_r2 = math.sin(r2)
            cos_r2 = math.cos(r2)
            return (x * sin_r2 - y * cos_r2, x * cos_r2 + y * sin_r2)
            
        return x, y

    def process(self,
                state: PipelineState,
                context: Optional[PipelineContext] = None) -> PipelineState:
        cfg = self.config or IFSConfig()
        ctx = context or PipelineContext()
        
        current_lines = state.lines
        if not current_lines:
            return state

        iterations = ctx.variables.get("iterations", cfg.iterations)
        
        logger.info(f"Applying Advanced IFS ({len(cfg.transforms)} transforms, {iterations} iterations)...")
        
        working_lines = current_lines
        
        for i in range(iterations):
            next_lines: List[LineString] = []
            
            for transform_cfg in cfg.transforms:
                matrix = transform_cfg.matrix
                variation = transform_cfg.variation
                
                for line in working_lines:
                    if line.is_empty:
                        continue
                        
                    # 1. Apply the standard Affine Transform (scale/rotate/translate)
                    affine_line = affine_transform(line, matrix)
                    
                    # 2. Apply the Non-Linear Variation
                    if variation != "linear":
                        warped_coords = [
                            self.apply_variation(x, y, variation) 
                            for x, y in affine_line.coords
                        ]
                        next_lines.append(LineString(warped_coords))
                    else:
                        next_lines.append(affine_line)
                    
            working_lines = next_lines
            logger.debug(f"IFS Iteration {i+1} complete: {len(working_lines)} paths.")
            
        logger.success(f"IFS generation complete. Yielded {len(working_lines)} lines.")
        return PipelineState(
            boundary=state.boundary,
            lines=working_lines,
            operation_name="ifs"
        )
