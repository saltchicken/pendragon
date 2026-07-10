from typing import List, Optional

from loguru import logger
from pydantic import BaseModel
from pydantic import Field
from shapely.geometry import LineString
from shapely.strtree import STRtree

from pendragon.core import PipelineContext
from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation


class DeduplicateConfig(BaseModel):
    tolerance: float = Field(
        default=1e-5, description="Tolerance for exactly equal geometries.")


@register_operation("deduplicate", config_class=DeduplicateConfig)
class DeduplicateMod(PipelineOperation):

    def process(self,
                state: PipelineState,
                context: Optional[PipelineContext] = None) -> PipelineState:
        cfg = self.config or DeduplicateConfig()
        ctx = context or PipelineContext()
        current_lines = state.lines

        if not current_lines:
            return state

        tolerance = ctx.variables.get("tolerance", cfg.tolerance)
        logger.info(f"Deduplicating {len(current_lines)} lines...")

        tree = STRtree(current_lines)
        duplicates_to_skip = set()
        unique_lines: List[LineString] = []

        for i, line in enumerate(current_lines):
            if i in duplicates_to_skip:
                continue
            unique_lines.append(line)

            query_indices = tree.query(line)
            for j in query_indices:
                if j <= i:
                    continue
                other_line = current_lines[j]
                if (line.equals_exact(other_line, tolerance) or
                        line.equals_exact(other_line.reverse(), tolerance)):
                    duplicates_to_skip.add(j)

        logger.success(
            f"Deduplication complete. Removed {len(duplicates_to_skip)} duplicate lines."
        )
        return PipelineState(boundary=state.boundary,
                             lines=unique_lines,
                             operation_name="deduplicate")
