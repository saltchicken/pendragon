from typing import List, Optional

from loguru import logger
import numpy as np
from pydantic import Field
from shapely.geometry import LineString

from pendragon.engine import BasePluginConfig
from pendragon.engine import PipelineOperation
from pendragon.engine import PipelineState
from pendragon.engine import register_operation


class JitterLinesConfig(BasePluginConfig):
    amount: float = Field(default=1.0,
                          description="Maximum displacement distance.")
    seed: int = Field(default=42,
                      description="Random seed for reproducibility.")


@register_operation("jitter_lines", config_class=JitterLinesConfig)
class JitterLinesMod(PipelineOperation):
    """Applies random vertex displacement to all current lines."""

    def process(self, state: PipelineState, context=None) -> PipelineState:
        cfg = self.config or JitterLinesConfig()
        if not state.lines:
            return state

        logger.info(
            f"Applying jitter (amount={cfg.amount}) to {len(state.lines)} paths."
        )
        np.random.seed(cfg.seed)

        jittered_lines: list[LineString] = []
        for line in state.lines:
            # Add random noise to each coordinate
            coords = np.array(line.coords)
            noise = np.random.uniform(-cfg.amount, cfg.amount, coords.shape)
            jittered_coords = coords + noise
            jittered_lines.append(LineString(jittered_coords))

        return PipelineState(boundary=state.boundary,
                             lines=jittered_lines,
                             operation_name="jitter_lines")
