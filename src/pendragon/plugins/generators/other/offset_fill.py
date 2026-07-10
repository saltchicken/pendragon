from typing import List

from loguru import logger
from pydantic import Field
from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

from pendragon.core import BasePluginConfig
from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation


class OffsetFillConfig(BasePluginConfig):
    spacing: float = Field(
        default=2.0, 
        gt=0.0, 
        description="Distance between concentric offset rings."
    )
    ring_simplify: float = Field(
        default=0.2, 
        ge=0.0, 
        description="Simplification tolerance for the generated rings."
    )


@register_operation("offset_fill", config_class=OffsetFillConfig)
class OffsetFillGen(PipelineOperation):
    """Fills the current clipping boundary with concentric inward offsets."""

    def process(self, state: PipelineState) -> PipelineState:
        cfg = self.config or OffsetFillConfig()
        
        # Fetch the boundary, automatically applying any configured overscan buffer
        effective_boundary = self.get_effective_boundary(state)
        
        if not effective_boundary or effective_boundary.is_empty:
            logger.warning("No boundary available to fill. Skipping offset_fill.")
            return state

        logger.info(f"Generating concentric offset fill with spacing {cfg.spacing}...")

        new_lines: List[LineString] = []
        
        # Use Shapely's buffer with a negative value to inset the polygon
        current_geom = effective_boundary.buffer(-cfg.spacing).simplify(
            cfg.ring_simplify, preserve_topology=False
        )

        # Keep stepping inward until the polygon collapses completely
        while not current_geom.is_empty and current_geom.area > 0:
            
            # Handle both singular Polygons and MultiPolygons safely
            polygons = (
                [current_geom] 
                if current_geom.geom_type == 'Polygon' 
                else list(current_geom.geoms)
            )
            
            for p in polygons:
                # Extract the outer boundary of the current offset level
                if p.exterior:
                    new_lines.append(LineString(p.exterior.coords))
                    
                # Extract any holes (interiors) at this offset level
                for interior in p.interiors:
                    new_lines.append(LineString(interior.coords))
                    
            # Step inward again for the next loop iteration
            current_geom = current_geom.buffer(-cfg.spacing).simplify(
                cfg.ring_simplify, preserve_topology=False
            )

        logger.success(f"Offset fill complete. Generated {len(new_lines)} contour paths.")

        # Append the new contour paths to any existing lines in the pipeline
        return PipelineState(
            boundary=state.boundary,  # Always pass the original, un-overscanned boundary forward
            lines=state.lines + new_lines,
            operation_name="offset_fill"
        )
