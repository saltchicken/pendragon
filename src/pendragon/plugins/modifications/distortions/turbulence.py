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


class TurbulenceConfig(BaseModel):
    amplitude: float = Field(default=3.0, description="How strong the warping effect is")
    frequency: float = Field(default=0.1, description="How tightly the ripples bunch up")
    asymmetry: float = Field(
        default=1.37, 
        description="Multiplier to separate X/Y phase so the distortion isn't perfectly diagonal"
    )
    phase: float = Field(default=0.0, description="Offset for animation or variation")


@register_operation("turbulence", config_class=TurbulenceConfig)
class TurbulenceMod(PipelineOperation):
    """Warps existing lines asymmetrically using a trigonometric pseudo-noise field."""

    def process(self,
                state: PipelineState,
                context: Optional[PipelineContext] = None) -> PipelineState:
        cfg = self.config or TurbulenceConfig()
        ctx = context or PipelineContext()
        current_lines = state.lines

        if not current_lines:
            return state

        amp = ctx.variables.get("amplitude", cfg.amplitude)
        freq = ctx.variables.get("frequency", cfg.frequency)
        asym = ctx.variables.get("asymmetry", cfg.asymmetry)
        phase = ctx.variables.get("phase", cfg.phase)

        logger.info(f"Applying asymmetric turbulence (amp: {amp}, freq: {freq})...")

        warped_lines = []
        for line in current_lines:
            if line.is_empty:
                continue
            
            new_coords = []
            for x, y in line.coords:
                # Interlocking sines and cosines with asymmetric scaling
                dx = math.sin((x * freq) + phase) * math.cos(y * freq * asym) * amp
                dy = math.sin(x * freq * asym) * math.cos((y * freq) + phase) * amp
                
                new_coords.append((x + dx, y + dy))
            
            warped_lines.append(LineString(new_coords))

        logger.success("Turbulence warping complete.")
        return PipelineState(boundary=state.boundary,
                             lines=warped_lines,
                             operation_name="turbulence")
