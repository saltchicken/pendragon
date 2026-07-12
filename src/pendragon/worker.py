import inspect

from loguru import logger
import numpy as np  # <-- Add this import

from pendragon.core.discovery import load_plugins
from pendragon.core.models import PipelineContext
from pendragon.core.models import PipelineState
from pendragon.core.registry import OPERATION_REGISTRY


def _vectorize_lines(lines):
    """
    Converts Shapely LineStrings into highly efficient numpy arrays 
    ready for direct injection into Vispy visuals.
    """
    if not lines:
        return np.empty((0, 2), dtype=np.float32), np.empty((0, 2),
                                                            dtype=np.uint32)

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


def run_pipeline_streaming(recipe,
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
