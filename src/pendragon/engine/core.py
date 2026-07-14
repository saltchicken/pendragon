import inspect
from typing import Generator, List, Optional

from loguru import logger
from shapely.geometry import LineString
from shapely.geometry import Polygon

from .models import PipelineContext
from .models import PipelineState
from .registry import PipelineOperation, PluginRegistry
from .store import InMemoryStateStore
from .store import StateStore


class PendragonEngine:

    def __init__(self,
                 recipe: list,
                 boundary: Optional[Polygon] = None,
                 interactive: bool = False,
                 store: Optional[StateStore] = None,
                 registry: Optional[PluginRegistry] = None):

        self.recipe = recipe
        self.boundary = boundary or Polygon([(0, 0), (200, 0), (200, 200), (0, 200), (0, 0)])
        self.interactive = interactive
        self.operations: list[PipelineOperation] = []

        self.registry = registry or PluginRegistry()
        if not self.registry.operations:
            self.registry.discover()

        base_state = PipelineState(boundary=self.boundary,
                                   operation_name="base_geometry")
        self.store: StateStore = store or InMemoryStateStore(base_state)

    # --- Law of Demeter Accessors ---

    def get_operation(self, index: int) -> Optional[PipelineOperation]:
        """Safely fetches an operation by index."""
        if 0 <= index < len(self.operations):
            return self.operations[index]
        return None

    def get_operation_count(self) -> int:
        """Returns the total number of operations in the pipeline."""
        return len(self.operations)

    def get_operations(self) -> List[PipelineOperation]:
        """Returns a shallow copy of the operations to prevent direct mutation."""
        return self.operations.copy()
        
    def update_recipe(self, new_recipe: list) -> bool:
        """Updates the recipe and rebuilds operations without wiping the state store."""
        self.recipe = new_recipe
        return self.build_pipeline()

    def get_final_lines(self) -> list[LineString]:
        """Returns the geometry of the most recently computed state."""
        if len(self.store) > 0:
            return self.store.get_last().lines
        return []

    # --------------------------------

    def load_recipe(self, new_recipe: list) -> bool:
        self.recipe = new_recipe
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
        self.operations.clear()

        for step in self.recipe:
            op_name = step.get("operation")
            if not op_name:
                logger.error(f"Invalid step configuration, missing 'operation' key: {step}")
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
        target_step = min(target_step, self.get_operation_count())
        empty_context = PipelineContext()

        start_idx = len(self.store) - 1

        for i in range(start_idx, target_step):
            op = self.operations[i]
            current_state = self.store.get_last()
            logger.info(f"Computing operation {i}: {op.__class__.__name__}")

            sig = inspect.signature(op.process)
            if 'context' in sig.parameters:
                new_state = op.process(current_state, context=empty_context)
            else:
                new_state = op.process(current_state)

            self.store.append(new_state)
            yield new_state

    def run(self) -> list[LineString]:
        for _ in self.compute_to_generator(self.get_operation_count()):
            pass
        return self.get_final_lines()
