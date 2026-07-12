import math
from typing import List, Optional

from loguru import logger
from nodeweaver.models import PipelineContext
from pendragon.registry import dxf_registry
from pendragon.registry import PendragonBaseConfig
from pendragon.registry import PendragonOperation
from pendragon.state import GeometryState
from pendragon.utils import ImageSampler
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry import MultiLineString


class PhotoWaveConfig(PendragonBaseConfig):
    lines: int = Field(default=80,
                       gt=0,
                       description="Number of horizontal wave lines.")
    amp: float = Field(default=2.0, description="Amplitude multiplier.")
    image_path: str | None = Field(default=None,
                                   description="File path to the source image.")


@dxf_registry.register("photo_wave", config_class=PhotoWaveConfig)
class PhotoWaveGen(PendragonOperation):

    def process(self,
                state: GeometryState,
                context: Optional[PipelineContext] = None) -> GeometryState:
        cfg = self.config or PhotoWaveConfig()
        ctx = context or PipelineContext()
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            return state

        if not cfg.image_path:
            return state

        lines_count = int(ctx.get("lines", cfg.lines))
        amp = ctx.get("amp", cfg.amp)

        logger.info(
            f"Generating {lines_count} photo waves from {cfg.image_path}...")

        minx, miny, maxx, maxy = effective_boundary.bounds
        width, height = maxx - minx, maxy - miny
        row_spacing = height / lines_count

        sampler = ImageSampler(cfg.image_path, effective_boundary.bounds)
        raw_lines: List[LineString] = []

        for r in range(lines_count):
            y_base = miny + (r * row_spacing)
            coords = []
            steps = int(width * 5)

            if steps <= 0:
                continue

            for s in range(steps):
                x = minx + (s * (width / steps))
                darkness = sampler.get_darkness(x, y_base)
                y_offset = math.sin(
                    x * 3.0) * (row_spacing * amp * 0.5) * darkness
                coords.append((x, y_base + y_offset))

            if len(coords) >= 2:
                raw_lines.append(LineString(coords))

        clipped_lines: List[LineString] = []
        for line in raw_lines:
            if line.intersects(effective_boundary):
                clipped = line.intersection(effective_boundary)
                if isinstance(clipped, LineString) and not clipped.is_empty:
                    clipped_lines.append(clipped)
                elif isinstance(clipped, MultiLineString):
                    for sub_line in clipped.geoms:
                        if not sub_line.is_empty:
                            clipped_lines.append(sub_line)

        logger.success(f"Generated {len(clipped_lines)} bounded wave paths.")
        return GeometryState(boundary=state.boundary,
                             lines=state.lines + clipped_lines,
                             operation_name="photo_wave")
