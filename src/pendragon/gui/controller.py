from enum import auto
from enum import Enum

from loguru import logger
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtCore import QObject
from PyQt5.QtCore import QTimer
import yaml

from pendragon.engine import PendragonEngine
from pendragon.export import export_gcode
from pendragon.gui.worker import PipelineStreamingThread


class ControllerState(Enum):
    """Defines the mutually exclusive states of the pipeline runner."""
    IDLE = auto()
    COMPUTING = auto()
    CANCELLING = auto()


class PipelineController(QObject):
    computation_started = pyqtSignal(int)
    computation_finished = pyqtSignal(object)
    computation_error = pyqtSignal(str)
    computation_cancelled = pyqtSignal()
    step_streamed = pyqtSignal(dict)
    ui_rebuild_requested = pyqtSignal()

    def __init__(self, engine: PendragonEngine):
        super().__init__()
        self.engine = engine
        self.worker_thread = None

        # State Machine Tracking
        self._state = ControllerState.IDLE
        self._computation_queued = False
        self._pending_op_index = None

        self.debounce_timer = QTimer()
        self.debounce_timer.setSingleShot(True)
        self.debounce_timer.setInterval(300)
        self.debounce_timer.timeout.connect(self._execute_recalculation)

    # --- Law of Demeter Accessors ---
    def get_operation_count(self) -> int:
        return self.engine.get_operation_count()

    def get_operation(self, index: int):
        return self.engine.get_operation(index)

    def get_available_operations(self) -> list[str]:
        return self.engine.registry.get_operation_names()

    def get_operation_info(self, name: str):
        return self.engine.registry.get(name)

    # --------------------------------

    def trigger_computation(self):
        # State Machine: Route or queue the execution request
        if self._state != ControllerState.IDLE:
            self._computation_queued = True
            return

        self._state = ControllerState.COMPUTING
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
        # State Machine: Only cancel if we are actively computing
        if self._state == ControllerState.COMPUTING and self.worker_thread and self.worker_thread.isRunning(
        ):
            self._state = ControllerState.CANCELLING
            self.worker_thread.cancel()

    def update_parameter(self, op_index: int, field_name: str, new_value):
        operation = self.engine.get_operation(op_index)
        if not operation or not operation.config:
            return

        setattr(operation.config, field_name, new_value)
        self.engine.invalidate_from(op_index)

        if self._pending_op_index is None:
            self._pending_op_index = op_index
        else:
            self._pending_op_index = min(self._pending_op_index, op_index)
        self.debounce_timer.start()

    def update_nested_parameter(self, op_index: int, parent_dict_name: str,
                                sub_field_name: str, new_value):
        operation = self.engine.get_operation(op_index)
        if not operation or not operation.config:
            return

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
        for op in self.engine.get_operations():
            op_name = getattr(op.__class__, '_plugin_name', None)
            if not op_name:
                continue

            step = {"operation": op_name}
            if op.config:
                step["settings"] = op.config.model_dump()
            current_recipe.append(step)
        return current_recipe

    def reload_pipeline(self, new_recipe: list, valid_history_idx: int = 0):
        success = self.engine.update_recipe(new_recipe)
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
        final_lines = self.engine.get_final_lines()
        export_gcode(final_lines, file_path)

    # --- Internal Callbacks ---
    def _execute_recalculation(self):
        if self._pending_op_index is not None:
            self.trigger_computation()

    def _on_calculation_finished(self, final_store):
        # State Machine: Reset to IDLE, Window handles queue check via finalize_state
        self._state = ControllerState.IDLE
        self.engine.store = final_store
        self.computation_finished.emit(final_store)

    def _on_calculation_error(self, error_msg):
        # State Machine: Reset to IDLE, clear queue on hard errors
        self._state = ControllerState.IDLE
        self._computation_queued = False
        logger.error(f"Background pipeline failed: {error_msg}")
        self.computation_error.emit(error_msg)

    def _on_calculation_cancelled(self):
        # State Machine: Reset to IDLE, instantly process queue if modifications happened during cancel
        self._state = ControllerState.IDLE
        logger.warning("Pipeline calculation cancelled by user.")
        self.computation_cancelled.emit()

        if self._computation_queued:
            self._computation_queued = False
            self.trigger_computation()

    def finalize_state(self):
        # State Machine: Called by window when visualization is fully ready
        if self._computation_queued:
            self._computation_queued = False
            self.trigger_computation()

    def shutdown(self):
        if self._state != ControllerState.IDLE and self.worker_thread and self.worker_thread.isRunning(
        ):
            self._state = ControllerState.CANCELLING
            self.worker_thread.cancel()
            self.worker_thread.quit()
            self.worker_thread.wait(1000)
