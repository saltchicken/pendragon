import inspect

from loguru import logger

from pendragon.core.discovery import load_plugins
from pendragon.core.models import PipelineContext
from pendragon.core.models import PipelineState
from pendragon.core.registry import OPERATION_REGISTRY


def run_pipeline_streaming(recipe, boundary, progress_queue):
    """
    Executes the pipeline in a background process, pushing intermediate states.
    Pushes the final history array to the queue at the end.
    """
    load_plugins()

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

    progress_queue.put({
        "type": "FRAME",
        "step": 0,
        "total": total_ops,
        "op_name": history[-1].operation_name,
        "lines": history[-1].lines
    })

    for i, op in enumerate(operations):
        current_state = history[-1]
        sig = inspect.signature(op.process)

        if 'context' in sig.parameters:
            new_state = op.process(current_state, context=empty_context)
        else:
            new_state = op.process(current_state)

        history.append(new_state)

        progress_queue.put({
            "type": "FRAME",
            "step": i + 1,
            "total": total_ops,
            "op_name": new_state.operation_name,
            "lines": new_state.lines
        })

    # Push the final result through the queue instead of returning it
    progress_queue.put({"type": "DONE", "history": history})
