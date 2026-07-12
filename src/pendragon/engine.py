import inspect
from typing import List, Optional

from loguru import logger
import numpy as np
from shapely.geometry import LineString
from shapely.geometry import Polygon

from pendragon.core.discovery import load_plugins
from pendragon.core.models import PipelineContext
from pendragon.core.models import PipelineState
from pendragon.core.registry import OPERATION_REGISTRY

from .pen import PenConfig
from .pen import PenTool
from .runner import InteractiveRunner
from .runner import PipelineRunner


def _vectorize_lines(lines):
    """
    Converts Shapely LineStrings into highly efficient numpy arrays 
    ready for direct injection into Vispy visuals.
    """
    if not lines:
        return np.empty((0, 2), dtype=np.float32), np.empty((0, 2), dtype=np.uint32)

    # Extract all coordinates into a list of arrays
    coords_list = [np.array(line.coords, dtype=np.float32) for line in lines]
    stacked_pos = np.vstack(coords_list)

    # Vectorize the connection index building
    lengths = [len(c) for c in coords_list]
    connect_blocks = []
    current_idx = 0

    for n in lengths:
        if n > 1:
            # Rapidly generate [0,1], [1,2], [2,3] index pairs for the GPU
            starts = np.arange(current_idx,
                               current_idx + n - 1,
                               dtype=np.uint32)
            ends = starts + 1
            connect_blocks.append(np.column_stack((starts, ends)))
        current_idx += n

    final_connect = np.vstack(connect_blocks) if connect_blocks else np.empty(
        (0, 2), dtype=np.uint32)
    return stacked_pos, final_connect


class PendragonEngine:

    def __init__(self,
                 recipe: list,
                 boundary: Optional[Polygon] = None,
                 interactive: bool = False):
        """
        Initializes the engine with a recipe and an optional boundary.
        """
        self.recipe = recipe
        self.boundary = boundary or Polygon([(0, 0), (200, 0), (200, 200),
                                             (0, 200), (0, 0)])
        self.interactive = interactive

        initial_state = PipelineState(boundary=self.boundary,
                                      operation_name="base_geometry")

        if self.interactive:
            self.runner = InteractiveRunner(initial_state)
        else:
            self.runner = PipelineRunner(initial_state)

    def load_recipe(self, new_recipe: list) -> bool:
        """
        Resets the engine's runner and loads a new recipe dynamically.
        """
        self.recipe = new_recipe

        # 1. Re-initialize the base state
        initial_state = PipelineState(boundary=self.boundary,
                                      operation_name="base_geometry")

        # 2. Create a brand new runner to clear the old history and operations
        if self.interactive:
            self.runner = InteractiveRunner(initial_state)
        else:
            self.runner = PipelineRunner(initial_state)

        # 3. Rebuild the pipeline with the new recipe
        success = self.build_pipeline()

        if success:
            logger.info("Successfully loaded and built new pipeline recipe.")
        else:
            logger.error("Failed to build pipeline from new recipe.")

        return success

    def build_pipeline(self) -> bool:
        """
        Validates the recipe and queues up the configured plugin operations.
        Returns True if successful, False if validation fails.
        """
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
                    logger.success(
                        f"Successfully validated config for {op_name}")
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

    def export_gcode(self,
                     lines: List[LineString],
                     output_path: str,
                     pen_config: Optional[PenConfig] = None):
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

    @staticmethod
    def run_pipeline_process(recipe,
                             boundary,
                             progress_queue,
                             prior_history=None,
                             start_index=0):
        """
        Executes the pipeline in a background process, pushing intermediate states.
        Pushes the final history array to the queue at the end.
        """
        load_plugins()

        if prior_history:
            history = prior_history
        else:
            initial_state = PipelineState(boundary=boundary,
                                          operation_name="base_geometry")
            history = [initial_state]

        operations = []
        for step in recipe:
            op_name = step.get("operation")
            op_info = OPERATION_REGISTRY.get(op_name)
            if not op_info:
                continue

            PluginClass, ConfigClass = op_info["class"], op_info["config"]
            config = ConfigClass(
                **step.get("settings", {})) if ConfigClass else None
            operations.append(PluginClass(config=config))

        empty_context = PipelineContext()
        total_ops = len(operations)

        if start_index == 0:
            stacked_pos, final_connect = _vectorize_lines(history[-1].lines)
            progress_queue.put({
                "type": "FRAME",
                "step": 0,
                "total": total_ops,
                "op_name": history[-1].operation_name,
                "line_count": len(history[-1].lines),
                "pos": stacked_pos,
                "connect": final_connect
            })

        for i in range(start_index, total_ops):
            op = operations[i]
            current_state = history[-1]

            sig = inspect.signature(op.process)
            if 'context' in sig.parameters:
                new_state = op.process(current_state, context=empty_context)
            else:
                new_state = op.process(current_state)

            history.append(new_state)

            # Offload the heavy coordinate extraction to this background process
            stacked_pos, final_connect = _vectorize_lines(new_state.lines)

            progress_queue.put({
                "type": "FRAME",
                "step": i + 1,
                "total": total_ops,
                "op_name": new_state.operation_name,
                "line_count": len(new_state.lines),
                "pos": stacked_pos,
                "connect": final_connect
            })

        progress_queue.put({"type": "DONE", "history": history})
