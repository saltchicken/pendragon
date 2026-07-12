from typing import List, Optional

from loguru import logger
from nodeweaver.models import PipelineContext
from pendragon.registry import dxf_registry
from pendragon.registry import PendragonOperation
from pendragon.state import GeometryState
from pydantic import BaseModel
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry import MultiLineString


class SimplifyConfig(BaseModel):
    tolerance: float = Field(
        default=0.1,
        ge=0.0,
        description="Max allowed distance between original and simplified line."
    )
    preserve_topology: bool = Field(default=False,
                                    description="Prevents invalid geometries.")


@dxf_registry.register("simplify", config_class=SimplifyConfig)
class SimplifyMod(PendragonOperation):

    def process(self,
                state: GeometryState,
                context: Optional[PipelineContext] = None) -> GeometryState:
        cfg = self.config or SimplifyConfig()
        ctx = context or PipelineContext()
        current_lines = state.lines

        if not current_lines:
            return state

        tolerance = ctx.get("tolerance", cfg.tolerance)
        preserve = ctx.get("preserve_topology", cfg.preserve_topology)

        logger.info(
            f"Simplifying {len(current_lines)} lines with tolerance {tolerance}..."
        )

        simplified_lines: List[LineString] = []
        for line in current_lines:
            if line.is_empty:
                continue
            simplified = line.simplify(tolerance, preserve_topology=preserve)

            if simplified.is_empty:
                continue
            elif isinstance(simplified, LineString):
                simplified_lines.append(simplified)
            elif isinstance(simplified, MultiLineString):
                simplified_lines.extend(list(simplified.geoms))

        logger.success(
            f"Simplification complete. Yielded {len(simplified_lines)} lines.")
        return GeometryState(boundary=state.boundary,
                             lines=simplified_lines,
                             operation_name="simplify")
