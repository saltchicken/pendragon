from typing import Optional

from loguru import logger
from pydantic import BaseModel
from pydantic import Field
from shapely.affinity import scale
from shapely.geometry import LineString
from shapely.geometry import MultiLineString

from pendragon.engine import PipelineContext
from pendragon.engine import PipelineOperation
from pendragon.engine import PipelineState
from pendragon.engine import register_operation


class MirrorConfig(BaseModel):
    mirror_x: bool = Field(
        default=True, 
        description="Mirror horizontally (inverts X coordinates)."
    )
    mirror_y: bool = Field(
        default=False, 
        description="Mirror vertically (inverts Y coordinates)."
    )
    duplicate: bool = Field(
        default=True, 
        description="Keep the original geometry alongside the mirrored copy."
    )


@register_operation("mirror", config_class=MirrorConfig)
class MirrorMod(PipelineOperation):
    """Mirrors existing paths across the X and/or Y axis of the boundary's center."""

    def process(
        self,
        state: PipelineState,
        context: Optional[PipelineContext] = None
    ) -> PipelineState:
        cfg = self.config or MirrorConfig()
        ctx = context or PipelineContext()
        current_lines = state.lines

        if not current_lines:
            return state

        boundary = self.get_effective_boundary(state)
        if not boundary or boundary.is_empty:
            logger.warning("No boundary available to establish a mirror center.")
            return state

        # Resolve dynamic variables via context or static config
        mirror_x = ctx.variables.get("mirror_x", cfg.mirror_x)
        mirror_y = ctx.variables.get("mirror_y", cfg.mirror_y)
        duplicate = ctx.variables.get("duplicate", cfg.duplicate)

        if not mirror_x and not mirror_y:
            return state

        # Determine the pivot center (support localized cells from generate_in_cells)
        cx = ctx.local_center_x if ctx.local_center_x is not None else boundary.centroid.x
        cy = ctx.local_center_y if ctx.local_center_y is not None else boundary.centroid.y
        origin = (cx, cy)

        # Scale by -1 on an axis reflects it perfectly across the origin
        xfact = -1.0 if mirror_x else 1.0
        yfact = -1.0 if mirror_y else 1.0

        logger.info(
            f"Mirroring {len(current_lines)} lines "
            f"(x: {mirror_x}, y: {mirror_y}, duplicate: {duplicate}) around center {origin}..."
        )

        final_lines: list[LineString] = []
        if duplicate:
            final_lines.extend(current_lines)

        for line in current_lines:
            if line.is_empty:
                continue
            
            mirrored_geom = scale(line, xfact=xfact, yfact=yfact, origin=origin)
            
            if isinstance(mirrored_geom, LineString):
                final_lines.append(mirrored_geom)
            elif isinstance(mirrored_geom, MultiLineString):
                for sub_line in mirrored_geom.geoms:
                    if not sub_line.is_empty:
                        final_lines.append(sub_line)

        logger.success(f"Mirroring complete. Path count is now {len(final_lines)}.")
        
        return PipelineState(
            boundary=state.boundary,
            lines=final_lines,
            operation_name="mirror"
        )
