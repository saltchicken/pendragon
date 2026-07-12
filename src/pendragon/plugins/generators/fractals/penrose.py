import math
from typing import List, Optional, Tuple

from loguru import logger
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry import MultiLineString

from pendragon.engine import CenteredPluginConfig
from pendragon.engine import PipelineContext
from pendragon.engine import PipelineOperation
from pendragon.engine import PipelineState
from pendragon.engine import register_operation
from pendragon.utils import extract_target_polygons

PHI = (1.0 + math.sqrt(5.0)) / 2.0


class PenroseConfig(CenteredPluginConfig):
    depth: int = Field(
        default=5,
        ge=1,
        description=
        "Number of recursive deflation iterations. High values exponentially increase detail."
    )


@register_operation("penrose", config_class=PenroseConfig)
class PenroseGen(PipelineOperation):
    """
    Generates an aperiodic Penrose P3 (rhombus-like) tiling pattern
    using recursive Robinson triangle deflation.
    """

    def process(self,
                state: PipelineState,
                context: Optional[PipelineContext] = None) -> PipelineState:
        cfg = self.config or PenroseConfig()
        ctx = context or PipelineContext()
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            logger.warning("No boundary available. Skipping penrose.")
            return state

        polygons = extract_target_polygons(effective_boundary,
                                           cfg.group_boundaries)
        clipped_lines: List[LineString] = []

        logger.info(f"Generating Penrose tiling (depth {cfg.depth}) "
                    f"across {len(polygons)} boundary region(s)...")

        for poly in polygons:
            # Fallback hierarchy: Context -> YAML Config -> Geometry Centroid
            cx = ctx.local_center_x if ctx.local_center_x is not None else (
                cfg.center_x if cfg.center_x is not None else poly.centroid.x)
            cy = ctx.local_center_y if ctx.local_center_y is not None else (
                cfg.center_y if cfg.center_y is not None else poly.centroid.y)

            minx, miny, maxx, maxy = poly.bounds

            dx = max(abs(maxx - cx), abs(cx - minx))
            dy = max(abs(maxy - cy), abs(cy - miny))
            radius = math.hypot(dx, dy) * 1.5

            triangles = []
            for i in range(10):
                a1 = i * math.pi / 5.0
                a2 = (i + 1) * math.pi / 5.0

                p1 = (cx, cy)
                p2 = (cx + radius * math.cos(a1), cy + radius * math.sin(a1))
                p3 = (cx + radius * math.cos(a2), cy + radius * math.sin(a2))

                if i % 2 == 0:
                    triangles.append((0, p1, p2, p3))
                else:
                    triangles.append((0, p1, p3, p2))

            for _ in range(cfg.depth):
                next_triangles = []
                for t_type, p1, p2, p3 in triangles:
                    if t_type == 0:
                        ax = p1[0] + (p2[0] - p1[0]) / PHI
                        ay = p1[1] + (p2[1] - p1[1]) / PHI
                        p_new = (ax, ay)

                        next_triangles.append((0, p3, p_new, p2))
                        next_triangles.append((1, p_new, p3, p1))
                    else:
                        bx = p2[0] + (p1[0] - p2[0]) / PHI
                        by = p2[1] + (p1[1] - p2[1]) / PHI
                        p_new1 = (bx, by)

                        cx_pt = p2[0] + (p3[0] - p2[0]) / PHI
                        cy_pt = p2[1] + (p3[1] - p2[1]) / PHI
                        p_new2 = (cx_pt, cy_pt)

                        next_triangles.append((1, p_new2, p_new1, p2))
                        next_triangles.append((0, p_new1, p_new2, p3))
                        next_triangles.append((1, p_new1, p3, p1))

                triangles = next_triangles

            seen_edges = set()

            def get_edge_key(
                pt1: Tuple[float, float], pt2: Tuple[float, float]
            ) -> Tuple[Tuple[int, int], Tuple[int, int]]:
                k1 = (int(round(pt1[0] * 100)), int(round(pt1[1] * 100)))
                k2 = (int(round(pt2[0] * 100)), int(round(pt2[1] * 100)))
                return (k1, k2) if k1 < k2 else (k2, k1)

            for _, p1, p2, p3 in triangles:
                for start, end in [(p1, p2), (p2, p3), (p3, p1)]:
                    key = get_edge_key(start, end)
                    if key not in seen_edges:
                        seen_edges.add(key)

                        line = LineString([start, end])
                        if line.intersects(poly):
                            clipped = line.intersection(poly)

                            if isinstance(clipped,
                                          LineString) and not clipped.is_empty:
                                clipped_lines.append(clipped)
                            elif isinstance(clipped, MultiLineString):
                                for sub_line in clipped.geoms:
                                    if not sub_line.is_empty:
                                        clipped_lines.append(sub_line)

        logger.success(
            f"Generated Penrose tiling. Retained {len(clipped_lines)} continuous paths."
        )

        return PipelineState(boundary=state.boundary,
                             lines=state.lines + clipped_lines,
                             operation_name="penrose")
