from typing import List

from loguru import logger
import numpy as np
from pydantic import Field
from scipy.spatial import cKDTree
from shapely.geometry import LineString
from shapely.geometry import Point

from pendragon.core import BasePluginConfig
from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation
from pendragon.utils import ImageSampler


class PhotoTSPConfig(BasePluginConfig):
    nodes: int = Field(
        default=2000, 
        gt=1,
        description="Number of stipple points to generate and connect."
    )
    image_path: str | None = Field(
        default=None,
        description="File path to the source image to sample."
    )
    seed: int = Field(
        default=42,
        description="Random seed for repeatable point placement."
    )


@register_operation("photo_tsp", config_class=PhotoTSPConfig)
class PhotoTSPGen(PipelineOperation):
    """Generates a Traveling Salesperson path stippled according to image darkness."""

    def process(self, state: PipelineState) -> PipelineState:
        cfg = self.config or PhotoTSPConfig()
        
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            logger.warning("No boundary available. Skipping photo_tsp.")
            return state

        if not cfg.image_path:
            logger.warning("No image_path provided. Skipping photo_tsp.")
            return state

        logger.info(f"Generating {cfg.nodes}-node TSP path from {cfg.image_path}...")

        minx, miny, maxx, maxy = effective_boundary.bounds
        sampler = ImageSampler(cfg.image_path, effective_boundary.bounds)
        
        np.random.seed(cfg.seed)
        points = []
        batch_size = cfg.nodes * 2
        max_batches = 100
        batches = 0

        # 1. Vectorized Rejection Sampling
        while len(points) < cfg.nodes and batches < max_batches:
            batches += 1
            xs = np.random.uniform(minx, maxx, batch_size)
            ys = np.random.uniform(miny, maxy, batch_size)
            rand_thresholds = np.random.random(batch_size)
            
            for i in range(batch_size):
                if len(points) >= cfg.nodes:
                    break
                
                x, y = xs[i], ys[i]
                
                # Check darkness first (fastest)
                if rand_thresholds[i] < sampler.get_darkness(x, y):
                    # Check complex geometry inclusion (slower)
                    if effective_boundary.contains(Point(x, y)):
                        points.append([x, y])

        if len(points) < 2:
            logger.warning("Could not generate enough points inside the boundary.")
            return state

        logger.info(f"Connecting {len(points)} nodes via KD-Tree nearest-neighbor...")

        # 2. O(N log N) Greedy TSP using cKDTree
        pts = np.array(points)
        tree = cKDTree(pts)
        visited = np.zeros(len(pts), dtype=bool)
        
        # Start at the first generated point
        current_idx = 0
        visited[0] = True
        route = [pts[0]]
        
        for _ in range(len(pts) - 1):
            k = 16  # Initial search radius
            best_idx = -1
            
            while best_idx == -1:
                query_k = min(k, len(pts))
                # Query nearest neighbors
                dists, idxs = tree.query(route[-1], k=query_k)
                
                # Scipy returns a scalar if k=1, but arrays if k>1
                if query_k == 1:
                    idxs = [idxs]
                    
                for idx in idxs:
                    if not visited[idx]:
                        best_idx = idx
                        break
                
                # Expand search if all local neighbors were already visited
                if best_idx == -1:
                    if query_k == len(pts):
                        break  # Fallback if logic fails
                    k *= 4
                    
            if best_idx != -1:
                visited[best_idx] = True
                route.append(pts[best_idx])

        # Convert the ordered route into a single continuous LineString
        final_path = LineString(route)
        
        logger.success("Photo TSP generation complete.")

        return PipelineState(
            boundary=state.boundary, 
            lines=state.lines + [final_path],
            operation_name="photo_tsp"
        )
