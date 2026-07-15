from typing import Literal, Optional

from loguru import logger
from pydantic import BaseModel, Field
from shapely.affinity import scale
from shapely.geometry import box, LineString, MultiLineString

from pendragon.engine import PipelineContext, PipelineOperation, PipelineState, register_operation


class SymmetryFoldConfig(BaseModel):
    axis: Literal["vertical", "horizontal"] = Field(
        default="vertical",
        description="The axis to fold across ('vertical' folds left/right, 'horizontal' folds top/bottom)."
    )
    keep_side: Literal["left", "right", "top", "bottom"] = Field(
        default="left",
        description="Which side of the original geometry to keep and mirror."
    )


@register_operation("symmetry_fold", config_class=SymmetryFoldConfig)
class SymmetryFoldMod(PipelineOperation):
    """Clips geometry to one half of the boundary and mirrors it across the center."""

    def process(self, state: PipelineState, context: Optional[PipelineContext] = None) -> PipelineState:
        cfg = self.config or SymmetryFoldConfig()
        ctx = context or PipelineContext()
        current_lines = state.lines

        if not current_lines:
            return state

        boundary = self.get_effective_boundary(state)
        if not boundary or boundary.is_empty:
            logger.warning("No boundary available to establish a fold center.")
            return state

        # 1. Resolve variables
        axis = ctx.variables.get("axis", cfg.axis)
        keep_side = ctx.variables.get("keep_side", cfg.keep_side)

        minx, miny, maxx, maxy = boundary.bounds
        
        # Use dynamic context center if available (for nested cell processing), otherwise boundary centroid
        cx = ctx.local_center_x if ctx.local_center_x is not None else boundary.centroid.x
        cy = ctx.local_center_y if ctx.local_center_y is not None else boundary.centroid.y
        origin = (cx, cy)

        # 2. Define the clipping box for the "kept" half
        if axis == "vertical":
            if keep_side not in ["left", "right"]:
                keep_side = "left"  # Fallback to prevent invalid states
            
            if keep_side == "left":
                clip_box = box(minx, miny, cx, maxy)
            else:
                clip_box = box(cx, miny, maxx, maxy)
            xfact, yfact = -1.0, 1.0
        else:  # horizontal
            if keep_side not in ["top", "bottom"]:
                keep_side = "top"  # Fallback
                
            if keep_side == "bottom":
                clip_box = box(minx, miny, maxx, cy)
            else:  # top
                clip_box = box(minx, cy, maxx, maxy)
            xfact, yfact = 1.0, -1.0

        logger.info(f"Folding symmetry across {axis} axis, keeping {keep_side} half...")

        # 3. Clip original lines to the keep box
        clipped_lines: list[LineString] = []
        for line in current_lines:
            if line.intersects(clip_box):
                clipped = line.intersection(clip_box)
                if isinstance(clipped, LineString) and not clipped.is_empty:
                    clipped_lines.append(clipped)
                elif isinstance(clipped, MultiLineString):
                    for sub_line in clipped.geoms:
                        if not sub_line.is_empty:
                            clipped_lines.append(sub_line)

        # 4. Mirror the clipped lines
        folded_lines: list[LineString] = []
        for line in clipped_lines:
            mirrored_geom = scale(line, xfact=xfact, yfact=yfact, origin=origin)
            folded_lines.append(mirrored_geom)

        # 5. Combine the original clipped half with its mirrored copy
        final_lines = clipped_lines + folded_lines

        logger.success(f"Symmetry fold complete. Final line count: {len(final_lines)}.")
        
        return PipelineState(
            boundary=state.boundary,
            lines=final_lines,
            operation_name="symmetry_fold"
        )
