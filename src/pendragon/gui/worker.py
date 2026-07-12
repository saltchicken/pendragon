import time
import numpy as np
from PyQt5.QtCore import pyqtSignal, QThread

from pendragon.engine import PipelineRunner

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

def vispy_formatter(state):
    """Transforms a PipelineState into a GUI-ready dictionary inside the background process."""
    pos, connect = _vectorize_lines(state.lines)
    return {
        "op_name": state.operation_name,
        "line_count": len(state.lines),
        "pos": pos,
        "connect": connect
    }

class PipelineStreamingThread(QThread):
    step_completed = pyqtSignal(dict)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, recipe, boundary, prior_history=None, start_index=0, target_fps=30):
        super().__init__()
        self.frame_time = 1.0 / target_fps
        self._is_cancelled = False
        
        # The engine handles all the multiprocessing boilerplate now!
        self.runner = PipelineRunner(
            recipe=recipe, 
            boundary=boundary, 
            prior_history=prior_history, 
            start_index=start_index, 
            formatter=vispy_formatter # Pass the heavy lifting function
        )

    def cancel(self):
        self._is_cancelled = True
        self.runner.terminate()
        self.cancelled.emit()

    def run(self):
        self.runner.start()
        last_emit_time = 0.0
        pending_data = None

        # Clean, pythonic iteration over the background events
        for event in self.runner.iter_events():
            if self._is_cancelled:
                break

            if event["type"] == "ERROR":
                self.error.emit(event["message"])
                return

            if event["type"] == "DONE":
                if pending_data:
                    # Flatten the data dict for the GUI signature
                    self.step_completed.emit({"step": pending_data["step"], "total": pending_data["total"], **pending_data["data"]})
                self.finished.emit(event["history"])
                return

            if event["type"] == "FRAME":
                pending_data = event
                current_time = time.time()
                
                if current_time - last_emit_time >= self.frame_time:
                    # Flatten the data dict for the GUI signature
                    self.step_completed.emit({"step": pending_data["step"], "total": pending_data["total"], **pending_data["data"]})
                    last_emit_time = current_time
                    pending_data = None
