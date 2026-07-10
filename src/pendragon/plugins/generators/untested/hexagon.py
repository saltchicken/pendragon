import math
from typing import List

from loguru import logger
from pydantic import Field
from shapely.geometry import LineString, MultiLineString

from pendragon.core import (
    BasePluginConfig,
    PipelineOperation,
    PipelineState,
    register_operation,
)


class HexagonConfig(BasePluginConfig):
    radius: float = Field(
        default=3.0, 
        gt=0.0,
        description="The outer radius of a single hexagon cell."
    )


@register_operation("hexagon", config_class=HexagonConfig)
class HexagonGen(PipelineOperation):
    """Generates a regular hexagonal (honeycomb) tessellation using a heuristic-driven graph traversal to minimize pen lifts."""

    def process(self, state: PipelineState) -> PipelineState:
        cfg = self.config or HexagonConfig()
        
        # 1. Acquire the boundary geometry (factoring in overscan if configured)
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            logger.warning("No boundary available. Skipping hexagon.")
            return state

        minx, miny, maxx, maxy = effective_boundary.bounds

        if cfg.radius <= 0:
            return state

        logger.info(f"Generating Hexagon fill with radius {cfg.radius}...")

        w = math.sqrt(3.0) * cfg.radius
        h = 2.0 * cfg.radius
        x_spacing = w
        y_spacing = 1.5 * cfg.radius

        cols = int(math.ceil((maxx - minx) / x_spacing)) + 2
        rows = int(math.ceil((maxy - miny) / y_spacing)) + 2

        start_x = minx - w
        start_y = miny - h

        # 2. Generate unique edges and map quantized coordinates to exact floats
        unique_edges = set()
        pts_map = {}

        def quantize(pt):
            # Quantize to 0.001mm to avoid floating-point mismatch at junctions
            return (int(round(pt[0] * 1000)), int(round(pt[1] * 1000)))

        for row in range(rows):
            for col in range(cols):
                cx = start_x + col * x_spacing
                if row % 2 != 0:
                    cx += x_spacing / 2.0
                cy = start_y + row * y_spacing

                vertices = []
                for i in range(6):
                    angle_rad = math.radians(60 * i - 30)
                    vx = cx + cfg.radius * math.cos(angle_rad)
                    vy = cy + cfg.radius * math.sin(angle_rad)
                    vertices.append((vx, vy))

                for i in range(6):
                    p1, p2 = vertices[i], vertices[(i + 1) % 6]
                    k1, k2 = quantize(p1), quantize(p2)

                    pts_map[k1] = p1
                    pts_map[k2] = p2

                    edge = (k1, k2) if k1 < k2 else (k2, k1)
                    unique_edges.add(edge)

        # 3. Build adjacency list for the graph
        adj = {k: set() for k in pts_map.keys()}
        for k1, k2 in unique_edges:
            adj[k1].add(k2)
            adj[k2].add(k1)

        raw_lines = []

        # 4. Smart Eulerian path routing using a Look-Ahead Heuristic
        while unique_edges:
            start_node = None

            # Start prioritization:
            # 1. Degree 1 (Clear true dead ends first)
            # 2. Degree 3 (Standard odd nodes, clearing them makes the graph even)
            # 3. Degree 2/4 (Even nodes last)
            for target_degree in [1, 3, 2, 4]:
                candidates = [
                    n for n, neighbors in adj.items()
                    if len(neighbors) == target_degree
                ]
                if candidates:
                    start_node = candidates[0]
                    break

            if start_node is None:
                break

            path = [start_node]
            curr = start_node

            # Walk the graph
            while adj[curr]:
                # THE HEURISTIC: Look at all connected nodes.
                # Sort them by how many connections THEY have remaining.
                # Pick the one with the HIGHEST remaining connections to avoid walking into a trap.
                neighbors = list(adj[curr])
                neighbors.sort(key=lambda n: len(adj[n]), reverse=True)

                nxt = neighbors[0]

                # Consume the edge
                adj[curr].remove(nxt)
                adj[nxt].remove(curr)

                # Remove from tracking set
                e = (curr, nxt) if curr < nxt else (nxt, curr)
                unique_edges.discard(e)

                path.append(nxt)
                curr = nxt

            # Convert quantized path back to precise float coordinates
            if len(path) > 1:
                float_path = [pts_map[node] for node in path]
                raw_lines.append(LineString(float_path))

        # 5. Clip the generated curves against the complex boundary
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

        logger.success(f"Generated Hexagon fill. Retained {len(clipped_lines)} continuous bounded paths.")

        # 6. Return a new immutable state
        return PipelineState(
            boundary=state.boundary, 
            lines=state.lines + clipped_lines,
            operation_name="hexagon"
        )
