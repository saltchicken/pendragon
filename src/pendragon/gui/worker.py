import multiprocessing
import queue as standard_queue
import time

from PyQt5.QtCore import pyqtSignal, QThread
from pendragon.engine import PendragonEngine


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
                target=PendragonEngine.run_pipeline_process,  # <-- Point to the static method
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

