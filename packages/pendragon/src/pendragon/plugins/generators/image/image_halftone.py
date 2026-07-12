import math
from typing import Optional

from loguru import logger
from pydantic import Field

from nodeweaver.models import PipelineContext
from pendragon.state import GeometryState
from pendragon.registry import PendragonBaseConfig, PendragonOperation, dxf_registry
from pendragon.utils import ImageSampler


class ImageHalftoneConfig(PendragonBaseConfig):
    source_image: str = Field(default="",
                              description="Source image to map.",
                              json_schema_extra={"widget": "file_picker"})
    spacing: float = Field(default=5.0,
                           ge=0.1,
                           description="Grid spacing between generated shapes.")

    # --- Meta-Generator Config ---
    generator: str = Field(default="concentric",
                           description="The generator to run in each cell.",
                           json_schema_extra={"widget": "operation_selector"})
    generator_settings: dict = Field(
        default_factory=dict, description="Settings for the chosen generator.")
    target_setting: str = Field(
        default="max_radius",
        description="The exact name of the parameter to modulate.")

    # --- Modulation Bounds ---
    min_val: float = Field(default=0.1,
                           description="Value applied in pure white areas.")
    max_val: float = Field(default=2.5,
                           description="Value applied in pure black areas.")


@dxf_registry.register("image_halftone", config_class=ImageHalftoneConfig)
class ImageHalftoneGen(PendragonOperation):

    def process(self,
                state: GeometryState,
                context: Optional[PipelineContext] = None) -> GeometryState:
        cfg = self.config or ImageHalftoneConfig()

        if not cfg.source_image:
            logger.warning(
                "No source image provided. Skipping halftone generation.")
            return state

        # 1. Look up the chosen sub-generator from the registry
        op_info = dxf_registry.get(cfg.generator)
        if not op_info:
            logger.error(f"Halftone sub-generator '{cfg.generator}' not found.")
            return state

        SubGenClass = op_info["class"]
        SubConfigClass = op_info["config"]

        # 2. Instantiate the sub-generator with its baseline settings
        try:
            sub_config = SubConfigClass(**cfg.generator_settings)
            sub_gen = SubGenClass(config=sub_config)
        except Exception as e:
            logger.error(f"Failed to initialize '{cfg.generator}': {e}")
            return state

        effective_boundary = self.get_effective_boundary(state)
        minx, miny, maxx, maxy = effective_boundary.bounds

        logger.info(
            f"Generating modulated {cfg.generator} pattern from {cfg.source_image}"
        )
        sampler = ImageSampler(cfg.source_image, effective_boundary.bounds)

        new_lines = []
        half_space = cfg.spacing / 2.0

        current_x = minx
        while current_x <= maxx:
            current_y = miny
            while current_y <= maxy:

                # 3. Calculate the modulated value (Lerp)
                darkness = sampler.get_darkness(current_x, current_y)
                modulated_val = cfg.min_val + (darkness *
                                               (cfg.max_val - cfg.min_val))

                # 4. Inject the new value directly into the sub-generator's config
                if hasattr(sub_gen.config, cfg.target_setting):
                    setattr(sub_gen.config, cfg.target_setting, modulated_val)
                else:
                    logger.warning(
                        f"Setting '{cfg.target_setting}' does not exist on {cfg.generator}"
                    )
                    return state

                # 5. Create a localized context so the generator knows its explicit center
                local_ctx = PipelineContext(variables={
                    "center_x": current_x,
                    "center_y": current_y
                })

                # 6. Create a distinct boundary box for this specific cell to allow local clipping
                cell_poly = box(current_x - half_space, current_y - half_space,
                                current_x + half_space, current_y + half_space)
                local_state = GeometryState(boundary=cell_poly,
                                            operation_name=f"cell_{cfg.generator}")

                # 7. Execute the sub-generator and collect its lines
                result_state = sub_gen.process(local_state, context=local_ctx)
                new_lines.extend(result_state.lines)

                current_y += cfg.spacing
            current_x += cfg.spacing

        logger.success(
            f"Halftone generation complete. Created {len(new_lines)} path segments."
        )

        return GeometryState(boundary=state.boundary,
                             lines=state.lines + new_lines,
                             operation_name="image_halftone")
