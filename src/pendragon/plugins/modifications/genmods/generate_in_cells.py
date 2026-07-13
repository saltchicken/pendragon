import inspect
import math
from typing import Any, Dict, Optional

from loguru import logger
from pydantic import BaseModel
from pydantic import Field
from shapely import set_precision
from shapely.ops import polygonize
from shapely.ops import unary_union

from pendragon.engine import BasePluginConfig
from pendragon.engine import PipelineContext
from pendragon.engine import PipelineOperation
from pendragon.engine import PipelineState
from pendragon.engine import register_operation
from pendragon.utils import ImageSampler


class ImageModulatorConfig(BaseModel):
    image_path: str = Field(
        ..., description="File path to the source image to sample.")
    target_setting: str = Field(
        ...,
        description=
        "The parameter name in the sub-generator to modulate (e.g., 'revolutions', 'spacing')."
    )
    min_val: float = Field(
        ...,
        description=
        "The setting value when the image is pure white (0% darkness).")
    max_val: float = Field(
        ...,
        description=
        "The setting value when the image is pure black (100% darkness).")


class GenerateInCellsConfig(BasePluginConfig):
    generator: str = Field(
        default="grid_lines",
        description="The registry name of the generator to run in each cell.",
        json_schema_extra={"widget": "operation_selector"})

    generator_settings: Dict[str, Any] = Field(
        default_factory=dict,
        description="Settings to pass to the sub-generator.")

    auto_center: bool = Field(
        default=True,
        description=
        "Automatically inject center_x and center_y for the sub-generator based on cell centroid."
    )

    auto_rotate: bool = Field(
        default=False,
        description=
        "Automatically calculate the minimum rotated rectangle of the cell and inject its angle."
    )

    rotation_setting: str = Field(
        default="rotation",
        description=
        "The parameter name in the sub-generator to inject the calculated angle into (e.g., 'rotation')."
    )

    keep_scaffolding: bool = Field(
        default=False,
        description=
        "If true, includes the original incoming lines (the grid) in the final output."
    )

    tolerance: float = Field(
        default=1e-5,
        description=
        "Grid size for snapping vertices to resolve floating-point gaps. Set to 0 to disable."
    )

    image_modulator: Optional[ImageModulatorConfig] = Field(
        default=None,
        description=
        "Optional configuration to dynamically modulate a setting based on an image."
    )


@register_operation("generate_in_cells", config_class=GenerateInCellsConfig)
class GenerateInCellsOp(PipelineOperation):

    def process(self,
                state: PipelineState,
                context: Optional[PipelineContext] = None) -> PipelineState:
        cfg = self.config or GenerateInCellsConfig()
        current_lines = state.lines

        if not current_lines:
            logger.warning("No lines available to form cells. Skipping.")
            return state

        # 1. Slice the incoming lines at their intersection points
        noded_lines = unary_union(current_lines)

        # 2. Resolve floating-point inaccuracies
        if cfg.tolerance > 0:
            logger.debug(
                f"Applying precision snapping with tolerance {cfg.tolerance}")
            noded_lines = set_precision(noded_lines, grid_size=cfg.tolerance)

        # 3. Polygonize to detect closed loops
        polygons = list(polygonize(noded_lines))

        if not polygons:
            logger.warning(
                "No closed cells could be formed from the current lines.")
            return state

        logger.info(
            f"Formed {len(polygons)} cells. Running '{cfg.generator}' inside each..."
        )

        # 4. Initialize Image Sampler if modulation is configured
        sampler = None
        if cfg.image_modulator and cfg.image_modulator.image_path:
            if not state.boundary or state.boundary.is_empty:
                logger.warning(
                    "No active boundary to map the image to. Skipping image modulation."
                )
            else:
                logger.info(
                    f"Modulating '{cfg.image_modulator.target_setting}' based on {cfg.image_modulator.image_path}"
                )
                sampler = ImageSampler(cfg.image_modulator.image_path,
                                       state.boundary.bounds)

        # 5. Look up the requested sub-generator in the registry
        # TODO: This needs to be fixed with new registry
        op_info = OPERATION_REGISTRY.get(cfg.generator)
        if not op_info:
            logger.error(
                f"Sub-generator '{cfg.generator}' not found in registry.")
            return state

        SubGenClass = op_info["class"]
        SubConfigClass = op_info["config"]
        all_new_lines = []

        # 6. Iterate over every isolated cell
        for poly in polygons:
            # We no longer modify the static sub_config. It stays exactly as the user wrote it.
            cell_settings = cfg.generator_settings.copy()
            centroid = poly.centroid

            ctx_center_x = centroid.x if cfg.auto_center else None
            ctx_center_y = centroid.y if cfg.auto_center else None
            ctx_rotation = None
            ctx_vars = {}

            # Apply Geometry-Aware Rotation logic
            if cfg.auto_rotate:
                min_rect = poly.minimum_rotated_rectangle
                best_angle = 0.0
                if min_rect.geom_type == 'Polygon':
                    coords = list(min_rect.exterior.coords)
                    longest_length = -1
                    for i in range(len(coords) - 1):
                        p1, p2 = coords[i], coords[i + 1]
                        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
                        length = math.hypot(dx, dy)
                        if length > longest_length:
                            longest_length = length
                            best_angle = math.degrees(math.atan2(dy, dx))
                    ctx_rotation = best_angle % 180.0
                elif min_rect.geom_type == 'LineString':
                    coords = list(min_rect.coords)
                    dx, dy = coords[-1][0] - coords[0][0], coords[-1][
                        1] - coords[0][1]
                    ctx_rotation = math.degrees(math.atan2(dy, dx)) % 180.0

                # Make the rotation available generally and strictly under the configured string
                ctx_vars[cfg.rotation_setting] = ctx_rotation

            # Apply Image Modulation logic
            if sampler and cfg.image_modulator:
                darkness = sampler.get_darkness(centroid.x, centroid.y)
                val_range = cfg.image_modulator.max_val - cfg.image_modulator.min_val
                modulated_value = cfg.image_modulator.min_val + (darkness *
                                                                 val_range)
                ctx_vars[cfg.image_modulator.target_setting] = modulated_value

            cell_context = PipelineContext(local_center_x=ctx_center_x,
                                           local_center_y=ctx_center_y,
                                           local_rotation=ctx_rotation,
                                           variables=ctx_vars)

            sub_config = None
            if SubConfigClass:
                try:
                    sub_config = SubConfigClass(**cell_settings)
                except Exception as e:
                    logger.error(
                        f"Error configuring sub-generator for a cell: {e}")
                    continue

            sub_gen = SubGenClass(config=sub_config)

            temp_state = PipelineState(boundary=poly,
                                       lines=[],
                                       operation_name=f"cell_{cfg.generator}")

            # Safely Execute the sub-generator
            sig = inspect.signature(sub_gen.process)
            if 'context' in sig.parameters:
                result_state = sub_gen.process(temp_state, context=cell_context)
            else:
                result_state = sub_gen.process(temp_state)

            all_new_lines.extend(result_state.lines)

        logger.success(
            f"Generated {len(all_new_lines)} paths across {len(polygons)} cells."
        )

        final_lines = all_new_lines
        if cfg.keep_scaffolding:
            logger.info("Keeping original scaffolding lines in the output.")
            final_lines = current_lines + all_new_lines

        return PipelineState(boundary=state.boundary,
                             lines=final_lines,
                             operation_name="generate_in_cells")
