from typing import List, Optional

from loguru import logger
from pydantic import BaseModel, Field
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge, unary_union

from pendragon.core import PipelineOperation, PipelineState, PipelineContext, register_operation


class MergeConfig(BaseModel):
    precision: float = Field(default=0.0, description="Grid precision for unioning (0.0 for default).")


@register_operation("merge", config_class=MergeConfig)
class MergeMod(PipelineOperation):
    def process(self, state: PipelineState, context: Optional[PipelineContext] = None) -> PipelineState:
        current_lines = state.lines
        if not current_lines: return state

        logger.info(f"Merging and deduplicating {len(current_lines)} lines...")

        union_geom = unary_union(current_lines)
        merged_geom = linemerge(union_geom)

        final_lines: List[LineString] = []
        if isinstance(merged_geom, LineString):
            if not merged_geom.is_empty: final_lines.append(merged_geom)
        elif isinstance(merged_geom, MultiLineString):
            for line in merged_geom.geoms:
                if not line.is_empty: final_lines.append(line)
        else:
            logger.warning(f"Unexpected geometric type returned during merge: {type(merged_geom)}")

        logger.success(f"Deduplication complete. Reduced geometry to {len(final_lines)} continuous paths.")
        return PipelineState(boundary=state.boundary, lines=final_lines, operation_name="merge")
