from typing import List, Optional

from loguru import logger
import numpy as np
from pydantic import Field
from shapely.geometry import LineString

from pendragon.core import BasePluginConfig
from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation


class SubdivideConfig(BasePluginConfig):
    max_segment_length: float = Field(
        default=1.0,
        description="Maximum length of a segment before it gets subdivided.")


@register_operation("subdivide_lines", config_class=SubdivideConfig)
class SubdivideLinesMod(PipelineOperation):
    """Interpolates points into existing lines to ensure segment density."""

    def process(self, state: PipelineState, context=None) -> PipelineState:
        cfg = self.config or SubdivideConfig()
        if not state.lines:
            return state

        logger.info(
            f"Subdividing lines with max length {cfg.max_segment_length}.")

        subdivided_lines: List[LineString] = []
        for line in state.lines:
            # We use Shapely's segmentize, which handles the math of
            # inserting points efficiently along a LineString
            new_line = line.segmentize(
                max_segment_length=cfg.max_segment_length)
            subdivided_lines.append(new_line)

        return PipelineState(boundary=state.boundary,
                             lines=subdivided_lines,
                             operation_name="subdivide_lines")
