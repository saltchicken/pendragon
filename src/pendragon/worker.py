import inspect

from loguru import logger

from pendragon.core.discovery import load_plugins
from pendragon.core.models import PipelineContext
from pendragon.core.models import PipelineState
from pendragon.core.registry import OPERATION_REGISTRY


def run_pipeline_streaming(recipe, boundary, progress_queue):
    """
    Executes the pipeline in a background process, pushing intermediate 
    geometry states to the progress_queue, and returns the full history.
    """
    # Ensure plugins are loaded in the new process context
    load_plugins()

    initial_state = PipelineState(boundary=boundary, operation_name="base_geometry")
    history = [initial_state]
    operations = []

    # Reconstruct operations from the serialized recipe
    for step in recipe:
        op_name = step.get("operation")
        op_info = OPERATION_REGISTRY.get(op_name)
        if not op_info:
            continue
            
        PluginClass = op_info["class"]
        ConfigClass = op_info["config"]
        config = ConfigClass(**step.get("settings", {})) if ConfigClass else None
        operations.append(PluginClass(config=config))

    empty_context = PipelineContext()
    total_ops = len(operations)

    # 1. Push the initial state
    progress_queue.put({
        "step": 0,
        "total": total_ops,
        "op_name": history[-1].operation_name,
        "lines": history[-1].lines
    })

    # 2. Execute sequentially and stream
    for i, op in enumerate(operations):
        current_state = history[-1]
        sig = inspect.signature(op.process)
        
        if 'context' in sig.parameters:
            new_state = op.process(current_state, context=empty_context)
        else:
            new_state = op.process(current_state)
            
        history.append(new_state)

        progress_queue.put({
            "step": i + 1,
            "total": total_ops,
            "op_name": new_state.operation_name,
            "lines": new_state.lines
        })

    # 3. Signal completion
    progress_queue.put("DONE")
    
    # Return the full history to sync back with the main GUI's InteractiveRunner
    return history
