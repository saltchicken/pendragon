import math
from typing import List, Optional

from loguru import logger
from nodeweaver.models import PipelineContext
import numpy as np
from pendragon.registry import dxf_registry
from pendragon.registry import PendragonBaseConfig
from pendragon.registry import PendragonOperation
from pendragon.state import GeometryState
from pendragon.utils import extract_target_polygons
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry import MultiLineString
from shapely.geometry import Point
from shapely.ops import linemerge


class LichtenbergConfig(PendragonBaseConfig):
    center_x: float | None = Field(default=None)
    center_y: float | None = Field(default=None)
    group_boundaries: bool = Field(default=False)
    nodes: int = Field(
        default=1500,
        gt=0,
        description="Target number of branches/nodes to generate per region.")
    spacing: float = Field(default=2.0,
                           gt=0.0,
                           description="Length of each branching segment.")
    seed: int = Field(
        default=42,
        description="Random seed for reproducible fractal generation.")
    max_iterations: int = Field(
        default=1000,
        description="Safety limit to prevent infinite generation loops.")


@dxf_registry.register("lichtenberg", config_class=LichtenbergConfig)
class LichtenbergGen(PendragonOperation):
    """
    Generates a Lichtenberg-style (branching fractal) fill using an RRT
    (Rapidly-exploring Random Tree) algorithm confined to the boundary.
    """

    def process(self,
                state: GeometryState,
                context: Optional[PipelineContext] = None) -> GeometryState:
        cfg = self.config or LichtenbergConfig()
        ctx = context or PipelineContext()
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            logger.warning("No boundary available. Skipping lichtenberg.")
            return state

        polygons = extract_target_polygons(effective_boundary,
                                           cfg.group_boundaries)
        logger.info(f"Generating Lichtenberg fractals ({cfg.nodes} nodes max) "
                    f"across {len(polygons)} boundary region(s)...")

        np.random.seed(cfg.seed)
        all_fractal_lines: List[LineString] = []

        for poly in polygons:
            minx, miny, maxx, maxy = poly.bounds

            # Fallback hierarchy: Context -> YAML Config -> Geometry Centroid
            cx = ctx.get("center_x") if ctx.get("center_x") is not None else (
                cfg.center_x if cfg.center_x is not None else poly.centroid.x)
            cy = ctx.get("center_y") if ctx.get("center_y") is not None else (
                cfg.center_y if cfg.center_y is not None else poly.centroid.y)
            root_pt = Point(cx, cy)

            if not poly.contains(root_pt):
                for _ in range(100):
                    root_pt = Point(np.random.uniform(minx, maxx),
                                    np.random.uniform(miny, maxy))
                    if poly.contains(root_pt):
                        break

            nodes_arr = np.zeros((cfg.nodes, 2))
            nodes_arr[0] = [root_pt.x, root_pt.y]
            current_size = 1
            raw_segments = []

            max_attempts = cfg.nodes * 10
            rand_xs = np.random.uniform(minx, maxx, max_attempts)
            rand_ys = np.random.uniform(miny, maxy, max_attempts)

            for i in range(max_attempts):
                if current_size >= cfg.nodes:
                    break

                rx, ry = rand_xs[i], rand_ys[i]

                valid_nodes = nodes_arr[:current_size]
                diff = valid_nodes - np.array([rx, ry])
                sq_dists = diff[:, 0]**2 + diff[:, 1]**2
                nearest_idx = np.argmin(sq_dists)

                nx, ny = valid_nodes[nearest_idx]
                dist = math.sqrt(sq_dists[nearest_idx])

                if dist == 0:
                    continue

                step = min(cfg.spacing, dist)
                new_x = nx + (rx - nx) * (step / dist)
                new_y = ny + (ry - ny) * (step / dist)

                segment = LineString([(nx, ny), (new_x, new_y)])

                if poly.contains(segment):
                    nodes_arr[current_size] = [new_x, new_y]
                    current_size += 1
                    raw_segments.append(segment)

            if raw_segments:
                merged_geometry = linemerge(raw_segments)

                if isinstance(merged_geometry, LineString):
                    all_fractal_lines.append(merged_geometry)
                elif isinstance(merged_geometry, MultiLineString):
                    for line in merged_geometry.geoms:
                        all_fractal_lines.append(line)

        logger.success(
            f"Generated {len(all_fractal_lines)} continuous fractal paths.")

        return GeometryState(boundary=state.boundary,
                             lines=state.lines + all_fractal_lines,
                             operation_name="lichtenberg")
