# src/pendragon/core/engine.py

from typing import List, Optional
import matplotlib.pyplot as plt
from loguru import logger
from shapely.geometry import Polygon, LineString

from pendragon.core.models import PipelineState
from pendragon.core.runner import PipelineRunner
from pendragon.core.registry import OPERATION_REGISTRY
from pendragon.pen import PenTool, PenConfig


class PendragonEngine:
    def __init__(self, recipe: list, boundary: Optional[Polygon] = None):
        """
        Initializes the engine with a recipe and an optional boundary.
        """
        self.recipe = recipe
        # Hardcoded for now, but prepped for Issue #1 (Dynamic Boundaries)
        self.boundary = boundary or Polygon([(0, 0), (200, 0), (200, 200), (0, 200), (0, 0)])
        
        initial_state = PipelineState(boundary=self.boundary, operation_name="base_geometry")
        self.runner = PipelineRunner(initial_state)

    def build_pipeline(self) -> bool:
        """
        Validates the recipe and queues up the configured plugin operations.
        Returns True if successful, False if validation fails.
        """
        for step in self.recipe:
            op_name = step.get("operation")
            if not op_name:
                logger.error(f"Invalid step configuration, missing 'operation' key: {step}")
                return False

            op_info = OPERATION_REGISTRY.get(op_name)
            if not op_info:
                logger.error(f"Operation '{op_name}' not found in registry.")
                return False

            PluginClass = op_info["class"]
            ConfigClass = op_info["config"]
            
            validated_config = None
            if ConfigClass:
                try:
                    validated_config = ConfigClass(**step.get("settings", {}))
                    logger.success(f"Successfully validated config for {op_name}")
                except Exception as e:
                    logger.error(f"Configuration error for '{op_name}': {e}")
                    return False
                    
            plugin_instance = PluginClass(config=validated_config)
            self.runner.add_operation(plugin_instance)
            
        return True

    def run(self) -> List[LineString]:
        """
        Executes the pipeline sequentially and returns the final geometries.
        """
        self.runner.execute_all()
        return self.runner.get_final_lines()

    def export_gcode(self, lines: List[LineString], output_path: str, pen_config: Optional[PenConfig] = None):
        """
        Translates LineStrings into G-code using the PenTool context manager.
        """
        if not lines:
            logger.warning("No lines to export!")
            return
            
        config = pen_config or PenConfig()
        logger.info(f"Generating G-code to {output_path}...")
        
        with PenTool(config=config, output_filename=output_path) as pen:
            for line in lines:
                points = list(line.coords)
                pen.draw_path(points)

    def visualize(self, lines: List[LineString]):
        """
        Renders the final paths and boundary in a Matplotlib window.
        """
        if not lines:
            logger.warning("No lines to visualize!")
            return
            
        logger.info("Opening visualization window...")
        fig, ax = plt.subplots(figsize=(8, 8))
        
        # Plot boundary
        bx, by = self.boundary.exterior.xy
        ax.plot(bx, by, color='red', linestyle='--', label='Boundary')

        # Plot paths
        for line in lines:
            x, y = line.xy
            ax.plot(x, y, color='black', linewidth=1)
            
        ax.set_aspect('equal')
        ax.set_title("Pendragon Generated Lines")
        plt.show()
