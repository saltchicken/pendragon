import inspect
from typing import Generator, List, Optional

from loguru import logger
from shapely.geometry import LineString, Polygon

from .models import PipelineContext, PipelineState
from .registry import OPERATION_REGISTRY, PipelineOperation


class PendragonEngine:
    """
    Core pipeline orchestrator.
    Manages its own history, caching, and intelligent recalculation.
    """

    def __init__(self,
                 recipe: list,
                 boundary: Optional[Polygon] = None,
                 interactive: bool = False):
        self.recipe = recipe
        self.boundary = boundary or Polygon([(0, 0), (200, 0), (200, 200), (0, 200), (0, 0)])
        self.interactive = interactive

        self.operations: List[PipelineOperation] = []
        
        # The engine holds its own state history natively, starting with the base boundary
        self.history: List[PipelineState] = [
            PipelineState(boundary=self.boundary, operation_name="base_geometry")
        ]

    def load_recipe(self, new_recipe: list) -> bool:
        """Resets the engine and loads a new recipe dynamically."""
        self.recipe = new_recipe
        self.history = [PipelineState(boundary=self.boundary, operation_name="base_geometry")]
        
        success = self.build_pipeline()
        if success:
            logger.info("Successfully loaded and built new pipeline recipe.")
        else:
            logger.error("Failed to build pipeline from new recipe.")
        return success

    def build_pipeline(self) -> bool:
        """Instantiates operations based on the current recipe."""
        self.operations.clear()
        
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
                except Exception as e:
                    logger.error(f"Configuration error for '{op_name}': {e}")
                    return False

            self.operations.append(PluginClass(config=validated_config))
        return True

    def invalidate_from(self, step_index: int):
        """
        Clears cached history from this step index onwards.
        This forces a recalculation of subsequent steps when next requested.
        """
        valid_length = step_index + 1
        if len(self.history) > valid_length:
            logger.debug(f"Invalidating history from step {step_index} onwards.")
            self.history = self.history[:valid_length]

    def go_to_step(self, target_step: int) -> PipelineState:
        """
        Intelligently calculates up to the target step and returns the state.
        If the history already exists, it skips computation and returns instantly.
        """
        for _ in self.compute_to_generator(target_step):
            pass
        
        target = min(target_step, len(self.history) - 1)
        return self.history[target]

    def compute_to_generator(self, target_step: int) -> Generator[PipelineState, None, None]:
        """
        Generator that intelligently computes missing states up to target_step.
        Skips recalculation for steps already cached in self.history.
        """
        target_step = min(target_step, len(self.operations))
        empty_context = PipelineContext()

        # Start computing from the end of our valid cached history
        start_idx = len(self.history) - 1

        for i in range(start_idx, target_step):
            op = self.operations[i]
            current_state = self.history[-1]
            logger.info(f"Computing operation {i}: {op.__class__.__name__}")

            sig = inspect.signature(op.process)
            if 'context' in sig.parameters:
                new_state = op.process(current_state, context=empty_context)
            else:
                new_state = op.process(current_state)

            self.history.append(new_state)
            yield new_state

    def run(self) -> List[LineString]:
        """Executes the entire pipeline and returns the final geometries."""
        for _ in self.compute_to_generator(len(self.operations)):
            pass
        return self.history[-1].lines if self.history else []
