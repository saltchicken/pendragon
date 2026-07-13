from loguru import logger
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtCore import QObject
from PyQt5.QtCore import QTimer
import yaml

from pendragon.engine import PendragonEngine
from pendragon.engine.registry import OPERATION_REGISTRY
from pendragon.export import export_gcode
from pendragon.gui.worker import PipelineStreamingThread


class PipelineController(QObject):
    """ViewModel/Controller: Manages engine state, worker threads, and recipe logic."""

    # Signals to update the UI
    computation_started = pyqtSignal(int)  # Emits start index
    computation_finished = pyqtSignal(object)  # Emits new store
    computation_error = pyqtSignal(str)
    computation_cancelled = pyqtSignal()
    step_streamed = pyqtSignal(dict)

    ui_rebuild_requested = pyqtSignal()

    def __init__(self, engine: PendragonEngine):
        super().__init__()
        self.engine = engine

        self.worker_thread = None
        self._is_computing = False
        self._computation_queued = False
        self._pending_op_index = None

        self.debounce_timer = QTimer()
        self.debounce_timer.setSingleShot(True)
        self.debounce_timer.setInterval(300)
        self.debounce_timer.timeout.connect(self._execute_recalculation)

    def trigger_computation(self):
        """Centralized queue manager. Prevents overlapping threads and freezes."""
        if self._is_computing:
            self._computation_queued = True
            return

        self._is_computing = True
        start_index = self._pending_op_index if self._pending_op_index is not None else 0
        self._pending_op_index = None

        self.computation_started.emit(start_index)

        current_recipe = self.get_current_recipe()
        prior_store = self.engine.store

        self.worker_thread = PipelineStreamingThread(current_recipe,
                                                     self.engine.boundary,
                                                     prior_history=prior_store,
                                                     start_index=start_index)

        self.worker_thread.step_completed.connect(self.step_streamed.emit)
        self.worker_thread.finished.connect(self._on_calculation_finished)
        self.worker_thread.error.connect(self._on_calculation_error)
        self.worker_thread.cancelled.connect(self._on_calculation_cancelled)

        self.worker_thread.start()

    def cancel_computation(self):
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.cancel()

    def update_parameter(self, op_index: int, field_name: str, new_value):
        operation = self.engine.operations[op_index]
        setattr(operation.config, field_name, new_value)

        self.engine.invalidate_from(op_index)

        if self._pending_op_index is None:
            self._pending_op_index = op_index
        else:
            self._pending_op_index = min(self._pending_op_index, op_index)
        self.debounce_timer.start()

    def update_nested_parameter(self, op_index: int, parent_dict_name: str,
                                sub_field_name: str, new_value):
        operation = self.engine.operations[op_index]
        if hasattr(operation.config, parent_dict_name):
            target_dict = getattr(operation.config, parent_dict_name)
            if isinstance(target_dict, dict):
                target_dict[sub_field_name] = new_value

                self.engine.invalidate_from(op_index)

                if self._pending_op_index is None:
                    self._pending_op_index = op_index
                else:
                    self._pending_op_index = min(self._pending_op_index,
                                                 op_index)
                self.debounce_timer.start()

    def get_current_recipe(self) -> list:
        current_recipe = []
        for op in self.engine.operations:
            op_name = next((name for name, info in OPERATION_REGISTRY.items()
                            if isinstance(op, info["class"])), None)
            if not op_name:
                continue

            step = {"operation": op_name}
            if op.config:
                step["settings"] = op.config.model_dump()
            current_recipe.append(step)
        return current_recipe

    def reload_pipeline(self, new_recipe: list, valid_history_idx: int = 0):
        """Overrides the current recipe and asks the engine to validate/build ops."""
        self.engine.recipe = new_recipe
        success = self.engine.build_pipeline()

        if success:
            self.engine.invalidate_from(valid_history_idx)
            self._pending_op_index = valid_history_idx

            self.ui_rebuild_requested.emit()
            self.trigger_computation()
        else:
            logger.error("Failed to reload pipeline with new recipe.")

    def add_operation(self, insert_idx: int, op_name: str):
        if not op_name:
            return
        recipe = self.get_current_recipe()
        recipe.insert(insert_idx, {"operation": op_name, "settings": {}})
        self.reload_pipeline(recipe, valid_history_idx=insert_idx)

    def remove_operation(self, remove_idx: int):
        recipe = self.get_current_recipe()
        if 0 <= remove_idx < len(recipe):
            recipe.pop(remove_idx)
            self.reload_pipeline(recipe, valid_history_idx=remove_idx)

    def load_recipe_from_file(self, file_path: str):
        try:
            with open(file_path, 'r') as f:
                new_recipe = yaml.safe_load(f)

            if not isinstance(new_recipe, list):
                logger.error(
                    "Invalid recipe format: must be a list of operations.")
                return False

            success = self.engine.load_recipe(new_recipe)
            if success:
                self.ui_rebuild_requested.emit()
                self.trigger_computation()
                return True
        except Exception as e:
            logger.error(f"Error loading recipe from {file_path}: {e}")
        return False

    def save_recipe_to_file(self, file_path: str):
        current_recipe = self.get_current_recipe()
        try:
            with open(file_path, 'w') as f:
                yaml.safe_dump(current_recipe,
                               f,
                               sort_keys=False,
                               default_flow_style=False)
            logger.success(f"Recipe successfully saved to {file_path}")
        except Exception as e:
            logger.error(f"Failed to save recipe: {e}")

    def export_gcode_to_file(self, file_path: str):
        final_lines = self.engine.store.get_last().lines
        export_gcode(final_lines, file_path)

    # --- Internal Callbacks ---
    def _execute_recalculation(self):
        if self._pending_op_index is not None:
            self.trigger_computation()

    def _on_calculation_finished(self, final_store):
        self._is_computing = False
        self.engine.store = final_store
        self.computation_finished.emit(final_store)

    def _on_calculation_error(self, error_msg):
        self._is_computing = False
        logger.error(f"Background pipeline failed: {error_msg}")
        self.computation_error.emit(error_msg)

    def _on_calculation_cancelled(self):
        self._is_computing = False
        self._computation_queued = False
        logger.warning("Pipeline calculation cancelled by user.")
        self.computation_cancelled.emit()

    def finalize_state(self):
        """Checks if a queued computation needs to start after the previous one finishes."""
        if self._computation_queued:
            self._computation_queued = False
            self.trigger_computation()

    def shutdown(self):
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.cancel()
            self.worker_thread.quit()
            self.worker_thread.wait(1000)
