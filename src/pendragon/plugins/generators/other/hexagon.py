import math
from typing import List, Optional

from loguru import logger
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry import MultiLineString

from pendragon.core import BasePluginConfig
from pendragon.core import PipelineContext
from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation


class HexagonConfig(BasePluginConfig):
    radius: float = Field(default=3.0,
                          gt=0.0,
                          description="Outer radius of a single hexagon cell.")


@register_operation("hexagon", config_class=HexagonConfig)
class HexagonGen(PipelineOperation):

    def process(self,
                state: PipelineState,
                context: Optional[PipelineContext] = None) -> PipelineState:
        cfg = self.config or HexagonConfig()
        ctx = context or PipelineContext()
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            return state

        radius = ctx.variables.get("radius", cfg.radius)
        if radius <= 0:
            return state

        minx, miny, maxx, maxy = effective_boundary.bounds
        logger.info(f"Generating Hexagon fill with radius {radius}...")

        w = math.sqrt(3.0) * radius
        h = 2.0 * radius
        cols = int(math.ceil((maxx - minx) / w)) + 2
        rows = int(math.ceil((maxy - miny) / (1.5 * radius))) + 2

        start_x, start_y = minx - w, miny - h
        unique_edges, pts_map = set(), {}

        def quantize(pt):
            return (int(round(pt[0] * 1000)), int(round(pt[1] * 1000)))

        for row in range(rows):
            for col in range(cols):
                cx = start_x + col * w
                if row % 2 != 0:
                    cx += w / 2.0
                cy = start_y + row * (1.5 * radius)

                vertices = []
                for i in range(6):
                    angle_rad = math.radians(60 * i - 30)
                    vertices.append((cx + radius * math.cos(angle_rad),
                                     cy + radius * math.sin(angle_rad)))

                for i in range(6):
                    p1, p2 = vertices[i], vertices[(i + 1) % 6]
                    k1, k2 = quantize(p1), quantize(p2)
                    pts_map[k1], pts_map[k2] = p1, p2
                    unique_edges.add((k1, k2) if k1 < k2 else (k2, k1))

        adj = {k: set() for k in pts_map.keys()}
        for k1, k2 in unique_edges:
            adj[k1].add(k2)
            adj[k2].add(k1)

        raw_lines = []
        while unique_edges:
            start_node = None
            for target_degree in [1, 3, 2, 4]:
                candidates = [
                    n for n, neighbors in adj.items()
                    if len(neighbors) == target_degree
                ]
                if candidates:
                    start_node = candidates[0]
                    break
            if start_node is None:
                candidates = [
                    n for n, neighbors in adj.items() if len(neighbors) > 0
                ]
                if candidates:
                    start_node = candidates[0]
            if start_node is None:
                break

            path, curr = [start_node], start_node
            while adj[curr]:
                neighbors = list(adj[curr])
                neighbors.sort(key=lambda n: len(adj[n]), reverse=False)
                nxt = neighbors[0]

                adj[curr].remove(nxt)
                adj[nxt].remove(curr)
                unique_edges.discard((curr, nxt) if curr < nxt else (nxt, curr))

                path.append(nxt)
                curr = nxt

            if len(path) > 1:
                raw_lines.append(LineString([pts_map[node] for node in path]))

        clipped_lines: List[LineString] = []

        def extract_valid_lines(geom):
            extracted = []
            if geom.is_empty:
                return extracted
            if geom.geom_type == 'LineString':
                extracted.append(geom)
            elif geom.geom_type == 'MultiLineString':
                extracted.extend(list(geom.geoms))
            elif geom.geom_type == 'GeometryCollection':
                for g in geom.geoms:
                    if g.geom_type == 'LineString':
                        extracted.append(g)
                    elif g.geom_type == 'MultiLineString':
                        extracted.extend(list(g.geoms))
            return extracted

        for line in raw_lines:
            if line.intersects(effective_boundary):
                clipped_lines.extend(
                    extract_valid_lines(line.intersection(effective_boundary)))

        logger.success(
            f"Generated Hexagon fill. Retained {len(clipped_lines)} continuous paths."
        )
        return PipelineState(boundary=state.boundary,
                             lines=state.lines + clipped_lines,
                             operation_name="hexagon")
