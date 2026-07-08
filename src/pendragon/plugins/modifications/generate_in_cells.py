from typing import Any, Dict
from loguru import logger
from pydantic import BaseModel, Field
from shapely.ops import polygonize, unary_union

from pendragon.core import PipelineOperation, PipelineState, register_operation
from pendragon.core.registry import OPERATION_REGISTRY


class GenerateInCellsConfig(BaseModel):
    generator: str = Field(..., description="The registry name of the generator to run in each cell.")
    generator_settings: Dict[str, Any] = Field(default_factory=dict, description="Settings to pass to the sub-generator.")
    auto_center: bool = Field(default=True, description="Automatically inject center_x and center_y for the sub-generator based on cell centroid.")

    keep_scaffolding: bool = Field(
        default=False, 
        description="If true, includes the original incoming lines (the grid) in the final output."
    )


@register_operation("generate_in_cells", config_class=GenerateInCellsConfig)
class GenerateInCellsOp(PipelineOperation):

    def process(self, state: PipelineState) -> PipelineState:
        cfg = self.config
        current_lines = state.lines

        if not current_lines:
            logger.warning("No lines available to form cells. Skipping.")
            return state

        # 1. Grab the outer perimeter of the current boundary
        boundary_ring = state.boundary.boundary
        
        # 2. Combine our grid lines with the outer perimeter
        all_lines = current_lines + [boundary_ring]
        
        # 3. Slice all lines at their intersection points
        noded_lines = unary_union(all_lines)

        # 4. Now polygonize can successfully detect the closed loops
        polygons = list(polygonize(noded_lines))
        # --------------------------------------------

        if not polygons:
            logger.warning("No closed cells could be formed from the current lines.")
            return state

        logger.info(f"Formed {len(polygons)} cells. Running '{cfg.generator}' inside each...")

        # 2. Look up the requested sub-generator in the registry
        op_info = OPERATION_REGISTRY.get(cfg.generator)
        if not op_info:
            logger.error(f"Sub-generator '{cfg.generator}' not found in registry.")
            return state

        SubGenClass = op_info["class"]
        SubConfigClass = op_info["config"]

        all_new_lines = []

        # 3. Iterate over every isolated cell
        for poly in polygons:
            cell_settings = cfg.generator_settings.copy()
            
            # Inject centroid coordinates if the sub-generator needs a center point
            if cfg.auto_center:
                centroid = poly.centroid
                cell_settings["center_x"] = centroid.x
                cell_settings["center_y"] = centroid.y

            # Validate the dynamic sub-configuration
            sub_config = None
            if SubConfigClass:
                try:
                    sub_config = SubConfigClass(**cell_settings)
                except Exception as e:
                    logger.error(f"Error configuring sub-generator for a cell: {e}")
                    continue
            
            sub_gen = SubGenClass(config=sub_config)
            
            # 4. Create a temporary local state where the boundary is ONLY this cell
            #    and the lines are empty so the generator starts fresh.
            temp_state = PipelineState(
                boundary=poly,
                lines=[], 
                operation_name=f"cell_{cfg.generator}"
            )
            
            # 5. Execute the sub-generator and collect the output
            result_state = sub_gen.process(temp_state)
            all_new_lines.extend(result_state.lines)

        logger.success(f"Generated {len(all_new_lines)} paths across {len(polygons)} cells.")

        final_lines = all_new_lines
        if cfg.keep_scaffolding:
            logger.info("Keeping original scaffolding lines in the output.")
            final_lines = current_lines + all_new_lines

        # 6. Return the unified lines, but PRESERVE the original global boundary
        return PipelineState(
            boundary=state.boundary,
            lines=final_lines,
            operation_name="generate_in_cells"
        )
