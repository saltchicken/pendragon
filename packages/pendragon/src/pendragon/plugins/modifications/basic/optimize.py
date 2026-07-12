from typing import List, Optional, Tuple
from loguru import logger
import numpy as np
from pydantic import BaseModel, Field
from scipy.spatial import cKDTree
from shapely.geometry import LineString

from nodeweaver.models import PipelineContext
from pendragon.state import GeometryState
from pendragon.registry import PendragonOperation, dxf_registry


class OptimizeConfig(BaseModel):
    start_x: float = Field(default=0.0, description="X coordinate to start optimizing from.")
    start_y: float = Field(default=0.0, description="Y coordinate to start optimizing from.")


def optimize_paths_nearest_neighbor(
    paths: List[List[Tuple[float, float]]],
    start_pt: Tuple[float, float] = (0.0, 0.0)
) -> List[List[Tuple[float, float]]]:
    if not paths:
        return []
    valid_paths = [p for p in paths if p]
    n_paths = len(valid_paths)
    if n_paths == 0:
        return []

    endpoints = np.zeros((n_paths * 2, 2))
    for i, path in enumerate(valid_paths):
        endpoints[i * 2], endpoints[i * 2 + 1] = path[0], path[-1]

    tree = cKDTree(endpoints)
    visited = np.zeros(n_paths, dtype=bool)
    optimized: List[List[Tuple[float, float]]] = []
    current_pt = np.array(start_pt)

    for _ in range(n_paths):
        k, best_idx = 16, -1
        while best_idx == -1:
            query_k = min(k, n_paths * 2)
            distances, indices = tree.query(current_pt, k=query_k)
            if query_k == 1:
                distances, indices = [distances], [indices]
            for dist, idx in zip(distances, indices):
                path_idx = idx // 2
                if not visited[path_idx]:
                    best_idx = idx
                    break
            if best_idx == -1:
                if query_k == n_paths * 2:
                    break
                k *= 4

        if best_idx == -1:
            break
        path_idx, is_end = best_idx // 2, (best_idx % 2 != 0)
        chosen_path = valid_paths[path_idx]
        if is_end:
            chosen_path = list(reversed(chosen_path))

        optimized.append(chosen_path)
        visited[path_idx] = True
        current_pt = np.array(chosen_path[-1])

    return optimized


@dxf_registry.register("optimize", config_class=OptimizeConfig)
class OptimizeMod(PendragonOperation):

    def process(self, state: GeometryState, context: Optional[PipelineContext] = None) -> GeometryState:
        cfg = self.config or OptimizeConfig()
        ctx = context or PipelineContext()
        current_lines = state.lines

        if not current_lines:
            return state

        raw_paths = [list(line.coords) for line in current_lines]
        
        # Handle dynamic variable extraction
        lc_x = ctx.get("local_center_x")
        lc_y = ctx.get("local_center_y")
        
        start_x = ctx.get("start_x", lc_x if lc_x is not None else cfg.start_x)
        start_y = ctx.get("start_y", lc_y if lc_y is not None else cfg.start_y)

        logger.info(f"Optimizing {len(raw_paths)} paths starting near ({start_x}, {start_y})...")

        optimized_paths = optimize_paths_nearest_neighbor(raw_paths, start_pt=(start_x, start_y))
        optimized_lines = [LineString(path) for path in optimized_paths]

        logger.success("Path optimization complete.")
        return GeometryState(boundary=state.boundary,
                             lines=optimized_lines,
                             operation_name="optimize")
