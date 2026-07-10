# src/pendragon/plugins/modifications/deduplicate.py

from typing import List

from loguru import logger
from pydantic import BaseModel
from pydantic import Field
from shapely.geometry import LineString
from shapely.strtree import STRtree

from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation


class DeduplicateConfig(BaseModel):
    tolerance: float = Field(
        default=1e-5,
        description="Tolerance for considering two geometries exactly equal.")


@register_operation("deduplicate", config_class=DeduplicateConfig)
class DeduplicateMod(PipelineOperation):

    def process(self, state: PipelineState) -> PipelineState:
        active_config = self.config or DeduplicateConfig()
        current_lines = state.lines

        if not current_lines:
            logger.warning(
                "No lines provided to the deduplicate operation. Skipping.")
            return state

        logger.info(f"Deduplicating {len(current_lines)} lines...")

        # 1. Build a spatial index (R-Tree) of all bounding boxes for fast querying
        tree = STRtree(current_lines)
        duplicates_to_skip = set()
        unique_lines: List[LineString] = []

        # 2. Iterate and compare
        for i, line in enumerate(current_lines):
            # If we've already flagged this line as a duplicate of an earlier one, skip it
            if i in duplicates_to_skip:
                continue

            unique_lines.append(line)

            # Query the R-Tree for lines with overlapping bounding boxes
            query_indices = tree.query(line)

            for j in query_indices:
                if j <= i:
                    continue  # Skip checking against itself or already-processed lines

                other_line = current_lines[j]

                # Use equals_exact to account for tiny floating point differences,
                # checking both forward and reversed directions
                if (line.equals_exact(other_line, active_config.tolerance) or
                        line.equals_exact(other_line.reverse(),
                                          active_config.tolerance)):
                    duplicates_to_skip.add(j)

        logger.success(
            f"Deduplication complete. Removed {len(duplicates_to_skip)} duplicate lines. "
            f"Retained {len(unique_lines)} paths.")

        return PipelineState(boundary=state.boundary,
                             lines=unique_lines,
                             operation_name="deduplicate")
