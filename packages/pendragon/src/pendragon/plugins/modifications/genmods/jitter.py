from typing import List, Optional

from loguru import logger
from nodeweaver.models import PipelineContext
import numpy as np
from pendragon.registry import dxf_registry
from pendragon.registry import PendragonBaseConfig
from pendragon.registry import PendragonOperation
from pendragon.state import GeometryState
from pydantic import Field
from shapely.geometry import LineString


class JitterLinesConfig(PendragonBaseConfig):
    amount: float = Field(default=1.0,
                          description="Maximum displacement distance.")
    seed: int = Field(default=42,
                      description="Random seed for reproducibility.")


@dxf_registry.register("jitter_lines", config_class=JitterLinesConfig)
class JitterLinesMod(PendragonOperation):
    """Applies random vertex displacement to all current lines."""

    def process(self,
                state: GeometryState,
                context: Optional[PipelineContext] = None) -> GeometryState:
        cfg = self.config or JitterLinesConfig()
        if not state.lines:
            return state

        logger.info(
            f"Applying jitter (amount={cfg.amount}) to {len(state.lines)} paths."
        )
        np.random.seed(cfg.seed)

        jittered_lines: List[LineString] = []
        for line in state.lines:
            # Add random noise to each coordinate
            coords = np.array(line.coords)
            noise = np.random.uniform(-cfg.amount, cfg.amount, coords.shape)
            jittered_coords = coords + noise
            jittered_lines.append(LineString(jittered_coords))

        return GeometryState(boundary=state.boundary,
                             lines=jittered_lines,
                             operation_name="jitter_lines")
