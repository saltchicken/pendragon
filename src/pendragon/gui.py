import multiprocessing
import queue as standard_queue
import time
from typing import Any, Dict, get_args, get_origin, List, Literal

from loguru import logger
import numpy as np
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtCore import Qt
from PyQt5.QtCore import QThread
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication
from PyQt5.QtWidgets import QCheckBox
from PyQt5.QtWidgets import QComboBox
from PyQt5.QtWidgets import QDoubleSpinBox
from PyQt5.QtWidgets import QFileDialog
from PyQt5.QtWidgets import QFormLayout
from PyQt5.QtWidgets import QGroupBox
from PyQt5.QtWidgets import QHBoxLayout
from PyQt5.QtWidgets import QLabel
from PyQt5.QtWidgets import QLineEdit
from PyQt5.QtWidgets import QMainWindow
from PyQt5.QtWidgets import QProgressBar
from PyQt5.QtWidgets import QPushButton
from PyQt5.QtWidgets import QSlider
from PyQt5.QtWidgets import QSpinBox
from PyQt5.QtWidgets import QVBoxLayout
from PyQt5.QtWidgets import QWidget
from shapely.geometry import MultiPolygon
from shapely.geometry import Polygon
from vispy import scene
import yaml

from pendragon.core.models import PipelineState
from pendragon.core.registry import OPERATION_REGISTRY
from pendragon.worker import run_pipeline_streaming

DARK_THEME_STYLESHEET = """
QWidget {
    background-color: #1e1e1e;
    color: #cccccc;
    font-size: 13px;
}
QLabel {
    color: #cccccc;
}
QGroupBox {
    font-weight: bold;
    border: 1px solid #333333;
    border-radius: 5px;
    margin-top: 1ex;
    padding-top: 10px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 3px;
}
QSlider::groove:horizontal {
    border: 1px solid #333333;
    height: 6px;
    background: #333333;
    margin: 2px 0;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #007acc;
    border: 1px solid #005c99;
    width: 14px;
    margin: -4px 0;
    border-radius: 7px;
}
QSlider::handle:horizontal:hover {
    background: #0098ff;
}
QSlider::sub-page:horizontal {
    background: #007acc;
    border-radius: 3px;
}
QPushButton {
    background-color: #333333;
    border: 1px solid #555555;
    border-radius: 4px;
    padding: 6px;
    color: #cccccc;
}
QPushButton:hover {
    background-color: #444444;
}
QPushButton:pressed {
    background-color: #222222;
}
QPushButton:disabled {
    background-color: #1a1a1a;
    color: #555555;
    border: 1px solid #333333;
}
QProgressBar {
    border: 1px solid #555555;
    border-radius: 4px;
    text-align: center;
    background-color: #333333;
}
QProgressBar::chunk {
    background-color: #007acc;
    width: 10px;
}
"""


class PipelineStreamingThread(QThread):
    step_completed = pyqtSignal(dict)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, recipe, boundary, prior_history=None, start_index=0, target_fps=30):
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
                target=run_pipeline_streaming,
                args=(self.recipe, self.boundary, self.progress_queue, self.prior_history, self.start_index))
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


class LiveEditorWindow(QMainWindow):

    def __init__(self, engine):
        super().__init__()
        self.setWindowTitle("Pendragon")
        self.engine = engine

        self.setStyleSheet(DARK_THEME_STYLESHEET)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        self.viewer = PipelineViewer(self.engine)
        main_layout.addWidget(self.viewer.native, stretch=3)

        self.control_panel = QWidget()
        self.control_layout = QVBoxLayout(self.control_panel)
        self.control_layout.setAlignment(Qt.AlignTop)
        main_layout.addWidget(self.control_panel, stretch=1)

        self.stats_group = QGroupBox("Pipeline Statistics")
        self.stats_layout = QFormLayout(self.stats_group)

        self.step_label = QLabel("-")
        self.op_label = QLabel("-")
        self.lines_label = QLabel("-")
        self.vertices_label = QLabel("-")

        self.stats_layout.addRow("Step:", self.step_label)
        self.stats_layout.addRow("Operation:", self.op_label)
        self.stats_layout.addRow("Lines:", self.lines_label)
        self.stats_layout.addRow("Vertices:", self.vertices_label)

        self.control_layout.addWidget(self.stats_group)

        # --- PROGRESS & CANCEL UI ---
        self.progress_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setStyleSheet(
            "background-color: #8b0000; font-weight: bold;")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_computation)

        self.progress_layout.addWidget(self.progress_bar)
        self.progress_layout.addWidget(self.btn_cancel)
        self.control_layout.addLayout(self.progress_layout)
        # --------------------------------

        self.show_vertices_checkbox = QCheckBox("Show Vertices")
        self.show_vertices_checkbox.setChecked(False)
        self.show_vertices_checkbox.toggled.connect(self._on_vertices_toggled)
        self.control_layout.addWidget(self.show_vertices_checkbox)

        self.final_view_checkbox = QCheckBox("Show Final View")
        self.final_view_checkbox.setChecked(False)
        self.final_view_checkbox.toggled.connect(self._on_view_mode_toggled)
        self.control_layout.addWidget(self.final_view_checkbox)

        self.nav_layout = QHBoxLayout()
        self.btn_prev = QPushButton("Previous Step")
        self.btn_next = QPushButton("Next Step")

        self.btn_prev.clicked.connect(self.viewer.step_backward)
        self.btn_next.clicked.connect(self.viewer.step_forward)

        self.nav_layout.addWidget(self.btn_prev)
        self.nav_layout.addWidget(self.btn_next)
        self.control_layout.addLayout(self.nav_layout)

        self.action_layout = QHBoxLayout()
        self.btn_load_recipe = QPushButton("Load Recipe")
        self.btn_export_gcode = QPushButton("Export G-Code")
        self.btn_save_recipe = QPushButton("Save Recipe")

        self.btn_load_recipe.clicked.connect(self._load_live_recipe)
        self.btn_export_gcode.clicked.connect(self._export_live_gcode)
        self.btn_save_recipe.clicked.connect(self._save_live_recipe)

        self.action_layout.addWidget(self.btn_load_recipe)
        self.action_layout.addWidget(self.btn_save_recipe)
        self.action_layout.addWidget(self.btn_export_gcode)
        self.control_layout.addLayout(self.action_layout)

        self.edit_layout = QHBoxLayout()

        self.op_selector = QComboBox()
        self.op_selector.addItems(sorted(OPERATION_REGISTRY.keys()))

        self.btn_add_op = QPushButton("Add Step")
        self.btn_remove_op = QPushButton("Remove Step")

        self.btn_add_op.clicked.connect(self._add_operation)
        self.btn_remove_op.clicked.connect(self._remove_operation)

        self.edit_layout.addWidget(self.op_selector, stretch=2)
        self.edit_layout.addWidget(self.btn_add_op, stretch=1)
        self.edit_layout.addWidget(self.btn_remove_op, stretch=1)

        self.control_layout.addLayout(self.edit_layout)

        self.dynamic_form_widget = QWidget()
        self.form_layout = QFormLayout(self.dynamic_form_widget)
        self.control_layout.addWidget(self.dynamic_form_widget)

        self.viewer.on_step_changed = self.build_ui_for_current_step
        self.viewer.on_close_requested = self.close
        self.viewer.on_stats_updated = self.update_stats_ui

        self.debounce_timer = QTimer()
        self.debounce_timer.setSingleShot(True)
        self.debounce_timer.setInterval(300)
        self.debounce_timer.timeout.connect(self._execute_recalculation)
        self._pending_op_index = None

        # Thread and Queuing State
        self.worker_thread = None
        self._is_computing = False
        self._computation_queued = False

        self.build_ui_for_current_step()
        self._trigger_computation()

    def _trigger_computation(self):
        """Centralized queue manager. Prevents overlapping threads and freezes."""
        if self._is_computing:
            self._computation_queued = True
            return

        self._is_computing = True

        # 1. Determine where to start
        start_index = self._pending_op_index if self._pending_op_index is not None else 0
        self._pending_op_index = None  # Clear it immediately so edits while computing are tracked

        # 2. Grab history up to the point of change (start_index + 1 includes the base geometry at index 0)
        prior_history = None
        if start_index > 0 and len(self.engine.runner.history) > start_index:
            prior_history = self.engine.runner.history[:start_index + 1]
        else:
            start_index = 0  # Fallback to scratch if history doesn't exist

        # Reset UI for computation
        self.btn_cancel.setEnabled(True)
        self.btn_cancel.setStyleSheet("background-color: #ff4444; color: white; font-weight: bold;")
        
        # Visually jump the progress bar to the starting step
        self.progress_bar.setValue(start_index) 
        self.progress_bar.setFormat("Initializing...")

        current_recipe = self._get_current_recipe()

        # 3. Fire up the thread with the partial history
        self.worker_thread = PipelineStreamingThread(
            current_recipe,
            self.engine.boundary,
            prior_history=prior_history,
            start_index=start_index
        )
        self.worker_thread.step_completed.connect(self._on_step_streamed)
        self.worker_thread.finished.connect(self._on_calculation_finished)
        self.worker_thread.error.connect(self._on_calculation_error)
        self.worker_thread.cancelled.connect(self._on_calculation_cancelled)

        self.worker_thread.start()

    def _cancel_computation(self):
        """Triggered by the user clicking the red Cancel button."""
        if self.worker_thread and self.worker_thread.isRunning():
            self.progress_bar.setFormat("Cancelling...")
            self.btn_cancel.setEnabled(False)
            self.worker_thread.cancel()

    def _on_calculation_cancelled(self):
        self._is_computing = False
        self._computation_queued = False  # Flush queue on abort
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setStyleSheet(
            "background-color: #8b0000; color: #aaaaaa; font-weight: bold;")
        self.progress_bar.setFormat("Computation Aborted")
        logger.warning("Pipeline calculation cancelled by user.")

    def _on_view_mode_toggled(self, checked):
        self.viewer.show_final_view = checked
        self.viewer.update_view()

    def _on_vertices_toggled(self, checked):
        self.viewer.show_vertices = checked
        self.viewer.update_view()

    def update_stats_ui(self, step, total_ops, op_name, lines, vertices,
                        final_view):
        step_text = f"{step} / {total_ops}"
        if final_view:
            step_text += " (FINAL VIEW)"

        self.step_label.setText(step_text)
        self.op_label.setText(str(op_name))
        self.lines_label.setText(str(lines))
        self.vertices_label.setText(str(vertices))

    def build_ui_for_current_step(self):
        self.control_layout.removeWidget(self.dynamic_form_widget)
        self.dynamic_form_widget.deleteLater()

        self.dynamic_form_widget = QWidget()
        self.form_layout = QFormLayout(self.dynamic_form_widget)
        self.control_layout.addWidget(self.dynamic_form_widget)

        op_index = self.viewer.current_step - 1
        if op_index < 0 or op_index >= len(self.engine.runner.operations):
            self.form_layout.addRow(
                QLabel("No configurable parameters for this state."))
            return

        operation = self.engine.runner.operations[op_index]
        if not operation.config:
            self.form_layout.addRow(
                QLabel(f"{operation.__class__.__name__} has no config."))
            return

        self.form_layout.addRow(
            QLabel(f"<b>Editing: {operation.__class__.__name__}</b>"))

        for field_name, field_info in operation.config.model_fields.items():
            current_value = getattr(operation.config, field_name)
            origin = get_origin(field_info.annotation)

            if field_info.annotation == float:
                container = QWidget()
                h_layout = QHBoxLayout(container)
                h_layout.setContentsMargins(0, 0, 0, 0)

                val_min = None
                val_max = None
                for m in field_info.metadata:
                    if hasattr(m, 'ge'):
                        val_min = m.ge
                    if hasattr(m, 'le'):
                        val_max = m.le

                if val_min is not None and val_max is not None:
                    slider = QSlider(Qt.Horizontal)
                    slider.setMinimum(0)
                    slider.setMaximum(100)

                    current_percent = int(
                        ((current_value - val_min) / (val_max - val_min)) * 100)
                    slider.setValue(current_percent)

                    value_label = QLabel(f"{current_value:.2f}")
                    value_label.setMinimumWidth(35)
                    value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

                    def update_bounded_float(val,
                                             fname=field_name,
                                             idx=op_index,
                                             lbl=value_label,
                                             v_min=val_min,
                                             v_max=val_max):
                        real_val = v_min + (val / 100.0) * (v_max - v_min)
                        lbl.setText(f"{real_val:.2f}")
                        self.update_parameter(idx, fname, real_val)

                    slider.valueChanged.connect(update_bounded_float)
                    h_layout.addWidget(slider)
                    h_layout.addWidget(value_label)

                else:
                    spin_box = QDoubleSpinBox()
                    spin_box.setRange(-10000.0, 10000.0)
                    spin_box.setDecimals(2)
                    spin_box.setSingleStep(0.1)
                    spin_box.setValue(current_value)

                    def update_unbounded_float(val,
                                               fname=field_name,
                                               idx=op_index):
                        self.update_parameter(idx, fname, val)

                    spin_box.valueChanged.connect(update_unbounded_float)
                    h_layout.addWidget(spin_box)

                self.form_layout.addRow(field_name, container)

            elif field_info.annotation == int:
                container = QWidget()
                h_layout = QHBoxLayout(container)
                h_layout.setContentsMargins(0, 0, 0, 0)

                spin_box = QSpinBox()
                spin_box.setRange(0, 10000)
                spin_box.setValue(
                    int(current_value) if current_value is not None else 0)

                def update_int_wrapper(val, fname=field_name, idx=op_index):
                    self.update_parameter(idx, fname, val)

                spin_box.valueChanged.connect(update_int_wrapper)

                h_layout.addWidget(spin_box)
                self.form_layout.addRow(field_name, container)

            elif field_info.annotation == bool:
                container = QWidget()
                h_layout = QHBoxLayout(container)
                h_layout.setContentsMargins(0, 0, 0, 0)

                checkbox = QCheckBox()
                checkbox.setChecked(bool(current_value))

                def update_bool_wrapper(state, fname=field_name, idx=op_index):
                    self.update_parameter(idx, fname, bool(state))

                checkbox.stateChanged.connect(update_bool_wrapper)

                h_layout.addWidget(checkbox)
                self.form_layout.addRow(field_name, container)

            elif origin is Literal:
                container = QWidget()
                h_layout = QHBoxLayout(container)
                h_layout.setContentsMargins(0, 0, 0, 0)

                combo_box = QComboBox()
                allowed_options = get_args(field_info.annotation)

                combo_box.blockSignals(True)
                combo_box.addItems([str(opt) for opt in allowed_options])

                if current_value in allowed_options:
                    combo_box.setCurrentText(str(current_value))
                elif allowed_options:
                    combo_box.setCurrentText(str(allowed_options[0]))

                combo_box.blockSignals(False)

                def update_literal_wrapper(text,
                                           fname=field_name,
                                           idx=op_index):
                    self.update_parameter(idx, fname, text)

                combo_box.currentTextChanged.connect(update_literal_wrapper)

                h_layout.addWidget(combo_box)
                self.form_layout.addRow(field_name, container)

            elif field_info.annotation == str:
                container = QWidget()
                h_layout = QHBoxLayout(container)
                h_layout.setContentsMargins(0, 0, 0, 0)

                schema_extra = field_info.json_schema_extra or {}
                widget_type = schema_extra.get("widget")

                def update_value(text,
                                 fname=field_name,
                                 idx=op_index,
                                 wtype=widget_type):
                    op = self.engine.runner.operations[idx]
                    if getattr(op.config, fname) == text:
                        return

                    self.update_parameter(idx, fname, text)

                    if wtype == "operation_selector":
                        settings_key = f"{fname}_settings"
                        if hasattr(op.config, settings_key):
                            setattr(op.config, settings_key, {})
                        QTimer.singleShot(0, self.build_ui_for_current_step)

                if widget_type == "operation_selector":
                    widget = QComboBox()
                    widget.blockSignals(True)
                    widget.addItems(sorted(OPERATION_REGISTRY.keys()))
                    if current_value:
                        widget.setCurrentText(str(current_value))
                    widget.blockSignals(False)

                    widget.currentTextChanged.connect(update_value)
                    h_layout.addWidget(widget)

                else:
                    widget = QLineEdit(str(current_value or ""))
                    widget.textChanged.connect(update_value)
                    h_layout.addWidget(widget)

                    if widget_type == "file_picker":
                        browse_btn = QPushButton("Browse...")

                        def open_file_dialog(checked=False, le=widget):
                            file_path, _ = QFileDialog.getOpenFileName(
                                self, f"Select {field_name}", "",
                                "Images (*.png *.jpg *.jpeg);;All Files (*)")
                            if file_path:
                                le.setText(file_path)

                        browse_btn.clicked.connect(open_file_dialog)
                        h_layout.addWidget(browse_btn)

                self.form_layout.addRow(field_name, container)

            elif isinstance(current_value,
                            dict) or field_info.annotation == dict or getattr(
                                field_info.annotation, '__origin__',
                                None) is dict:
                registry_key = None
                prefix = field_name.split('_')[0] if '_' in field_name else ""
                if prefix and hasattr(operation.config, prefix):
                    registry_key = getattr(operation.config, prefix)
                elif hasattr(operation.config, "generator"):
                    registry_key = getattr(operation.config, "generator")

                op_info = OPERATION_REGISTRY.get(
                    registry_key) if registry_key else None

                if op_info and op_info["config"]:
                    sub_config_class = op_info["config"]
                    self.form_layout.addRow(
                        QLabel(
                            f"<br><i>Nested Context: {registry_key} ({field_name})</i>"
                        ))

                    for sub_field_name, sub_field_info in sub_config_class.model_fields.items(
                    ):
                        if sub_field_info.annotation == float:
                            sub_current_value = current_value.get(
                                sub_field_name, sub_field_info.default
                                if sub_field_info.default is not None else 0.0)

                            sub_container = QWidget()
                            sub_h_layout = QHBoxLayout(sub_container)
                            sub_h_layout.setContentsMargins(0, 0, 0, 0)

                            sub_slider = QSlider(Qt.Horizontal)
                            sub_slider.setMinimum(0)
                            sub_slider.setMaximum(1000)
                            sub_slider.setValue(int(sub_current_value * 10))

                            sub_value_label = QLabel(f"{sub_current_value:.1f}")
                            sub_value_label.setMinimumWidth(35)
                            sub_value_label.setAlignment(Qt.AlignRight |
                                                         Qt.AlignVCenter)

                            sub_h_layout.addWidget(sub_slider)
                            sub_h_layout.addWidget(sub_value_label)

                            def sub_update_wrapper(val,
                                                   parent_dict=field_name,
                                                   fname=sub_field_name,
                                                   idx=op_index,
                                                   lbl=sub_value_label):
                                real_val = val / 10.0
                                lbl.setText(f"{real_val:.1f}")
                                self.update_nested_parameter(
                                    idx, parent_dict, fname, real_val)

                            sub_slider.valueChanged.connect(sub_update_wrapper)
                            self.form_layout.addRow(f"↳ {sub_field_name}",
                                                    sub_container)

    def update_parameter(self, op_index, field_name, new_value):
        operation = self.engine.runner.operations[op_index]
        setattr(operation.config, field_name, new_value)
        # Track the lowest index modified
        if self._pending_op_index is None:
            self._pending_op_index = op_index
        else:
            self._pending_op_index = min(self._pending_op_index, op_index)
        self.debounce_timer.start()

    def update_nested_parameter(self, op_index, parent_dict_name, sub_field_name, new_value):
        operation = self.engine.runner.operations[op_index]
        if hasattr(operation.config, parent_dict_name):
            target_dict = getattr(operation.config, parent_dict_name)
            if isinstance(target_dict, dict):
                target_dict[sub_field_name] = new_value
                # Track the lowest index modified
                if self._pending_op_index is None:
                    self._pending_op_index = op_index
                else:
                    self._pending_op_index = min(self._pending_op_index, op_index)
                self.debounce_timer.start()

    def _execute_recalculation(self):
        if self._pending_op_index is not None:
            self._trigger_computation()

    def _on_step_streamed(self, state_data):
        step = state_data["step"]
        total = state_data["total"]
        op_name = state_data["op_name"]
        lines = state_data["lines"]
        vertices = sum(len(line.coords) for line in lines)
        
        self.update_stats_ui(step, total, op_name, len(lines), vertices, False)
        
        # --- 1. PRE-RENDER UI UPDATE ---
        safe_total = max(1, total) 
        self.progress_bar.setMaximum(safe_total)
        self.progress_bar.setValue(step)
        
        # Explicitly tell the user we are rendering this specific step
        self.progress_bar.setFormat(f"{step} / {total} ({op_name}) - Rendering...")
        
        # Force PyQt to draw the "Rendering..." text to the screen immediately
        QApplication.processEvents()
        
        # --- 2. HEAVY LIFTING ---
        # Now we do the heavy numpy/Vispy array conversions
        self.viewer.set_live_lines(lines)

        # --- 3. POST-RENDER CLEANUP ---
        # Strip the "Rendering..." text off now that the graphic is on screen
        self.progress_bar.setFormat(f"{step} / {total} ({op_name})")

    def _on_calculation_finished(self, history):
        self._is_computing = False
        
        # Cleanup UI buttons
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setStyleSheet("background-color: #8b0000; color: #aaaaaa; font-weight: bold;")
        
        # Lock bar at 100% and show finalization status
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.progress_bar.setFormat("Finalizing Display...")
        QApplication.processEvents() 

        # Sync the engine's runner history for localized scrubbing
        self.engine.runner.history = history
        
        target = len(self.engine.runner.operations) if self.viewer.show_final_view else self.viewer.current_step
        self.viewer.current_step = min(target, len(history) - 1)
        
        # Update view (now blazingly fast due to numpy)
        self.viewer.update_view() 

        # Give Vispy's OpenGL backend 150ms to push the final frame to the monitor 
        # before we declare the UI perfectly "Ready".
        QTimer.singleShot(150, self._set_ready_state)

    def _set_ready_state(self):
        """Clears the progress bar and queues the next run if needed."""
        self.progress_bar.setFormat("Ready")
        
        # Automatically start the next computation if the user kept sliding the bar
        if self._computation_queued:
            self._computation_queued = False
            self._trigger_computation()

    def _on_calculation_error(self, error_msg):
        self._is_computing = False
        logger.error(f"Background pipeline failed: {error_msg}")
        self.progress_bar.setFormat("Error")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setStyleSheet(
            "background-color: #8b0000; color: #aaaaaa; font-weight: bold;")

    def _get_current_recipe(self) -> list:
        current_recipe = []
        for op in self.engine.runner.operations:
            op_name = next((name for name, info in OPERATION_REGISTRY.items()
                            if isinstance(op, info["class"])), None)
            if not op_name:
                continue

            step = {"operation": op_name}
            if op.config:
                step["settings"] = op.config.model_dump()
            current_recipe.append(step)

        return current_recipe

    def _reload_pipeline(self, new_recipe: list, target_step: int):
        success = self.engine.load_recipe(new_recipe)
        if success:
            self._pending_op_index = 0  # Force a full recalculation from scratch
            max_step = len(self.engine.runner.operations)
            self.viewer.current_step = max(0, min(target_step, max_step))
            self.build_ui_for_current_step()
            self._trigger_computation()

    def _add_operation(self):
        op_name = self.op_selector.currentText()
        if not op_name:
            return

        recipe = self._get_current_recipe()
        insert_idx = self.viewer.current_step

        recipe.insert(insert_idx, {"operation": op_name, "settings": {}})
        self._reload_pipeline(recipe, target_step=insert_idx + 1)

    def _remove_operation(self):
        recipe = self._get_current_recipe()
        remove_idx = self.viewer.current_step - 1

        if 0 <= remove_idx < len(recipe):
            recipe.pop(remove_idx)
            self._reload_pipeline(recipe, target_step=max(0, remove_idx))

    def _load_live_recipe(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Recipe", "", "YAML Files (*.yaml *.yml);;All Files (*)")

        if not file_path:
            return

        try:
            with open(file_path, 'r') as f:
                new_recipe = yaml.safe_load(f)

            if not isinstance(new_recipe, list):
                logger.error(
                    "Invalid recipe format: must be a list of operations.")
                return

            success = self.engine.load_recipe(new_recipe)

            if success:
                self.viewer.current_step = len(self.engine.runner.operations)
                self.build_ui_for_current_step()
                self._trigger_computation()

        except Exception as e:
            logger.error(f"Error loading recipe from {file_path}: {e}")

    def _export_live_gcode(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export G-Code", "output.nc",
            "G-Code Files (*.nc *.gcode);;All Files (*)")

        if file_path:
            final_lines = self.engine.runner.history[-1].lines
            self.engine.export_gcode(lines=final_lines, output_path=file_path)

    def _save_live_recipe(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Recipe", "preset.yaml",
            "YAML Files (*.yaml *.yml);;All Files (*)")

        if not file_path:
            return

        current_recipe = self._get_current_recipe()

        try:
            with open(file_path, 'w') as f:
                yaml.safe_dump(current_recipe,
                               f,
                               sort_keys=False,
                               default_flow_style=False)
            logger.success(f"Recipe successfully saved to {file_path}")
        except Exception as e:
            logger.error(f"Failed to save recipe: {e}")

    def closeEvent(self, event):
        """
        Intercepts the window close action to guarantee no background
        processes are left orphaned consuming CPU.
        """
        if self.worker_thread and self.worker_thread.isRunning():
            logger.info(
                "Application closing: Terminating background workers...")

            # Hard kill the multiprocessing.Process
            self.worker_thread.cancel()

            # Tell the QThread to stop and wait up to 1000ms for it to clean up
            self.worker_thread.quit()
            self.worker_thread.wait(1000)

        # Accept the event so the window actually closes
        event.accept()


class PipelineViewer(scene.SceneCanvas):

    def __init__(self, engine):
        super().__init__(keys='interactive',
                         size=(800, 800),
                         title="Pendragon Pipeline Visualizer",
                         show=True)
        self.unfreeze()
        self.engine = engine
        self.current_step = min(1, len(self.engine.runner.operations))
        self.show_vertices = False
        self.show_final_view = False

        self.on_step_changed = None
        self.on_close_requested = None
        self.on_stats_updated = None

        self.view = self.central_widget.add_view()
        self.view.camera = 'panzoom'
        self.view.camera.aspect = 1.0

        dummy_pos = np.zeros((2, 2), dtype=np.float32)

        self.lines_visual = scene.visuals.Line(pos=dummy_pos,
                                               parent=self.view.scene,
                                               color='white')
        self.boundary_visual = scene.visuals.Line(pos=dummy_pos,
                                                  parent=self.view.scene,
                                                  color='red')
        self.vertices_visual = scene.visuals.Markers(pos=dummy_pos,
                                                     parent=self.view.scene)

        self.lines_visual.visible = False
        self.boundary_visual.visible = False
        self.vertices_visual.visible = False

        self.freeze()
        self.update_view()

        history = self.engine.runner.history
        if history and history[0].boundary:
            minx, miny, maxx, maxy = history[0].boundary.bounds
            self.view.camera.set_range(x=(minx, maxx), y=(miny, maxy))
        else:
            try:
                self.view.camera.set_range()
            except ValueError:
                pass

    def step_forward(self):
        max_step = len(self.engine.runner.operations)
        if self.current_step < max_step:
            self.current_step += 1
            self.update_view()
            if self.on_step_changed is not None:
                self.on_step_changed()

    def step_backward(self):
        if self.current_step > 0:
            self.current_step -= 1
            self.update_view()
            if self.on_step_changed is not None:
                self.on_step_changed()

    def on_key_press(self, event):
        if event.key is None:
            return
        if event.key.name == 'Right':
            self.step_forward()
        elif event.key.name == 'Left':
            self.step_backward()
        elif event.key.name == 'Escape':
            if self.on_close_requested is not None:
                self.on_close_requested()
            else:
                self.close()

    def set_live_lines(self, lines):
        """Bypasses normal state management to draw geometry instantly from the streaming worker."""
        if lines:
            # 1. Extract all coordinates into a list of arrays much faster
            coords_list = [np.array(line.coords) for line in lines]
            stacked_pos = np.vstack(coords_list)

            # 2. Vectorize the connection index building
            lengths = [len(c) for c in coords_list]
            connect_blocks = []
            current_idx = 0

            for n in lengths:
                if n > 1:
                    # Rapidly generate [0,1], [1,2], [2,3] index pairs for the GPU
                    starts = np.arange(current_idx, current_idx + n - 1)
                    ends = starts + 1
                    connect_blocks.append(np.column_stack((starts, ends)))
                current_idx += n

            final_connect = np.vstack(
                connect_blocks) if connect_blocks else np.empty((0, 2))

            self.lines_visual.set_data(pos=stacked_pos, connect=final_connect)
            self.lines_visual.visible = True

            if self.show_vertices:
                self.vertices_visual.set_data(pos=stacked_pos,
                                              face_color='red',
                                              edge_color=None,
                                              size=10)
                self.vertices_visual.visible = True
            else:
                self.vertices_visual.visible = False
        else:
            self.lines_visual.visible = False
            self.vertices_visual.visible = False

    def update_view(self):
        target_step = len(self.engine.runner.operations
                         ) if self.show_final_view else self.current_step

        # Safely cap the display step to whatever history currently exists
        display_step = min(target_step, len(self.engine.runner.history) - 1)
        state = self.engine.runner.history[display_step]

        total_vertices = sum(len(line.coords) for line in state.lines)
        total_ops = len(self.engine.runner.operations)

        if self.on_stats_updated:
            self.on_stats_updated(self.current_step,
                                  total_ops, state.operation_name,
                                  len(state.lines), total_vertices,
                                  self.show_final_view)

        if state.boundary and not state.boundary.is_empty:
            polygons = []
            if isinstance(state.boundary, Polygon):
                polygons = [state.boundary]
            elif isinstance(state.boundary, MultiPolygon):
                polygons = list(state.boundary.geoms)

            # --- FAST VECTORIZED BOUNDARY PREP ---
            coords_list = []
            for poly in polygons:
                coords_list.append(np.array(poly.exterior.coords))
                for interior in poly.interiors:
                    coords_list.append(np.array(interior.coords))

            if coords_list:
                stacked_b_pos = np.vstack(coords_list)
                lengths = [len(c) for c in coords_list]
                connect_blocks = []
                current_idx = 0
                
                for n in lengths:
                    if n > 1:
                        # Rapidly generate [0,1], [1,2], [2,3] index pairs
                        starts = np.arange(current_idx, current_idx + n - 1)
                        ends = starts + 1
                        connect_blocks.append(np.column_stack((starts, ends)))
                    current_idx += n
                    
                b_connect = np.vstack(connect_blocks) if connect_blocks else np.empty((0, 2))
                
                self.boundary_visual.set_data(pos=stacked_b_pos, connect=b_connect)
                self.boundary_visual.visible = True
            else:
                self.boundary_visual.visible = False
        else:
            self.boundary_visual.visible = False

        self.set_live_lines(state.lines)
