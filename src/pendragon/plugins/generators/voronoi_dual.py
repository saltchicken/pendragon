import numpy as np
from loguru import logger
from pydantic import Field
from scipy.spatial import Delaunay, Voronoi
from shapely.geometry import LineString, MultiLineString
from typing import List

from pendragon.core import PipelineOperation, PipelineState, register_operation
from pendragon.core import BasePluginConfig


class VoronoiDualConfig(BasePluginConfig):
    spacing: float = Field(
        default=2.0, 
        gt=0.0, 
        description="Target spacing between points if num_points is 0."
    )
    num_points: int = Field(
        default=0, 
        ge=0, 
        description="Number of random seed points to generate."
    )
    seed: int = Field(
        default=42, 
        description="Random seed for repeatable generation."
    )
    mode: str = Field(
        default='dual', 
        description="Mode of generation: 'voronoi', 'delaunay', or 'dual'."
    )


@register_operation("voronoi_dual", config_class=VoronoiDualConfig)
class VoronoiDualGen(PipelineOperation):
    """Generates Voronoi cells, Delaunay triangulations, or both overlaid."""

    def process(self, state: PipelineState) -> PipelineState:
        cfg = self.config or VoronoiDualConfig()
        
        # Pull original lines to preserve them (matching the original plugin's behavior)
        current_lines = state.lines 
        
        # Get the boundary, buffered by the overscan config if applicable
        effective_boundary = self.get_effective_boundary(state)
        minx, miny, maxx, maxy = effective_boundary.bounds
        width = maxx - minx
        height = maxy - miny

        if width <= 0 or height <= 0:
            logger.warning("Effective boundary has no area. Skipping voronoi_dual generation.")
            return state

        logger.info(f"Generating {cfg.mode} diagram...")

        # 1. Determine point counts
        num_points = cfg.num_points
        if num_points <= 0:
            area = width * height
            safe_spacing = max(0.2, cfg.spacing)
            num_points = max(4, int(area / (safe_spacing**2)))

        # Expand generation bounds slightly so that Voronoi ridges don't
        # prematurely terminate before hitting the true clipping boundary.
        margin_x = width * 0.1
        margin_y = height * 0.1

        # 2. Distribute seed points
        np.random.seed(cfg.seed)
        xs = np.random.uniform(minx - margin_x, maxx + margin_x, num_points)
        ys = np.random.uniform(miny - margin_y, maxy + margin_y, num_points)
        points = np.column_stack((xs, ys))

        # Both diagrams require a minimum of 4 distinct points
        if len(points) < 4:
            logger.warning("Not enough points generated to form a valid diagram.")
            return state

        raw_lines: List[LineString] = []

        # 3. Generate Voronoi Edges
        if cfg.mode in ["voronoi", "dual"]:
            vor = Voronoi(points)
            for ridge in vor.ridge_vertices:
                if -1 not in ridge:  # -1 represents a ridge stretching to infinity
                    p1 = vor.vertices[ridge[0]]
                    p2 = vor.vertices[ridge[1]]
                    raw_lines.append(LineString([p1, p2]))

        # 4. Generate Delaunay Triangulation Edges
        if cfg.mode in ["delaunay", "dual"]:
            tri = Delaunay(points)
            delaunay_edges = set()

            # Extract unique edges from the simplices (triangles)
            for simplex in tri.simplices:
                for i in range(3):
                    idx1 = simplex[i]
                    idx2 = simplex[(i + 1) % 3]
                    # Sort the vertex indices so (A, B) and (B, A) hash to the same tuple
                    delaunay_edges.add(tuple(sorted([idx1, idx2])))

            for edge in delaunay_edges:
                p1 = points[edge[0]]
                p2 = points[edge[1]]
                raw_lines.append(LineString([p1, p2]))

        # 5. Clip generated geometry cleanly against the effective boundary
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

        logger.success(f"Generated {len(clipped_lines)} bounded {cfg.mode} paths.")

        # Pass the original boundary forward alongside the merged lines
        return PipelineState(
            boundary=state.boundary,
            lines=current_lines + clipped_lines,
            operation_name="voronoi_dual"
        )
