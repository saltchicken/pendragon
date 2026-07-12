from typing import List, Optional
from loguru import logger
from pydantic import BaseModel, Field
from shapely.affinity import rotate, scale, translate
from shapely.geometry import LineString, MultiLineString

from nodeweaver.models import PipelineContext
from pendragon.state import GeometryState
from pendragon.registry import PendragonOperation, dxf_registry


class TransformConfig(BaseModel):
    translate_x: float = Field(default=0.0, description="Translation along the X axis.")
    translate_y: float = Field(default=0.0, description="Translation along the Y axis.")
    rotation: float = Field(default=0.0, description="Rotation angle in degrees (counter-clockwise).")
    rotation_origin: str = Field(default="center", description="Origin point for rotation.")
    scale_x: float = Field(default=1.0, description="Scaling multiplier for the X axis.")
    scale_y: float = Field(default=1.0, description="Scaling multiplier for the Y axis.")
    scale_origin: str = Field(default="center", description="Origin point for scaling.")


@dxf_registry.register("transform", config_class=TransformConfig)
class TransformMod(PendragonOperation):
    """
    Applies affine transformations to the current geometry. 
    Operations are applied in the following order: Scale -> Rotate -> Translate.
    """

    def process(self, state: GeometryState, context: Optional[PipelineContext] = None) -> GeometryState:
        cfg = self.config or TransformConfig()
        ctx = context or PipelineContext()
        current_lines = state.lines

        valid_lines = [line for line in current_lines if not line.is_empty]
        if not valid_lines:
            return state

        # 1. Resolve variables
        tx = ctx.get("translate_x", cfg.translate_x)
        ty = ctx.get("translate_y", cfg.translate_y)
        rot = ctx.get("rotation", cfg.rotation)
        rot_orig = ctx.get("rotation_origin", cfg.rotation_origin)
        sx = ctx.get("scale_x", cfg.scale_x)
        sy = ctx.get("scale_y", cfg.scale_y)
        s_orig = ctx.get("scale_origin", cfg.scale_origin)

        # 2. Resolve dynamic origins
        def resolve_origin(origin_pref: str):
            lc_x = ctx.get("local_center_x")
            lc_y = ctx.get("local_center_y")
            if origin_pref == "center" and lc_x is not None and lc_y is not None:
                return (lc_x, lc_y)
            return origin_pref

        final_rot_orig = resolve_origin(rot_orig)
        final_scale_orig = resolve_origin(s_orig)

        logger.info(f"Applying transforms - Translate: ({tx}, {ty}), Rotate: {rot}°, Scale: ({sx}, {sy})")

        # 3. Pack lines into a single geometry to preserve relative coordinates
        geom = MultiLineString(valid_lines)
            
        # Scale
        if sx != 1.0 or sy != 1.0:
            geom = scale(geom, xfact=sx, yfact=sy, origin=final_scale_orig)

        # Rotate
        if rot != 0.0:
            geom = rotate(geom, angle=rot, origin=final_rot_orig)

        # Translate
        if tx != 0.0 or ty != 0.0:
            geom = translate(geom, xoff=tx, yoff=ty)

        # Unpack back to a list
        transformed_lines = list(geom.geoms)

        logger.success("Transformation complete.")
        return GeometryState(boundary=state.boundary,
                             lines=transformed_lines,
                             operation_name="transform")
