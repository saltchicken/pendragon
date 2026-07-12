from typing import List, Optional

from loguru import logger
from nodeweaver.models import PipelineContext
import numpy as np
from pendragon.registry import dxf_registry
from pendragon.registry import PendragonBaseConfig
from pendragon.registry import PendragonOperation
from pendragon.state import GeometryState
from pendragon.utils import ImageSampler
from pydantic import Field
from scipy.spatial import cKDTree
from shapely.geometry import LineString
from shapely.geometry import Point


class PhotoTSPConfig(PendragonBaseConfig):
    nodes: int = Field(default=2000,
                       gt=1,
                       description="Number of points to connect.")
    image_path: str | None = Field(default=None,
                                   description="File path to the source image.")
    seed: int = Field(default=42, description="Random seed.")


@dxf_registry.register("photo_tsp", config_class=PhotoTSPConfig)
class PhotoTSPGen(PendragonOperation):

    def process(self,
                state: GeometryState,
                context: Optional[PipelineContext] = None) -> GeometryState:
        cfg = self.config or PhotoTSPConfig()
        ctx = context or PipelineContext()
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            return state
        if not cfg.image_path:
            return state

        nodes = int(ctx.get("nodes", cfg.nodes))
        logger.info(
            f"Generating {nodes}-node TSP path from {cfg.image_path}...")

        minx, miny, maxx, maxy = effective_boundary.bounds
        sampler = ImageSampler(cfg.image_path, effective_boundary.bounds)
        np.random.seed(cfg.seed)

        points, batch_size, max_batches, batches = [], nodes * 2, 100, 0

        while len(points) < nodes and batches < max_batches:
            batches += 1
            xs, ys = np.random.uniform(minx, maxx,
                                       batch_size), np.random.uniform(
                                           miny, maxy, batch_size)
            rand_thresholds = np.random.random(batch_size)

            for i in range(batch_size):
                if len(points) >= nodes:
                    break
                x, y = xs[i], ys[i]
                if rand_thresholds[i] < sampler.get_darkness(x, y):
                    if effective_boundary.contains(Point(x, y)):
                        points.append([x, y])

        if len(points) < 2:
            logger.warning(
                "Could not generate enough points inside the boundary.")
            return state

        logger.info(
            f"Connecting {len(points)} nodes via KD-Tree nearest-neighbor...")

        pts = np.array(points)
        tree = cKDTree(pts)
        visited = np.zeros(len(pts), dtype=bool)
        visited[0] = True
        route = [pts[0]]

        for _ in range(len(pts) - 1):
            k, best_idx = 16, -1
            while best_idx == -1:
                query_k = min(k, len(pts))
                _, idxs = tree.query(route[-1], k=query_k)
                if query_k == 1:
                    idxs = [idxs]
                for idx in idxs:
                    if not visited[idx]:
                        best_idx = idx
                        break
                if best_idx == -1:
                    if query_k == len(pts):
                        break
                    k *= 4
            if best_idx != -1:
                visited[best_idx] = True
                route.append(pts[best_idx])

        final_path = LineString(route)
        logger.success("Photo TSP generation complete.")
        return GeometryState(boundary=state.boundary,
                             lines=state.lines + [final_path],
                             operation_name="photo_tsp")
