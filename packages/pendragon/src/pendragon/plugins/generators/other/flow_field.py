import math
import random
from typing import List, Optional

from loguru import logger
from nodeweaver.models import PipelineContext
from pendragon.registry import dxf_registry
from pendragon.registry import PendragonBaseConfig
from pendragon.registry import PendragonOperation
from pendragon.state import GeometryState
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry import MultiLineString


class FlowFieldConfig(PendragonBaseConfig):
    spacing: float = Field(default=3.0,
                           gt=0.0,
                           description="Distance between initial seed points.")
    step_length: float = Field(
        default=1.0,
        gt=0.0,
        description="Distance path travels in single step.")
    max_steps: int = Field(default=50,
                           gt=0,
                           description="Maximum number of steps.")
    scale: float = Field(default=0.1,
                         description="Scaling factor for vector field math.")
    seed: int = Field(default=42, description="Random seed.")


@dxf_registry.register("flow_field", config_class=FlowFieldConfig)
class FlowFieldGen(PendragonOperation):

    def process(self,
                state: GeometryState,
                context: Optional[PipelineContext] = None) -> GeometryState:
        cfg = self.config or FlowFieldConfig()
        ctx = context or PipelineContext()
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            return state

        spacing = ctx.get("spacing", cfg.spacing)
        scale = ctx.get("scale", cfg.scale)
        max_steps = int(ctx.get("max_steps", cfg.max_steps))

        logger.info(
            f"Generating flow field (spacing={spacing}, steps={max_steps}) using scale {scale}..."
        )

        random.seed(cfg.seed)
        minx, miny, maxx, maxy = effective_boundary.bounds
        width, height = maxx - minx, maxy - miny

        if width <= 0 or height <= 0:
            return state

        seeds = []
        x = minx
        while x <= maxx:
            y = miny
            while y <= maxy:
                jx = x + random.uniform(-spacing / 2, spacing / 2)
                jy = y + random.uniform(-spacing / 2, spacing / 2)
                seeds.append((jx, jy))
                y += spacing
            x += spacing

        cx = effective_boundary.centroid.x
        cy = effective_boundary.centroid.y

        def get_field_angle(px: float, py: float) -> float:
            nx, ny = (px - cx) * scale, (py - cy) * scale
            angle = math.sin(nx) + math.cos(ny) + math.sin(nx * ny * 0.5)
            return angle * math.pi

        raw_lines = []
        for sx, sy in seeds:
            path = [(sx, sy)]
            cx_pt, cy_pt = sx, sy

            for _ in range(max_steps):
                theta = get_field_angle(cx_pt, cy_pt)
                nx_pt = cx_pt + cfg.step_length * math.cos(theta)
                ny_pt = cy_pt + cfg.step_length * math.sin(theta)
                path.append((nx_pt, ny_pt))
                cx_pt, cy_pt = nx_pt, ny_pt

                if not (minx - 10 <= cx_pt <= maxx + 10 and
                        miny - 10 <= cy_pt <= maxy + 10):
                    break

            if len(path) > 1:
                raw_lines.append(LineString(path))

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

        logger.success(
            f"Generated {len(clipped_lines)} bounded flow field paths.")
        return GeometryState(boundary=state.boundary,
                             lines=state.lines + clipped_lines,
                             operation_name="flow_field")
