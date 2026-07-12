import multiprocessing
import queue as standard_queue
import time

import numpy as np
from PyQt5.QtCore import pyqtSignal, QThread

from pendragon.engine import PendragonEngine
from pendragon.engine.discovery import load_plugins


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
            starts = np.arange(current_idx, current_idx + n - 1, dtype=np.uint32)
            ends = starts + 1
            connect_blocks.append(np.column_stack((starts, ends)))
        current_idx += n

    final_connect = np.vstack(connect_blocks) if connect_blocks else np.empty((0, 2), dtype=np.uint32)
    return stacked_pos, final_connect


def run_pipeline_process(recipe, boundary, progress_queue, prior_history=None, start_index=0):
    """
    Executes the pipeline in a background process using the engine's native generator.
    """
    load_plugins()

    # 1. Spin up a headless engine inside this background process
    engine = PendragonEngine(recipe=recipe, boundary=boundary)
    engine.build_pipeline()

    # 2. Prime the engine's cache with our valid history so it skips recalculating
    if prior_history:
        engine.history = prior_history

    total_ops = len(engine.operations)

    # 3. Stream the 0th frame if we are starting completely fresh
    if start_index == 0 and engine.history:
        stacked_pos, final_connect = _vectorize_lines(engine.history[0].lines)
        progress_queue.put({
            "type": "FRAME",
            "step": 0,
            "total": total_ops,
            "op_name": engine.history[0].operation_name,
            "line_count": len(engine.history[0].lines),
            "pos": stacked_pos,
            "connect": final_connect
        })

    # 4. Let the generator intelligently compute ONLY the missing steps
    for new_state in engine.compute_to_generator(total_ops):
        # We use len(engine.history) - 1 because the generator already appended it
        step_idx = len(engine.history) - 1 
        
        # Offload the heavy coordinate extraction to this background process
        stacked_pos, final_connect = _vectorize_lines(new_state.lines)

        progress_queue.put({
            "type": "FRAME",
            "step": step_idx,
            "total": total_ops,
            "op_name": new_state.operation_name,
            "line_count": len(new_state.lines),
            "pos": stacked_pos,
            "connect": final_connect
        })

    progress_queue.put({"type": "DONE", "history": engine.history})


class PipelineStreamingThread(QThread):
    step_completed = pyqtSignal(dict)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self,
                 recipe,
                 boundary,
                 prior_history=None,
                 start_index=0,
                 target_fps=30):
        super().__init__()
        self.recipe = recipe
        self.boundary = boundary
        self.prior_history = prior_history or []
        self.start_index = start_index
        self.frame_time = 1.0 / target_fps
        self.process = None

    def cancel(self):
        """Hard kills the background process immediately."""
        if self.process and self.process.is_alive():
            self.process.terminate()
            self.process.join()
            self.cancelled.emit()

    def run(self):
        try:
            self.progress_queue = multiprocessing.Queue()
            self.process = multiprocessing.Process(
                target=run_pipeline_process,
                args=(self.recipe, self.boundary, self.progress_queue,
                      self.prior_history, self.start_index))
            self.process.start()

            last_emit_time = 0.0
            pending_data = None

            # Loop while the process runs OR there is still data to flush
            while self.process.is_alive() or not self.progress_queue.empty():
                try:
                    data = self.progress_queue.get(timeout=0.01)

                    if data["type"] == "DONE":
                        if pending_data is not None:
                            self.step_completed.emit(pending_data)
                        self.finished.emit(data["history"])
                        return  # Clean exit

                    if data["type"] == "FRAME":
                        pending_data = data
                        current_time = time.time()
                        if current_time - last_emit_time >= self.frame_time:
                            self.step_completed.emit(pending_data)
                            last_emit_time = current_time
                            pending_data = None

                except standard_queue.Empty:
                    if pending_data is not None:
                        self.step_completed.emit(pending_data)
                        last_emit_time = time.time()
                        pending_data = None
                    continue

        except Exception as e:
            self.error.emit(str(e))
