# src/pendragon/plugins/generators/guilloche.py

import math
from typing import List

from loguru import logger
from pydantic import BaseModel, Field
import numpy as np
from shapely.geometry import LineString, MultiLineString

from pendragon.core import PipelineOperation, PipelineState, register_operation
from pendragon.core import BasePluginConfig


class GuillocheConfig(BasePluginConfig):
    center_x: float = Field(default=100.0, description="X coordinate of the pattern center.")
    center_y: float = Field(default=100.0, description="Y coordinate of the pattern center.")
    R: float = Field(default=50.0, description="Radius of the fixed outer circle.")
    r: float = Field(default=35.0, description="Radius of the rolling inner circle.")
    p: float = Field(default=25.0, description="Distance from the pen to the center of the rolling circle.")
    steps: int = Field(default=1000, description="Total number of linear steps/points sampled along the curve.")
    revolutions: float = Field(default=10.0, description="Number of full outer loops ($2\pi$ rotations) to complete.")
    amplitude_mod: float = Field(default=0.0, description="Amplitude of secondary wave modulation.")
    frequency_mod: float = Field(default=0.0, description="Frequency multiplier of secondary wave modulation.")


@register_operation("guilloche", config_class=GuillocheConfig)
class GuillocheGen(PipelineOperation):

    def process(self, state: PipelineState) -> PipelineState:
        cfg = self.config or GuillocheConfig()
        boundary = self.get_effective_boundary(state)

        logger.info(
            f"Generating guilloche geometric pattern at ({cfg.center_x}, {cfg.center_y}) "
            f"over {cfg.revolutions} revolutions."
        )

        # 1. Parameterize and calculate points using classic hypotrochoid mathematics
        # with secondary wave modulation for an authentic security-pattern look.
        theta = np.linspace(0, cfg.revolutions * 2 * np.pi, cfg.steps)
        
        # Hypotrochoid base math
        r_diff = cfg.R - cfg.r
        ratio = r_diff / cfg.r
        
        # Apply optional harmonic modulation envelope
        mod_envelope = 1.0 + cfg.amplitude_mod * np.sin(cfg.frequency_mod * theta)
        effective_p = cfg.p * mod_envelope

        x = cfg.center_x + r_diff * np.cos(theta) + effective_p * np.cos(ratio * theta)
        y = cfg.center_y + r_diff * np.sin(theta) - effective_p * np.sin(ratio * theta)

        coords = np.column_stack((x, y))
        raw_pattern_line = LineString(coords)

        # 2. Clip the generated curve against the current pipeline boundary
        clipped_lines: List[LineString] = []
        if raw_pattern_line.intersects(boundary):
            clipped = raw_pattern_line.intersection(boundary)

            if isinstance(clipped, LineString) and not clipped.is_empty:
                clipped_lines.append(clipped)
            elif isinstance(clipped, MultiLineString):
                for sub_line in clipped.geoms:
                    if not sub_line.is_empty:
                        clipped_lines.append(sub_line)

        logger.success(f"Generated guilloche pattern segments. Retained {len(clipped_lines)} continuous paths.")

        return PipelineState(
            boundary=state.boundary,
            lines=clipped_lines,
            operation_name="guilloche"
        )
