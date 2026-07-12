import math
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


class TriangleConfig(PendragonBaseConfig):
    cell_size: float = Field(
        default=5.0,
        gt=0.0,
        description="Side length of equilateral triangles.")


@dxf_registry.register("triangle", config_class=TriangleConfig)
class TriangleGen(PendragonOperation):

    def process(self,
                state: GeometryState,
                context: Optional[PipelineContext] = None) -> GeometryState:
        cfg = self.config or TriangleConfig()
        ctx = context or PipelineContext()
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            return state

        cell_size = ctx.get("cell_size", cfg.cell_size)
        logger.info(f"Generating triangle grid with cell size {cell_size}...")

        minx, miny, maxx, maxy = effective_boundary.bounds
        cx = effective_boundary.centroid.x
        cy = effective_boundary.centroid.y

        diag = math.hypot(maxx - minx, maxy - miny)
        r = diag / 2.0 + cell_size
        spacing = cell_size * math.sqrt(3.0) / 2.0
        if spacing <= 0:
            return state

        raw_lines = []
        for angle_deg in [0, 60, 120]:
            angle_rad = math.radians(angle_deg)
            cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)
            nx, ny = -sin_a, cos_a

            num_lines = int(math.ceil(2 * r / spacing))
            for i in range(-num_lines // 2, num_lines // 2 + 1):
                offset = i * spacing
                px, py = cx + nx * offset, cy + ny * offset
                raw_lines.append(
                    LineString([(px - cos_a * r, py - sin_a * r),
                                (px + cos_a * r, py + sin_a * r)]))

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
            f"Generated {len(clipped_lines)} bounded triangle grid lines.")
        return PipelineState(boundary=state.boundary,
                             lines=state.lines + clipped_lines,
                             operation_name="triangle")
