from typing import List, Optional

from loguru import logger
import numpy as np
from pydantic import Field
from shapely.geometry import LineString

from pendragon.engine import BasePluginConfig
from pendragon.engine import PipelineOperation
from pendragon.engine import PipelineState
from pendragon.engine import register_operation


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

        subdivided_lines: list[LineString] = []
        for line in state.lines:
            # We use Shapely's segmentize, which handles the math of
            # inserting points efficiently along a LineString
            new_line = line.segmentize(
                max_segment_length=cfg.max_segment_length)
            subdivided_lines.append(new_line)

        return PipelineState(boundary=state.boundary,
                             lines=subdivided_lines,
                             operation_name="subdivide_lines")
