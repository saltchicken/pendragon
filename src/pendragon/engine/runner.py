import multiprocessing
import queue as standard_queue

from .core import PendragonEngine
from .discovery import load_plugins

def _worker_process(recipe, boundary, out_queue, prior_history, start_index, formatter):
    load_plugins()
    engine = PendragonEngine(recipe=recipe, boundary=boundary)
    engine.build_pipeline()
    
    if prior_history:
        engine.history = prior_history

    total_ops = len(engine.operations)

    try:
        # Prime the pump for the initial state if starting fresh
        if start_index == 0 and engine.history:
            state = engine.history[0]
            data = formatter(state) if formatter else state
            out_queue.put({"type": "FRAME", "step": 0, "total": total_ops, "data": data})

        # Intelligently compute missing steps
        for new_state in engine.compute_to_generator(total_ops):
            step_idx = len(engine.history) - 1
            data = formatter(new_state) if formatter else new_state
            
            out_queue.put({
                "type": "FRAME",
                "step": step_idx,
                "total": total_ops,
                "data": data
            })

        out_queue.put({"type": "DONE", "history": engine.history})
    except Exception as e:
        out_queue.put({"type": "ERROR", "message": str(e)})

class PipelineRunner:
    """A clean, boilerplate-free wrapper for running the pipeline in the background."""
    
    def __init__(self, recipe, boundary, prior_history=None, start_index=0, formatter=None):
        self.queue = multiprocessing.Queue()
        self.process = multiprocessing.Process(
            target=_worker_process,
            args=(recipe, boundary, self.queue, prior_history, start_index, formatter)
        )

    def start(self):
        self.process.start()

    def iter_events(self, timeout=0.01):
        """Yields events from the background process seamlessly."""
        while self.process.is_alive() or not self.queue.empty():
            try:
                yield self.queue.get(timeout=timeout)
            except standard_queue.Empty:
                continue

    def terminate(self):
        """Hard kills the background process."""
        if self.process.is_alive():
            self.process.terminate()
            self.process.join()
