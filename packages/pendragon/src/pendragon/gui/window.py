from typing import get_origin

from loguru import logger
from pendragon.gui.constants import DARK_THEME_STYLESHEET
from pendragon.gui.viewer import PipelineViewer
from pendragon.gui.widgets import WidgetFactory
from pendragon.gui.worker import PipelineStreamingThread
from pendragon.registry import dxf_registry
from PyQt5.QtCore import Qt
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication
from PyQt5.QtWidgets import QCheckBox
from PyQt5.QtWidgets import QComboBox
from PyQt5.QtWidgets import QFileDialog
from PyQt5.QtWidgets import QFormLayout
from PyQt5.QtWidgets import QGroupBox
from PyQt5.QtWidgets import QHBoxLayout
from PyQt5.QtWidgets import QLabel
from PyQt5.QtWidgets import QMainWindow
from PyQt5.QtWidgets import QProgressBar
from PyQt5.QtWidgets import QPushButton
from PyQt5.QtWidgets import QVBoxLayout
from PyQt5.QtWidgets import QWidget
import yaml


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
        self.op_selector.addItems(sorted([k for k, _ in dxf_registry.items()]))

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

        start_index = self._pending_op_index if self._pending_op_index is not None else 0
        self._pending_op_index = None

        prior_history = None
        if start_index > 0 and len(self.engine.runner.history) > start_index:
            prior_history = self.engine.runner.history[:start_index + 1]
        else:
            start_index = 0

        self.btn_cancel.setEnabled(True)
        self.btn_cancel.setStyleSheet(
            "background-color: #ff4444; color: white; font-weight: bold;")

        self.progress_bar.setValue(start_index)
        self.progress_bar.setFormat("Initializing...")

        current_recipe = self._get_current_recipe()

        self.worker_thread = PipelineStreamingThread(
            current_recipe,
            self.engine.initial_state.boundary,  # <-- FIXED ATTRIBUTE ACCESS
            prior_history=prior_history,
            start_index=start_index)
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
        self._computation_queued = False
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

        # --- PLUGIN UI DELEGATION HOOK ---
        if hasattr(operation, "build_custom_ui"):
            custom_widget = operation.build_custom_ui(self, op_index)
            if custom_widget:
                self.form_layout.addRow(custom_widget)
                return
        # ---------------------------------

        for field_name, field_info in operation.config.model_fields.items():
            current_value = getattr(operation.config, field_name)

            # 1. Handle Nested Configs (Dictionaries)
            if isinstance(current_value,
                          dict) or field_info.annotation == dict or getattr(
                              field_info.annotation, '__origin__',
                              None) is dict:
                registry_key = None
                prefix = field_name.split('_')[0] if '_' in field_name else ""
                if prefix and hasattr(operation.config, prefix):
                    registry_key = getattr(operation.config, prefix)
                elif hasattr(operation.config, "generator"):
                    registry_key = getattr(operation.config, "generator")

                op_info = dxf_registry.get(
                    registry_key) if registry_key else None

                if op_info and op_info["config"]:
                    sub_config_class = op_info["config"]
                    self.form_layout.addRow(
                        QLabel(
                            f"<br><i>Nested Context: {registry_key} ({field_name})</i>"
                        ))

                    for sub_field_name, sub_field_info in sub_config_class.model_fields.items(
                    ):
                        sub_current_value = current_value.get(
                            sub_field_name, sub_field_info.default
                            if sub_field_info.default is not None else 0.0)

                        def nested_update_callback(val,
                                                   parent_dict=field_name,
                                                   fname=sub_field_name,
                                                   idx=op_index):
                            self.update_nested_parameter(
                                idx, parent_dict, fname, val)

                        sub_container = WidgetFactory.build_field_widget(
                            sub_field_name,
                            sub_field_info,
                            sub_current_value,
                            nested_update_callback,
                            parent=self)
                        if sub_container:
                            self.form_layout.addRow(f"↳ {sub_field_name}",
                                                    sub_container)
                continue

            # 2. Handle Standard Config Fields via WidgetFactory
            schema_extra = field_info.json_schema_extra or {}
            widget_type = schema_extra.get("widget")

            if field_info.annotation == str:

                def root_update_callback(text,
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
            else:

                def root_update_callback(val, fname=field_name, idx=op_index):
                    self.update_parameter(idx, fname, val)

            container = WidgetFactory.build_field_widget(field_name,
                                                         field_info,
                                                         current_value,
                                                         root_update_callback,
                                                         parent=self)
            if container:
                self.form_layout.addRow(field_name, container)

    def update_parameter(self, op_index, field_name, new_value):
        operation = self.engine.runner.operations[op_index]
        setattr(operation.config, field_name, new_value)
        if self._pending_op_index is None:
            self._pending_op_index = op_index
        else:
            self._pending_op_index = min(self._pending_op_index, op_index)
        self.debounce_timer.start()

    def update_nested_parameter(self, op_index, parent_dict_name,
                                sub_field_name, new_value):
        operation = self.engine.runner.operations[op_index]
        if hasattr(operation.config, parent_dict_name):
            target_dict = getattr(operation.config, parent_dict_name)
            if isinstance(target_dict, dict):
                target_dict[sub_field_name] = new_value
                if self._pending_op_index is None:
                    self._pending_op_index = op_index
                else:
                    self._pending_op_index = min(self._pending_op_index,
                                                 op_index)
                self.debounce_timer.start()

    def _execute_recalculation(self):
        if self._pending_op_index is not None:
            self._trigger_computation()

    def _on_step_streamed(self, state_data):
        step = state_data["step"]
        total = state_data["total"]
        op_name = state_data["op_name"]

        line_count = state_data["line_count"]
        pos = state_data["pos"]
        connect = state_data["connect"]
        vertices = len(pos)

        safe_total = max(1, total)
        self.progress_bar.setMaximum(safe_total)
        self.progress_bar.setValue(step)

        self.progress_bar.setFormat(
            f"{step} / {total} ({op_name}) - Rendering...")
        QApplication.processEvents()

        if self.viewer.show_final_view or step == self.viewer.current_step:
            self.update_stats_ui(step, total, op_name, line_count, vertices,
                                 False)
            self.viewer.set_live_vectors(pos, connect)

        self.progress_bar.setFormat(f"{step} / {total} ({op_name})")

    def _on_calculation_finished(self, history):
        self._is_computing = False

        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setStyleSheet(
            "background-color: #8b0000; color: #aaaaaa; font-weight: bold;")

        self.progress_bar.setValue(self.progress_bar.maximum())
        self.progress_bar.setFormat("Finalizing Display...")
        QApplication.processEvents()

        self.engine.runner.history = history

        target = len(
            self.engine.runner.operations
        ) if self.viewer.show_final_view else self.viewer.current_step
        self.viewer.current_step = min(target, len(history) - 1)

        self.viewer.update_view()

        QTimer.singleShot(150, self._set_ready_state)

    def _set_ready_state(self):
        self.progress_bar.setFormat("Ready")
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
            op_name = next((name for name, info in dxf_registry.items()
                            if isinstance(op, info["class"])), None)
            if not op_name:
                continue

            step = {"operation": op_name}
            if op.config:
                step["settings"] = op.config.model_dump()
            current_recipe.append(step)

        return current_recipe

    def _reload_pipeline(self,
                         new_recipe: list,
                         target_step: int,
                         valid_history_idx: int = 0):
        valid_history = []
        if valid_history_idx > 0 and len(
                self.engine.runner.history) > valid_history_idx:
            valid_history = self.engine.runner.history[:valid_history_idx + 1]

        success = self.engine.load_recipe(new_recipe)

        if success:
            if valid_history:
                self.engine.runner.history = valid_history

            self._pending_op_index = valid_history_idx

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

        self._reload_pipeline(recipe,
                              target_step=insert_idx + 1,
                              valid_history_idx=insert_idx)

    def _remove_operation(self):
        recipe = self._get_current_recipe()
        remove_idx = self.viewer.current_step - 1

        if 0 <= remove_idx < len(recipe):
            recipe.pop(remove_idx)

            self._reload_pipeline(recipe,
                                  target_step=max(0, remove_idx),
                                  valid_history_idx=remove_idx)

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
            from pendragon.pen import PenConfig
            from pendragon.pen import PenTool
            config = PenConfig()
            with PenTool(config=config, output_filename=file_path) as pen:
                for line in final_lines:
                    pen.draw_path(list(line.coords))

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
        if self.worker_thread and self.worker_thread.isRunning():
            logger.info(
                "Application closing: Terminating background workers...")

            self.worker_thread.cancel()
            self.worker_thread.quit()
            self.worker_thread.wait(1000)

        event.accept()
