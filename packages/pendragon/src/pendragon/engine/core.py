from typing import List, Optional
from loguru import logger
from shapely.geometry import LineString, Polygon

from .models import PipelineState
from .registry import OPERATION_REGISTRY
from .runner import InteractiveRunner, PipelineRunner


class PendragonEngine:
    """
    Core pipeline orchestrator.
    Pure geometry processing engine. No UI, no threading, no I/O.
    """

    def __init__(self,
                 recipe: list,
                 boundary: Optional[Polygon] = None,
                 interactive: bool = False):
        self.recipe = recipe
        self.boundary = boundary or Polygon([(0, 0), (200, 0), (200, 200), (0, 200), (0, 0)])
        self.interactive = interactive

        initial_state = PipelineState(boundary=self.boundary, operation_name="base_geometry")

        if self.interactive:
            self.runner = InteractiveRunner(initial_state)
        else:
            self.runner = PipelineRunner(initial_state)

    def load_recipe(self, new_recipe: list) -> bool:
        """Resets the engine's runner and loads a new recipe dynamically."""
        self.recipe = new_recipe
        initial_state = PipelineState(boundary=self.boundary, operation_name="base_geometry")

        if self.interactive:
            self.runner = InteractiveRunner(initial_state)
        else:
            self.runner = PipelineRunner(initial_state)

        success = self.build_pipeline()

        if success:
            logger.info("Successfully loaded and built new pipeline recipe.")
        else:
            logger.error("Failed to build pipeline from new recipe.")

        return success

    def build_pipeline(self) -> bool:
        """Validates the recipe and queues up the configured plugin operations."""
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
        """Executes the pipeline sequentially and returns the final geometries."""
        self.runner.execute_all()
        return self.runner.get_final_lines()
