from typing import List

from loguru import logger
from pydantic import BaseModel
from shapely.geometry import LineString
from shapely.geometry import MultiLineString

from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation


class ClipConfig(BaseModel):
    pass


@register_operation("clip", config_class=ClipConfig)
class ClipMod(PipelineOperation):

    def process(self, state: PipelineState) -> PipelineState:
        current_lines = state.lines
        boundary = state.boundary

        if not current_lines or not boundary:
            logger.warning("No lines or boundary provided to clip operation. Skipping.")
            return state

        logger.info(
            f"Clipping {len(current_lines)} lines strictly to the current pipeline boundary..."
        )

        clipped_lines: List[LineString] = []

        for line in current_lines:
            if line.intersects(boundary):
                clipped = line.intersection(boundary)

                if isinstance(clipped, LineString) and not clipped.is_empty:
                    clipped_lines.append(clipped)
                elif isinstance(clipped, MultiLineString):
                    for sub_line in clipped.geoms:
                        if not sub_line.is_empty:
                            clipped_lines.append(sub_line)

        logger.success(
            f"Clipping complete. Yielded {len(clipped_lines)} bounded lines."
        )

        return PipelineState(boundary=boundary,
                             lines=clipped_lines,
                             operation_name="clip")
