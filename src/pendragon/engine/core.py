import inspect
from typing import Generator, List, Optional

from loguru import logger
from shapely.geometry import LineString
from shapely.geometry import Polygon

from .models import PipelineContext
from .models import PipelineState
from .registry import OPERATION_REGISTRY
from .registry import PipelineOperation
from .store import InMemoryStateStore
from .store import StateStore


class PendragonEngine:

    def __init__(self,
                 recipe: list,
                 boundary: Optional[Polygon] = None,
                 interactive: bool = False,
                 store: Optional[StateStore] = None):  # <-- Inject here

        self.recipe = recipe
        self.boundary = boundary or Polygon([(0, 0), (200, 0), (200, 200),
                                             (0, 200), (0, 0)])
        self.interactive = interactive
        self.operations: list[PipelineOperation] = []

        # Initialize the store. The engine no longer owns the list natively.
        base_state = PipelineState(boundary=self.boundary,
                                   operation_name="base_geometry")
        self.store: StateStore = store or InMemoryStateStore(base_state)

    def load_recipe(self, new_recipe: list) -> bool:
        self.recipe = new_recipe
        # Reset the store instead of overwriting a native list
        self.store.reset(
            PipelineState(boundary=self.boundary,
                          operation_name="base_geometry"))

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
                logger.error(
                    f"Invalid step configuration, missing 'operation' key: {step}"
                )
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
        valid_length = step_index + 1
        self.store.truncate(valid_length)

    def go_to_step(self, target_step: int) -> PipelineState:
        for _ in self.compute_to_generator(target_step):
            pass

        target = min(target_step, len(self.store) - 1)
        return self.store.get(target)

    def compute_to_generator(
            self, target_step: int) -> Generator[PipelineState, None, None]:
        target_step = min(target_step, len(self.operations))
        empty_context = PipelineContext()

        # Start computing from the end of our valid cached history
        start_idx = len(self.store) - 1

        for i in range(start_idx, target_step):
            op = self.operations[i]
            current_state = self.store.get_last()  # Fetch from store
            logger.info(f"Computing operation {i}: {op.__class__.__name__}")

            sig = inspect.signature(op.process)
            if 'context' in sig.parameters:
                new_state = op.process(current_state, context=empty_context)
            else:
                new_state = op.process(current_state)

            self.store.append(new_state)  # Save to store
            yield new_state

    def run(self) -> list[LineString]:
        for _ in self.compute_to_generator(len(self.operations)):
            pass

        return self.store.get_last().lines if len(self.store) > 0 else []
