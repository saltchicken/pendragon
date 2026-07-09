# src/pendragon/plugins/generators/guilloche.py

import math
from typing import List

from loguru import logger
import numpy as np
from pydantic import BaseModel
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry import MultiLineString
from shapely.geometry import MultiPolygon
from shapely.geometry import Polygon

from pendragon.core import CenteredPluginConfig
from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation
from pendragon.utils import extract_target_polygons


class GuillocheConfig(CenteredPluginConfig):
    R: float = Field(default=50.0,
                     description="Radius of the fixed outer circle.")
    r: float = Field(default=35.0,
                     description="Radius of the rolling inner circle.")
    p: float = Field(
        default=25.0,
        description="Distance from the pen to the center of the rolling circle."
    )
    steps: int = Field(
        default=1000,
        description=
        "Total number of linear steps/points sampled along the curve.")
    revolutions: float = Field(
        default=10.0,
        description="Number of full outer loops ($2\pi$ rotations) to complete."
    )
    amplitude_mod: float = Field(
        default=0.0, description="Amplitude of secondary wave modulation.")
    frequency_mod: float = Field(
        default=0.0,
        description="Frequency multiplier of secondary wave modulation.")


@register_operation("guilloche", config_class=GuillocheConfig)
class GuillocheGen(PipelineOperation):

    def process(self, state: PipelineState) -> PipelineState:
        cfg = self.config or GuillocheConfig()
        boundary = self.get_effective_boundary(state)

        polygons = extract_target_polygons(boundary, cfg.group_boundaries)

        clipped_lines: List[LineString] = []

        logger.info(
            f"Generating guilloche pattern over {cfg.revolutions} revolutions "
            f"across {len(polygons)} boundary region(s).")

        for poly in polygons:
            # Fallback to centroid if coordinates are not strictly defined
            cx = cfg.center_x if cfg.center_x is not None else poly.centroid.x
            cy = cfg.center_y if cfg.center_y is not None else poly.centroid.y

            theta = np.linspace(0, cfg.revolutions * 2 * np.pi, cfg.steps)

            # Hypotrochoid base math
            r_diff = cfg.R - cfg.r
            ratio = r_diff / cfg.r

            # Apply optional harmonic modulation envelope
            mod_envelope = 1.0 + cfg.amplitude_mod * np.sin(
                cfg.frequency_mod * theta)
            effective_p = cfg.p * mod_envelope

            x = cx + r_diff * np.cos(theta) + effective_p * np.cos(
                ratio * theta)
            y = cy + r_diff * np.sin(theta) - effective_p * np.sin(
                ratio * theta)

            coords = np.column_stack((x, y))
            raw_pattern_line = LineString(coords)

            if raw_pattern_line.intersects(poly):
                clipped = raw_pattern_line.intersection(poly)

                if isinstance(clipped, LineString) and not clipped.is_empty:
                    clipped_lines.append(clipped)
                elif isinstance(clipped, MultiLineString):
                    for sub_line in clipped.geoms:
                        if not sub_line.is_empty:
                            clipped_lines.append(sub_line)

        logger.success(
            f"Generated guilloche pattern segments. Retained {len(clipped_lines)} continuous paths."
        )

        return PipelineState(boundary=state.boundary,
                             lines=state.lines + clipped_lines,
                             operation_name="guilloche")
