from typing import List

from loguru import logger
from pydantic import BaseModel
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry import MultiLineString

# Pendragon core imports
from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation


class SimplifyConfig(BaseModel):
    tolerance: float = Field(
        default=0.1,
        ge=0.0,
        description=
        "Maximum allowed perpendicular distance between original and simplified line."
    )
    preserve_topology: bool = Field(
        default=False,
        description=
        "If True, prevents invalid geometries or self-intersections during simplification."
    )


@register_operation("simplify", config_class=SimplifyConfig)
class SimplifyMod(PipelineOperation):

    def process(self, state: PipelineState) -> PipelineState:
        # Fallback to default if no config provided in YAML
        active_config = self.config or SimplifyConfig()

        tolerance = active_config.tolerance
        preserve = active_config.preserve_topology
        current_lines = state.lines

        if not current_lines:
            logger.warning(
                "No lines provided to the simplify operation. Skipping.")
            return state

        logger.info(
            f"Simplifying {len(current_lines)} lines with tolerance {tolerance}..."
        )

        simplified_lines: List[LineString] = []

        for line in current_lines:
            if line.is_empty:
                continue

            # Utilize Shapely's built-in Douglas-Peucker simplification
            simplified = line.simplify(tolerance, preserve_topology=preserve)

            if simplified.is_empty:
                continue
            elif isinstance(simplified, LineString):
                simplified_lines.append(simplified)
            elif isinstance(simplified, MultiLineString):
                # If topology preservation forces a split, unpack the resulting geometries
                simplified_lines.extend(list(simplified.geoms))

        logger.success(
            f"Simplification complete. Yielded {len(simplified_lines)} lines.")

        # Return a fresh immutable state for the next pipeline step
        return PipelineState(boundary=state.boundary,
                             lines=simplified_lines,
                             operation_name="simplify")
