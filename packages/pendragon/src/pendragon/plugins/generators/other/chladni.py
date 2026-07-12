import math
from typing import List, Optional

from loguru import logger
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry import MultiLineString
from shapely.ops import linemerge

from nodeweaver.models import PipelineContext
from pendragon.state import GeometryState
from pendragon.registry import PendragonBaseConfig, PendragonOperation, dxf_registry
from pendragon.utils import ImageSampler


class ChladniConfig(PendragonBaseConfig):
    n: float = Field(default=3.0, description="Horizontal resonant mode.")
    m: float = Field(default=5.0, description="Vertical resonant mode.")
    sign: float = Field(default=-1.0,
                        description="Sign of the wave interference.")
    res: float = Field(default=0.5,
                       gt=0.0,
                       description="Grid sampling resolution.")
    simplify: float = Field(default=0.0,
                            ge=0.0,
                            description="Tolerance for path simplification.")
    image_path: str | None = Field(default=None,
                                   description="Optional image modulator.")


@dxf_registry.register("chladni", config_class=ChladniConfig)
class ChladniGen(PendragonOperation):

    def process(self,
                state: GeometryState,
                context: Optional[PipelineContext] = None) -> GeometryState:
        cfg = self.config or ChladniConfig()
        ctx = context or PipelineContext()
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            return state

        minx, miny, maxx, maxy = effective_boundary.bounds
        width, height = maxx - minx, maxy - miny
        if width <= 0 or height <= 0:
            return state

        n_mode = ctx.get("n", cfg.n)
        m_mode = ctx.get("m", cfg.m)
        res = ctx.get("res", cfg.res)

        logger.info(
            f"Generating Chladni pattern (n={n_mode}, m={m_mode}) at resolution {res}..."
        )

        sampler = None
        if cfg.image_path:
            sampler = ImageSampler(cfg.image_path, effective_boundary.bounds)

        grid_res = max(res, 0.1)
        cols = int(math.ceil(width / grid_res)) + 1
        rows = int(math.ceil(height / grid_res)) + 1

        x_grid = [minx + i * grid_res for i in range(cols)]
        y_grid = [miny + j * grid_res for j in range(rows)]

        def get_val(x: float, y: float) -> float:
            u = (x - minx) / width
            v = (y - miny) / height
            val = (math.cos(n_mode * math.pi * u) *
                   math.cos(m_mode * math.pi * v) +
                   cfg.sign * math.cos(m_mode * math.pi * u) *
                   math.cos(n_mode * math.pi * v))
            if sampler:
                val += (sampler.get_darkness(x, y) - 0.5) * 2.0
            return val

        vals = [[get_val(x, y) for y in y_grid] for x in x_grid]

        def interp(v1: float, v2: float, p1: tuple, p2: tuple) -> tuple:
            if v1 == v2:
                return p1
            t = (0.0 - v1) / (v2 - v1)
            return (p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1]))

        segments = []
        for i in range(cols - 1):
            for j in range(rows - 1):
                x0, y0 = x_grid[i], y_grid[j]
                x1, y1 = x_grid[i + 1], y_grid[j + 1]
                v00, v10, v11, v01 = vals[i][j], vals[i + 1][j], vals[i + 1][
                    j + 1], vals[i][j + 1]

                pts = []
                if (v00 > 0) != (v10 > 0):
                    pts.append(interp(v00, v10, (x0, y0), (x1, y0)))
                if (v10 > 0) != (v11 > 0):
                    pts.append(interp(v10, v11, (x1, y0), (x1, y1)))
                if (v11 > 0) != (v01 > 0):
                    pts.append(interp(v11, v01, (x1, y1), (x0, y1)))
                if (v01 > 0) != (v00 > 0):
                    pts.append(interp(v01, v00, (x0, y1), (x0, y0)))

                if len(pts) == 2:
                    segments.append(LineString(pts))
                elif len(pts) == 4:
                    center_val = (v00 + v10 + v11 + v01) / 4.0
                    if (center_val > 0) == (v00 > 0):
                        segments.extend([
                            LineString([pts[0], pts[3]]),
                            LineString([pts[1], pts[2]])
                        ])
                    else:
                        segments.extend([
                            LineString([pts[0], pts[1]]),
                            LineString([pts[2], pts[3]])
                        ])

        if not segments:
            return state

        merged = linemerge(segments)
        if cfg.simplify > 0:
            merged = merged.simplify(cfg.simplify, preserve_topology=False)

        raw_lines = [merged] if isinstance(merged, LineString) else list(
            merged.geoms) if isinstance(merged, MultiLineString) else segments

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
            f"Generated Chladni fill. Retained {len(clipped_lines)} continuous bounded paths."
        )
        return GeometryState(boundary=state.boundary,
                             lines=state.lines + clipped_lines,
                             operation_name="chladni")
