from typing import List, Optional

from loguru import logger
import numpy as np
from pydantic import Field
from scipy.spatial import Delaunay
from scipy.spatial import Voronoi
from shapely.geometry import LineString
from shapely.geometry import MultiLineString

from pendragon.core import BasePluginConfig
from pendragon.core import PipelineContext
from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation


class VoronoiDualConfig(BasePluginConfig):
    spacing: float = Field(default=2.0,
                           gt=0.0,
                           description="Target spacing between points.")
    num_points: int = Field(default=0,
                            ge=0,
                            description="Number of random seed points.")
    seed: int = Field(default=42, description="Random seed.")
    mode: str = Field(default='dual',
                      description="Mode: 'voronoi', 'delaunay', or 'dual'.")


@register_operation("voronoi_dual", config_class=VoronoiDualConfig)
class VoronoiDualGen(PipelineOperation):

    def process(self,
                state: PipelineState,
                context: Optional[PipelineContext] = None) -> PipelineState:
        cfg = self.config or VoronoiDualConfig()
        ctx = context or PipelineContext()
        effective_boundary = self.get_effective_boundary(state)

        minx, miny, maxx, maxy = effective_boundary.bounds
        width, height = maxx - minx, maxy - miny

        if width <= 0 or height <= 0:
            return state

        mode = ctx.variables.get("mode", cfg.mode)
        num_points = int(ctx.variables.get("num_points", cfg.num_points))
        spacing = ctx.variables.get("spacing", cfg.spacing)

        logger.info(f"Generating {mode} diagram...")

        if num_points <= 0:
            area = width * height
            safe_spacing = max(0.2, spacing)
            num_points = max(4, int(area / (safe_spacing**2)))

        margin_x, margin_y = width * 0.1, height * 0.1
        np.random.seed(cfg.seed)
        xs = np.random.uniform(minx - margin_x, maxx + margin_x, num_points)
        ys = np.random.uniform(miny - margin_y, maxy + margin_y, num_points)
        points = np.column_stack((xs, ys))

        if len(points) < 4:
            return state
        raw_lines: List[LineString] = []

        if mode in ["voronoi", "dual"]:
            vor = Voronoi(points)
            for ridge in vor.ridge_vertices:
                if -1 not in ridge:
                    raw_lines.append(
                        LineString(
                            [vor.vertices[ridge[0]], vor.vertices[ridge[1]]]))

        if mode in ["delaunay", "dual"]:
            tri = Delaunay(points)
            delaunay_edges = set()
            for simplex in tri.simplices:
                for i in range(3):
                    delaunay_edges.add(
                        tuple(sorted([simplex[i], simplex[(i + 1) % 3]])))
            for edge in delaunay_edges:
                raw_lines.append(LineString([points[edge[0]], points[edge[1]]]))

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

        logger.success(f"Generated {len(clipped_lines)} bounded {mode} paths.")
        return PipelineState(boundary=state.boundary,
                             lines=state.lines + clipped_lines,
                             operation_name="voronoi_dual")
