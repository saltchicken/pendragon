# src/pendragon/plugins/modifications/merge.py

from typing import List

from loguru import logger
from pydantic import BaseModel
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry import MultiLineString
from shapely.ops import linemerge
from shapely.ops import unary_union

from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation


class MergeConfig(BaseModel):
    # You can add a tolerance setting here if you want to snap nearby points first,
    # but standard unary_union handles identical overlapping geometry perfectly.
    precision: float = Field(
        default=0.0,
        description="Grid precision for unioning (0.0 for default).")


@register_operation("merge", config_class=MergeConfig)
class MergeMod(PipelineOperation):

    def process(self, state: PipelineState) -> PipelineState:
        current_lines = state.lines

        if not current_lines:
            logger.warning(
                "No lines provided to the merge operation. Skipping.")
            return state

        logger.info(f"Merging and deduplicating {len(current_lines)} lines...")

        # 1. Collapse duplicate segments and node intersections
        # unary_union dissolves duplicate lines entirely
        union_geom = unary_union(current_lines)

        # 2. Merge contiguous lines back into unified paths
        merged_geom = linemerge(union_geom)

        # 3. Unpack the results back into a clean List[LineString]
        final_lines: List[LineString] = []

        if isinstance(merged_geom, LineString):
            if not merged_geom.is_empty:
                final_lines.append(merged_geom)
        elif isinstance(merged_geom, MultiLineString):
            for line in merged_geom.geoms:
                if not line.is_empty:
                    final_lines.append(line)
        else:
            # Fallback if something else is returned
            logger.warning(
                f"Unexpected geometric type returned during merge: {type(merged_geom)}"
            )

        logger.success(
            f"Deduplication complete. Reduced geometry to {len(final_lines)} continuous paths."
        )

        return PipelineState(boundary=state.boundary,
                             lines=final_lines,
                             operation_name="merge")
