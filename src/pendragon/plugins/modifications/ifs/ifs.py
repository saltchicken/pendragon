from typing import List, Optional

from loguru import logger
from pydantic import BaseModel, Field
from shapely.affinity import affine_transform
from shapely.geometry import LineString

from pendragon.engine import PipelineContext, PipelineOperation, PipelineState, register_operation


class IFSConfig(BaseModel):
    iterations: int = Field(
        default=3,
        ge=1,
        le=8,
        description="Number of recursive iterations. Keep low (3-5) to avoid exponential line counts."
    )
    transforms: List[List[float]] = Field(
        default=[
            [0.5, 0.0, 0.0, 0.5, 0.0, 0.0],       # Scale 50%, no translation
            [0.5, 0.0, 0.0, 0.5, 100.0, 0.0],     # Scale 50%, shift right
            [0.5, 0.0, 0.0, 0.5, 50.0, 86.6]      # Scale 50%, shift up/right
        ],
        description="List of affine matrices in the format: [a, b, d, e, xoff, yoff]."
    )


@register_operation("ifs", config_class=IFSConfig)
class IFSMod(PipelineOperation):
    """
    Applies Iterated Function System (IFS) affine transformations.
    Mimics the core structural behavior of Apophysis by duplicating 
    and recursively transforming geometry.
    """

    def process(self,
                state: PipelineState,
                context: Optional[PipelineContext] = None) -> PipelineState:
        cfg = self.config or IFSConfig()
        ctx = context or PipelineContext()
        
        current_lines = state.lines
        if not current_lines:
            return state

        iterations = ctx.variables.get("iterations", cfg.iterations)
        transforms = ctx.variables.get("transforms", cfg.transforms)
                
        logger.info(f"Applying IFS ({len(transforms)} transforms, {iterations} iterations)...")
        
        # Start with our base geometry
        working_lines = current_lines
        
        for i in range(iterations):
            next_lines: List[LineString] = []
            
            for transform_matrix in transforms:
                if len(transform_matrix) != 6:
                    logger.warning(f"Skipping invalid transform {transform_matrix}. Must have exactly 6 values.")
                    continue
                    
                for line in working_lines:
                    if line.is_empty:
                        continue
                    # Apply the [a, b, d, e, xoff, yoff] matrix
                    transformed_line = affine_transform(line, transform_matrix)
                    next_lines.append(transformed_line)
                    
            working_lines = next_lines
            logger.debug(f"IFS Iteration {i+1} complete: {len(working_lines)} paths.")
            
        logger.success(f"IFS Fractal generation complete. Yielded {len(working_lines)} final lines.")
        return PipelineState(
            boundary=state.boundary,
            lines=working_lines,
            operation_name="ifs"
        )
