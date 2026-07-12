from typing import List, Optional

from loguru import logger
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

from nodeweaver.models import PipelineContext
from pendragon.state import GeometryState
from pendragon.registry import PendragonBaseConfig, PendragonOperation, dxf_registry


class OffsetFillConfig(PendragonBaseConfig):
    spacing: float = Field(default=2.0,
                           gt=0.0,
                           description="Distance between offset rings.")
    ring_simplify: float = Field(default=0.2,
                                 ge=0.0,
                                 description="Simplification tolerance.")


@dxf_registry.register("offset_fill", config_class=OffsetFillConfig)
class OffsetFillGen(PendragonOperation):

    def process(self,
                state: GeometryState,
                context: Optional[PipelineContext] = None) -> GeometryState:
        cfg = self.config or OffsetFillConfig()
        ctx = context or PipelineContext()
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            return state

        spacing = ctx.get("spacing", cfg.spacing)
        logger.info(
            f"Generating concentric offset fill with spacing {spacing}...")

        new_lines: List[LineString] = []
        current_geom = effective_boundary.buffer(-spacing).simplify(
            cfg.ring_simplify, preserve_topology=False)

        while not current_geom.is_empty and current_geom.area > 0:
            polygons = [current_geom
                        ] if current_geom.geom_type == 'Polygon' else list(
                            current_geom.geoms)
            for p in polygons:
                if p.exterior:
                    new_lines.append(LineString(p.exterior.coords))
                for interior in p.interiors:
                    new_lines.append(LineString(interior.coords))
            current_geom = current_geom.buffer(-spacing).simplify(
                cfg.ring_simplify, preserve_topology=False)

        logger.success(
            f"Offset fill complete. Generated {len(new_lines)} contour paths.")
        return GeometryState(boundary=state.boundary,
                             lines=state.lines + new_lines,
                             operation_name="offset_fill")
