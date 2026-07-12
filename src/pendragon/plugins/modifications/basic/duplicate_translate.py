from typing import Optional

from loguru import logger
from pydantic import BaseModel, Field
from shapely.affinity import translate

from pendragon.engine import PipelineContext, PipelineOperation, PipelineState, register_operation


class DuplicateTranslateConfig(BaseModel):
    copies: int = Field(
        default=1, 
        ge=1, 
        description="Number of duplicate copies to generate."
    )
    translate_x: float = Field(
        default=5.0, 
        description="X-axis translation applied to each successive copy."
    )
    translate_y: float = Field(
        default=5.0, 
        description="Y-axis translation applied to each successive copy."
    )


@register_operation("duplicate_translate", config_class=DuplicateTranslateConfig)
class DuplicateTranslateMod(PipelineOperation):
    """Duplicates existing lines and shifts the new copies by a set offset."""

    def process(self,
                state: PipelineState,
                context: Optional[PipelineContext] = None) -> PipelineState:
        
        cfg = self.config or DuplicateTranslateConfig()
        ctx = context or PipelineContext()
        current_lines = state.lines

        if not current_lines:
            return state

        copies = ctx.variables.get("copies", cfg.copies)
        tx = ctx.variables.get("translate_x", cfg.translate_x)
        ty = ctx.variables.get("translate_y", cfg.translate_y)

        logger.info(f"Duplicating lines {copies} times with offset ({tx}, {ty}) per copy...")

        # Start the new list with the original lines intact
        all_lines = list(current_lines)

        for i in range(1, copies + 1):
            # Calculate cumulative offset for this specific copy instance
            current_tx = tx * i
            current_ty = ty * i
            
            for line in current_lines:
                if line.is_empty:
                    continue
                
                # Apply the transformation and append the new line
                duplicated_line = translate(line, xoff=current_tx, yoff=current_ty)
                all_lines.append(duplicated_line)

        logger.success(f"Duplication complete. Total lines went from {len(current_lines)} to {len(all_lines)}.")
        
        return PipelineState(
            boundary=state.boundary,
            lines=all_lines,
            operation_name="duplicate_translate"
        )
