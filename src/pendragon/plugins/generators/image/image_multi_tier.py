from typing import Dict, Optional
import math

from loguru import logger
from pydantic import Field
from shapely.geometry import Polygon

from pendragon.engine import PipelineContext, PipelineOperation, PipelineState, register_operation
from pendragon.engine.registry import OPERATION_REGISTRY, BasePluginConfig
from pendragon.utils import ImageSampler


class ImageMultiTierConfig(BasePluginConfig):
    source_image: str = Field(
        default="", 
        description="Path to the source image.", 
        json_schema_extra={"widget": "file_picker"}
    )
    cell_size: float = Field(
        default=5.0, 
        description="Size of the grid cells."
    )
    
    # Tier 1 (Darkest)
    tier_1_op: str = Field(default="spiral", json_schema_extra={"widget": "operation_selector"})
    tier_1_settings: dict = Field(default_factory=dict)
    
    # Tier 2 (Mid-Dark)
    tier_2_op: str = Field(default="concentric", json_schema_extra={"widget": "operation_selector"})
    tier_2_settings: dict = Field(default_factory=dict)
    
    # Tier 3 (Mid-Light)
    tier_3_op: str = Field(default="grid_lines", json_schema_extra={"widget": "operation_selector"})
    tier_3_settings: dict = Field(default_factory=dict)
    
    # Tier 4 (Lightest)
    tier_4_op: str = Field(default="", json_schema_extra={"widget": "operation_selector"})
    tier_4_settings: dict = Field(default_factory=dict)


@register_operation("image_multi_tier", config_class=ImageMultiTierConfig)
class ImageMultiTierGen(PipelineOperation):
    """
    Samples an image across a grid and assigns one of 4 operations 
    to each cell based on the darkness threshold (0.0 to 1.0).
    """

    def _load_generator(self, op_name: str, settings: dict):
        if not op_name or op_name.lower() == "none":
            return None
        
        op_info = OPERATION_REGISTRY.get(op_name)
        if not op_info:
            logger.warning(f"Operation '{op_name}' not found in registry.")
            return None
            
        PluginClass = op_info["class"]
        ConfigClass = op_info["config"]
        
        config = ConfigClass(**settings) if ConfigClass else None
        return PluginClass(config=config)

    def process(self,
                state: PipelineState,
                context: Optional[PipelineContext] = None) -> PipelineState:
        
        cfg = self.config or ImageMultiTierConfig()
        
        if not cfg.source_image:
            logger.warning("No source image provided for image_multi_tier.")
            return state

        effective_boundary = self.get_effective_boundary(state)
        minx, miny, maxx, maxy = effective_boundary.bounds

        logger.info(f"Loading Multi-Tier image: {cfg.source_image}")
        sampler = ImageSampler(cfg.source_image, effective_boundary.bounds)
        
        # Pre-instantiate the generators to avoid rebuilding them thousands of times
        tier_1_gen = self._load_generator(cfg.tier_1_op, cfg.tier_1_settings) # 0.75 - 1.0
        tier_2_gen = self._load_generator(cfg.tier_2_op, cfg.tier_2_settings) # 0.50 - 0.75
        tier_3_gen = self._load_generator(cfg.tier_3_op, cfg.tier_3_settings) # 0.25 - 0.50
        tier_4_gen = self._load_generator(cfg.tier_4_op, cfg.tier_4_settings) # 0.00 - 0.25

        new_lines = []
        cell_size = cfg.cell_size
        
        cols = math.ceil((maxx - minx) / cell_size)
        rows = math.ceil((maxy - miny) / cell_size)

        logger.info(f"Processing {cols}x{rows} grid cells...")

        for col in range(cols):
            for row in range(rows):
                x = minx + (col * cell_size)
                y = miny + (row * cell_size)
                cx, cy = x + (cell_size / 2), y + (cell_size / 2)
                
                # Check if cell center is inside the main boundary
                # We do this fast check to avoid generating geometry outside non-square bounds
                import shapely.geometry
                if not effective_boundary.contains(shapely.geometry.Point(cx, cy)):
                    continue

                # Sample the image (returns 0.0 for white, 1.0 for black)
                darkness = sampler.get_darkness(cx, cy)
                
                # Determine which generator to use based on the quartile
                active_gen = None
                if darkness >= 0.75:
                    active_gen = tier_1_gen
                elif darkness >= 0.50:
                    active_gen = tier_2_gen
                elif darkness >= 0.25:
                    active_gen = tier_3_gen
                else:
                    active_gen = tier_4_gen
                
                if active_gen:
                    # Create the local bounding box for this cell
                    cell_poly = Polygon([
                        (x, y), (x + cell_size, y), 
                        (x + cell_size, y + cell_size), (x, y + cell_size), 
                        (x, y)
                    ])
                    
                    # Create isolated state and context for the sub-generator
                    sub_state = PipelineState(boundary=cell_poly)
                    sub_ctx = PipelineContext(local_center_x=cx, local_center_y=cy)
                    
                    try:
                        result_state = active_gen.process(sub_state, sub_ctx)
                        new_lines.extend(result_state.lines)
                    except Exception as e:
                        logger.error(f"Error running {active_gen.__class__.__name__} at cell ({x},{y}): {e}")

        logger.success(f"Multi-tier image processing generated {len(new_lines)} segments.")
        return PipelineState(boundary=state.boundary,
                             lines=state.lines + new_lines,
                             operation_name="image_multi_tier")
