from typing import Generic, Optional

from loguru import logger

from .models import T_State
from .registry import OperationRegistry
from .runner import InteractiveRunner
from .runner import PipelineRunner


class CoreEngine(Generic[T_State]):
    """
    Universal orchestrator. Resolves configs, builds runners, and acts as the API interface.
    """

    def __init__(self,
                 recipe: list,
                 initial_state: T_State,
                 registry: OperationRegistry[T_State],
                 interactive: bool = False):
        self.recipe = recipe
        self.initial_state = initial_state
        self.registry = registry
        self.interactive = interactive

        if self.interactive:
            self.runner = InteractiveRunner[T_State](self.initial_state)
        else:
            self.runner = PipelineRunner[T_State](self.initial_state)

    def load_recipe(self, new_recipe: list) -> bool:
        """Resets the engine's runner and loads a new recipe dynamically."""
        self.recipe = new_recipe

        if self.interactive:
            self.runner = InteractiveRunner[T_State](self.initial_state)
        else:
            self.runner = PipelineRunner[T_State](self.initial_state)

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
                logger.error(
                    f"Invalid step configuration, missing 'operation' key: {step}"
                )
                return False

            op_info = self.registry.get(op_name)
            if not op_info:
                logger.error(f"Operation '{op_name}' not found in registry.")
                return False

            PluginClass = op_info["class"]
            ConfigClass = op_info["config"]

            validated_config = None
            if ConfigClass:
                try:
                    validated_config = ConfigClass(**step.get("settings", {}))
                    logger.success(
                        f"Successfully validated config for {op_name}")
                except Exception as e:
                    logger.error(f"Configuration error for '{op_name}': {e}")
                    return False

            plugin_instance = PluginClass(config=validated_config)
            self.runner.add_operation(plugin_instance)

        return True

    def run(self) -> T_State:
        """Executes the pipeline sequentially and returns the final state."""
        self.runner.execute_all()
        return self.runner.get_final_state()
