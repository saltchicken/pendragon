from PyQt5.QtCore import Qt
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication
from PyQt5.QtWidgets import QCheckBox
from PyQt5.QtWidgets import QFileDialog
from PyQt5.QtWidgets import QFormLayout
from PyQt5.QtWidgets import QHBoxLayout
from PyQt5.QtWidgets import QLabel
from PyQt5.QtWidgets import QMainWindow
from PyQt5.QtWidgets import QPushButton
from PyQt5.QtWidgets import QVBoxLayout
from PyQt5.QtWidgets import QWidget

from pendragon.gui.controller import PipelineController
from pendragon.gui.panels import ActionPanel
from pendragon.gui.panels import EditPanel
from pendragon.gui.panels import ProgressPanel
from pendragon.gui.panels import StatsPanel
from pendragon.gui.viewer import PipelineViewer
from pendragon.gui.widgets import WidgetFactory

from pendragon.gui.utils import load_stylesheet


class LiveEditorWindow(QMainWindow):

    def __init__(self, controller: PipelineController):
        super().__init__()
        self.setWindowTitle("Pendragon Live Editor")
        self.controller = controller
        
        self.setStyleSheet(load_stylesheet("style.qss"))

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # Viewer setup
        self.viewer = PipelineViewer(self.controller.engine)
        main_layout.addWidget(self.viewer.native, stretch=3)

        # Control Panel setup
        self.control_panel = QWidget()
        self.control_layout = QVBoxLayout(self.control_panel)
        self.control_layout.setAlignment(Qt.AlignTop)
        main_layout.addWidget(self.control_panel, stretch=1)

        # 1. Stats Panel
        self.stats_panel = StatsPanel()
        self.control_layout.addWidget(self.stats_panel)

        # 2. Progress Panel
        self.progress_panel = ProgressPanel()
        self.progress_panel.btn_cancel.clicked.connect(self.controller.cancel_computation)
        self.control_layout.addWidget(self.progress_panel)

        # 3. Viewer Toggles
        self.show_vertices_checkbox = QCheckBox("Show Vertices")
        self.show_vertices_checkbox.toggled.connect(self._on_vertices_toggled)
        self.control_layout.addWidget(self.show_vertices_checkbox)

        self.final_view_checkbox = QCheckBox("Show Final View")
        self.final_view_checkbox.toggled.connect(self._on_view_mode_toggled)
        self.control_layout.addWidget(self.final_view_checkbox)

        # 4. Navigation Buttons
        self.nav_layout = QHBoxLayout()
        self.btn_prev = QPushButton("Previous Step")
        self.btn_next = QPushButton("Next Step")
        self.btn_prev.clicked.connect(self.viewer.step_backward)
        self.btn_next.clicked.connect(self.viewer.step_forward)
        self.nav_layout.addWidget(self.btn_prev)
        self.nav_layout.addWidget(self.btn_next)
        self.control_layout.addLayout(self.nav_layout)

        # 5. File Actions Panel
        self.action_panel = ActionPanel()
        self.action_panel.btn_load.clicked.connect(self._gui_load_recipe)
        self.action_panel.btn_save.clicked.connect(self._gui_save_recipe)
        self.action_panel.btn_export.clicked.connect(self._gui_export_gcode)
        self.control_layout.addWidget(self.action_panel)

        # 6. Editing Panel
        op_names = self.controller.engine.registry.get_operation_names()
        self.edit_panel = EditPanel(op_names=op_names)
        self.edit_panel.btn_add.clicked.connect(self._gui_add_operation)
        self.edit_panel.btn_remove.clicked.connect(self._gui_remove_operation)
        self.control_layout.addWidget(self.edit_panel)

        # 7. Dynamic Form Area
        self.dynamic_form_widget = QWidget()
        self.form_layout = QFormLayout(self.dynamic_form_widget)
        self.control_layout.addWidget(self.dynamic_form_widget)

        # --- Bind Viewer Callbacks ---
        self.viewer.on_step_changed = self.build_ui_for_current_step
        self.viewer.on_close_requested = self.close
        self.viewer.on_stats_updated = self.stats_panel.update_stats

        # --- Bind Controller Signals ---
        self.controller.computation_started.connect(self._on_compute_start)
        self.controller.step_streamed.connect(self._on_step_streamed)
        self.controller.computation_finished.connect(self._on_compute_finish)
        self.controller.computation_error.connect(self._on_compute_error)
        self.controller.computation_cancelled.connect(self._on_compute_cancel)
        self.controller.ui_rebuild_requested.connect(self._on_ui_rebuild)

        # Initial Boot
        self.build_ui_for_current_step()
        self.controller.trigger_computation()

    # --- GUI -> Controller Interactions ---
    
    def _gui_add_operation(self):
        op_name = self.edit_panel.op_selector.currentText()
        insert_idx = self.viewer.current_step
        self.controller.add_operation(insert_idx, op_name)

    def _gui_remove_operation(self):
        remove_idx = self.viewer.current_step - 1
        self.controller.remove_operation(remove_idx)

    def _gui_load_recipe(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Recipe", "", "YAML Files (*.yaml *.yml);;All Files (*)")
        if file_path:
            if self.controller.load_recipe_from_file(file_path):
                self.viewer.current_step = len(self.controller.engine.operations)

    def _gui_save_recipe(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Recipe", "preset.yaml", "YAML Files (*.yaml *.yml);;All Files (*)")
        if file_path:
            self.controller.save_recipe_to_file(file_path)

    def _gui_export_gcode(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export G-Code", "output.nc", "G-Code Files (*.nc *.gcode);;All Files (*)")
        if file_path:
            self.controller.export_gcode_to_file(file_path)

    def _on_vertices_toggled(self, checked):
        self.viewer.show_vertices = checked
        self.viewer.update_view()

    def _on_view_mode_toggled(self, checked):
        self.viewer.show_final_view = checked
        self.viewer.update_view()

    # --- Controller -> GUI Updates ---

    def _on_ui_rebuild(self):
        """Called when operations are added/removed to fix viewer indexing."""
        max_step = len(self.controller.engine.operations)
        if self.viewer.current_step > max_step:
            self.viewer.current_step = max_step
        self.build_ui_for_current_step()

    def _on_compute_start(self, start_index: int):
        self.progress_panel.btn_cancel.setEnabled(True)
        self.progress_panel.btn_cancel.setStyleSheet("background-color: #ff4444; color: white; font-weight: bold;")
        self.progress_panel.bar.setValue(start_index)
        self.progress_panel.bar.setFormat("Initializing...")

    def _on_step_streamed(self, state_data):
        step, total, op_name = state_data["step"], state_data["total"], state_data["op_name"]
        
        safe_total = max(1, total)
        self.progress_panel.bar.setMaximum(safe_total)
        self.progress_panel.bar.setValue(step)
        self.progress_panel.bar.setFormat(f"{step} / {total} ({op_name}) - Rendering...")
        
        QApplication.processEvents()

        if self.viewer.show_final_view or step == self.viewer.current_step:
            self.stats_panel.update_stats(
                step, total, op_name, state_data["line_count"], len(state_data["pos"]), False
            )
            self.viewer.set_live_vectors(state_data["pos"], state_data["connect"])

        self.progress_panel.bar.setFormat(f"{step} / {total} ({op_name})")

    def _on_compute_finish(self, final_store):
        self.progress_panel.btn_cancel.setEnabled(False)
        self.progress_panel.btn_cancel.setStyleSheet("background-color: #8b0000; color: #aaaaaa; font-weight: bold;")
        self.progress_panel.bar.setValue(self.progress_panel.bar.maximum())
        self.progress_panel.bar.setFormat("Finalizing Display...")
        QApplication.processEvents()

        target = len(self.controller.engine.operations) if self.viewer.show_final_view else self.viewer.current_step
        self.viewer.current_step = min(target, len(final_store) - 1)
        self.viewer.update_view()

        QTimer.singleShot(150, self._set_ready_state)

    def _set_ready_state(self):
        self.progress_panel.bar.setFormat("Ready")
        self.controller.finalize_state()

    def _on_compute_error(self, error_msg):
        self.progress_panel.bar.setFormat("Error")
        self._disable_cancel()

    def _on_compute_cancel(self):
        self.progress_panel.bar.setFormat("Computation Aborted")
        self._disable_cancel()

    def _disable_cancel(self):
        self.progress_panel.btn_cancel.setEnabled(False)
        self.progress_panel.btn_cancel.setStyleSheet("background-color: #8b0000; color: #aaaaaa; font-weight: bold;")

    # --- Dynamic Form Builder ---

    def build_ui_for_current_step(self):
        """Constructs the property editor based on the engine's current operation config."""
        self.control_layout.removeWidget(self.dynamic_form_widget)
        self.dynamic_form_widget.deleteLater()

        self.dynamic_form_widget = QWidget()
        self.form_layout = QFormLayout(self.dynamic_form_widget)
        self.control_layout.addWidget(self.dynamic_form_widget)

        op_index = self.viewer.current_step - 1
        if op_index < 0 or op_index >= len(self.controller.engine.operations):
            self.form_layout.addRow(QLabel("No configurable parameters for this state."))
            return

        operation = self.controller.engine.operations[op_index]
        if not operation.config:
            self.form_layout.addRow(QLabel(f"{operation.__class__.__name__} has no config."))
            return

        self.form_layout.addRow(QLabel(f"<b>Editing: {operation.__class__.__name__}</b>"))

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
            if isinstance(current_value, dict) or field_info.annotation == dict or getattr(field_info.annotation, '__origin__', None) is dict:
                registry_key = None
                prefix = field_name.split('_')[0] if '_' in field_name else ""
                if prefix and hasattr(operation.config, prefix):
                    registry_key = getattr(operation.config, prefix)
                elif hasattr(operation.config, "generator"):
                    registry_key = getattr(operation.config, "generator")

                # Grab the op info from the engine's registry instance
                op_info = self.controller.engine.registry.get(registry_key) if registry_key else None

                if op_info and op_info["config"]:
                    sub_config_class = op_info["config"]
                    self.form_layout.addRow(QLabel(f"<br><i>Nested Context: {registry_key} ({field_name})</i>"))

                    for sub_field_name, sub_field_info in sub_config_class.model_fields.items():
                        sub_current_value = current_value.get(
                            sub_field_name, sub_field_info.default if sub_field_info.default is not None else 0.0)

                        def nested_update_callback(val, parent_dict=field_name, fname=sub_field_name, idx=op_index):
                            self.controller.update_nested_parameter(idx, parent_dict, fname, val)

                        sub_container = WidgetFactory.build_field_widget(
                            sub_field_name, sub_field_info, sub_current_value, nested_update_callback, 
                            registry=self.controller.engine.registry, parent=self
                        )
                        if sub_container:
                            self.form_layout.addRow(f"↳ {sub_field_name}", sub_container)
                continue

            # 2. Handle Standard Config Fields via WidgetFactory
            schema_extra = field_info.json_schema_extra or {}
            widget_type = schema_extra.get("widget")

            if field_info.annotation == str:
                def root_update_callback(text, fname=field_name, idx=op_index, wtype=widget_type):
                    op = self.controller.engine.operations[idx]
                    if getattr(op.config, fname) == text:
                        return
                    self.controller.update_parameter(idx, fname, text)
                    
                    if wtype == "operation_selector":
                        settings_key = f"{fname}_settings"
                        if hasattr(op.config, settings_key):
                            setattr(op.config, settings_key, {})
                        QTimer.singleShot(0, self.build_ui_for_current_step)
            else:
                def root_update_callback(val, fname=field_name, idx=op_index):
                    self.controller.update_parameter(idx, fname, val)

            container = WidgetFactory.build_field_widget(
                field_name, field_info, current_value, root_update_callback, 
                registry=self.controller.engine.registry, parent=self
            )
            if container:
                self.form_layout.addRow(field_name, container)

    def closeEvent(self, event):
        self.controller.shutdown()
        event.accept()
