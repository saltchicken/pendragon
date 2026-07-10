from typing import List

from loguru import logger
from pydantic import BaseModel
from pydantic import Field
from shapely.affinity import scale
from shapely.geometry import LineString

from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation


class ScaleConfig(BaseModel):
    factor: float = Field(
        default=1.0,
        description="Uniform scaling multiplier (e.g., 2.0 doubles the size).")
    origin: str = Field(
        default="center",
        description=
        "Origin point for scaling: 'center', 'centroid', or an exact coordinate."
    )


@register_operation("scale", config_class=ScaleConfig)
class ScaleMod(PipelineOperation):
    """Scales all current geometries uniformly."""

    def process(self, state: PipelineState) -> PipelineState:
        cfg = self.config or ScaleConfig()
        current_lines = state.lines

        if not current_lines:
            logger.warning(
                "No lines provided to the scale operation. Skipping.")
            return state

        logger.info(
            f"Scaling {len(current_lines)} lines by a factor of {cfg.factor}..."
        )

        scaled_lines: List[LineString] = []

        for line in current_lines:
            if line.is_empty:
                continue

            # Shapely's scale handles the matrix math for us
            scaled_geom = scale(line,
                                xfact=cfg.factor,
                                yfact=cfg.factor,
                                origin=cfg.origin)
            scaled_lines.append(scaled_geom)

        logger.success("Scaling complete.")

        return PipelineState(
            boundary=state.boundary,  # Keep the original boundary intact
            lines=scaled_lines,
            operation_name="scale")
