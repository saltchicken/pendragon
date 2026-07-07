from typing import List, Tuple

import numpy as np
from pydantic import BaseModel, Field
from scipy.spatial import cKDTree
from shapely.geometry import LineString
from loguru import logger

# Pendragon core imports
from pendragon.core import PipelineState
from pendragon.core import PipelineOperation, register_operation


class OptimizeConfig(BaseModel):
    start_x: float = Field(default=0.0, description="X coordinate to start optimizing from.")
    start_y: float = Field(default=0.0, description="Y coordinate to start optimizing from.")


def optimize_paths_nearest_neighbor(
    paths: List[List[Tuple[float, float]]],
    start_pt: Tuple[float, float] = (0.0, 0.0)
) -> List[List[Tuple[float, float]]]:
    """
    Sorts paths using a greedy nearest-neighbor approach to minimize travel time.
    Utilizes a KD-Tree for O(N log N) spatial querying of endpoints.
    """
    if not paths:
        return []

    # Filter out empty paths to ensure coordinate extraction doesn't crash
    valid_paths = [p for p in paths if p]
    n_paths = len(valid_paths)
    if n_paths == 0:
        return []

    # Flatten start and end points into a single array for the KDTree
    # Index format: even = start point, odd = end point
    endpoints = np.zeros((n_paths * 2, 2))
    for i, path in enumerate(valid_paths):
        endpoints[i * 2] = path[0]  # Start point
        endpoints[i * 2 + 1] = path[-1]  # End point

    # Build the spatial index
    tree = cKDTree(endpoints)
    visited = np.zeros(n_paths, dtype=bool)
    optimized: List[List[Tuple[float, float]]] = []
    current_pt = np.array(start_pt)

    for _ in range(n_paths):
        k = 16  # Initial search batch size
        best_idx = -1

        while best_idx == -1:
            query_k = min(k, n_paths * 2)
            distances, indices = tree.query(current_pt, k=query_k)

            # Scipy returns scalars if k=1, but arrays if k>1
            if query_k == 1:
                distances, indices = [distances], [indices]

            for dist, idx in zip(distances, indices):
                path_idx = idx // 2
                if not visited[path_idx]:
                    best_idx = idx
                    break

            if best_idx == -1:
                # If all 'k' nearest neighbors were already visited, expand search ring
                if query_k == n_paths * 2:
                    break  # Should only hit this if logic fails or floats corrupt
                k *= 4

        if best_idx == -1:
            break

        # Decode the point index back to the path and direction
        path_idx = best_idx // 2
        is_end = (best_idx % 2 != 0)

        chosen_path = valid_paths[path_idx]
        if is_end:
            chosen_path = list(reversed(chosen_path))

        optimized.append(chosen_path)
        visited[path_idx] = True

        # Update current position to the exit point of the chosen path
        current_pt = np.array(chosen_path[-1])

    return optimized


@register_operation("optimize", config_class=OptimizeConfig)
class OptimizeMod(PipelineOperation):
    
    def process(self, state: PipelineState) -> PipelineState:
        # Fallback to default if no config provided in YAML
        active_config = self.config or OptimizeConfig()
        current_lines = state.lines
        
        if not current_lines:
            logger.warning("No lines provided to the optimize operation. Skipping.")
            return state

        # Unpack Shapely LineStrings into raw coordinate lists
        raw_paths = [list(line.coords) for line in current_lines]

        start_x = active_config.start_x
        start_y = active_config.start_y

        logger.info(f"Optimizing {len(raw_paths)} paths starting near ({start_x}, {start_y})...")

        # Run the KD-Tree nearest neighbor algorithm
        optimized_paths = optimize_paths_nearest_neighbor(
            raw_paths,
            start_pt=(start_x, start_y)
        )

        # Repack raw coordinates back into Shapely LineStrings
        optimized_lines = [LineString(path) for path in optimized_paths]
        
        logger.success("Path optimization complete.")

        # Return a fresh immutable state for the next pipeline step
        return PipelineState(
            boundary=state.boundary,
            lines=optimized_lines,
            operation_name="optimize"
        )
