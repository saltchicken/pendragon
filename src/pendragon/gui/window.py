from PyQt5.QtCore import Qt
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication
from PyQt5.QtWidgets import QCheckBox
from PyQt5.QtWidgets import QFileDialog
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
from pendragon.gui.panels import PropertiesPanel
from pendragon.gui.panels import StatsPanel
from pendragon.gui.utils import load_stylesheet
from pendragon.gui.viewer import PipelineViewer


class LiveEditorWindow(QMainWindow):

    def __init__(self, controller: PipelineController):
        super().__init__()
        self.setWindowTitle("Pendragon Live Editor")
        self.controller = controller

        self.setStyleSheet(load_stylesheet("style.qss"))

        self._setup_ui()
        self._connect_signals()

        self.build_ui_for_current_step()
        self.controller.trigger_computation()

    def _setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        self.viewer = PipelineViewer(self.controller.engine)
        main_layout.addWidget(self.viewer.native, stretch=3)

        self.control_panel = QWidget()
        self.control_layout = QVBoxLayout(self.control_panel)
        self.control_layout.setAlignment(Qt.AlignTop)
        main_layout.addWidget(self.control_panel, stretch=1)

        self.stats_panel = StatsPanel()
        self.control_layout.addWidget(self.stats_panel)

        self.progress_panel = ProgressPanel()
        self.control_layout.addWidget(self.progress_panel)

        self.show_vertices_checkbox = QCheckBox("Show Vertices")
        self.control_layout.addWidget(self.show_vertices_checkbox)

        self.final_view_checkbox = QCheckBox("Show Final View")
        self.control_layout.addWidget(self.final_view_checkbox)

        self.nav_layout = QHBoxLayout()
        self.btn_prev = QPushButton("Previous Step")
        self.btn_next = QPushButton("Next Step")
        self.nav_layout.addWidget(self.btn_prev)
        self.nav_layout.addWidget(self.btn_next)
        self.control_layout.addLayout(self.nav_layout)

        self.action_panel = ActionPanel()
        self.control_layout.addWidget(self.action_panel)

        op_names = self.controller.get_available_operations()
        self.edit_panel = EditPanel(op_names=op_names)
        self.control_layout.addWidget(self.edit_panel)

        self.properties_panel = PropertiesPanel(self.controller)
        self.control_layout.addWidget(self.properties_panel)

    def _connect_signals(self):
        # UI Component Signals
        self.progress_panel.btn_cancel.clicked.connect(
            self.controller.cancel_computation)

        self.show_vertices_checkbox.toggled.connect(self._on_vertices_toggled)
        self.final_view_checkbox.toggled.connect(self._on_view_mode_toggled)

        self.btn_prev.clicked.connect(self.viewer.step_backward)
        self.btn_next.clicked.connect(self.viewer.step_forward)

        self.action_panel.btn_load.clicked.connect(self._gui_load_recipe)
        self.action_panel.btn_save.clicked.connect(self._gui_save_recipe)
        self.action_panel.btn_export.clicked.connect(self._gui_export_gcode)

        self.edit_panel.btn_add.clicked.connect(self._gui_add_operation)
        self.edit_panel.btn_remove.clicked.connect(self._gui_remove_operation)

        # Viewer Event Bindings
        self.viewer.on_step_changed = self.build_ui_for_current_step
        self.viewer.on_close_requested = self.close
        self.viewer.on_stats_updated = self.stats_panel.update_stats

        # Controller Bindings
        self.controller.computation_started.connect(self._on_compute_start)
        self.controller.step_streamed.connect(self._on_step_streamed)
        self.controller.computation_finished.connect(self._on_compute_finish)
        self.controller.computation_error.connect(self._on_compute_error)
        self.controller.computation_cancelled.connect(self._on_compute_cancel)
        self.controller.ui_rebuild_requested.connect(self._on_ui_rebuild)

    def _gui_add_operation(self):
        op_name = self.edit_panel.op_selector.currentText()
        insert_idx = self.viewer.current_step
        self.viewer.current_step += 1
        self.controller.add_operation(insert_idx, op_name)

    def _gui_remove_operation(self):
        remove_idx = self.viewer.current_step - 1
        self.controller.remove_operation(remove_idx)

    def _gui_load_recipe(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Recipe", "", "YAML Files (*.yaml *.yml);;All Files (*)")
        if file_path:
            if self.controller.load_recipe_from_file(file_path):
                self.viewer.current_step = self.controller.get_operation_count()

    def _gui_save_recipe(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Recipe", "preset.yaml",
            "YAML Files (*.yaml *.yml);;All Files (*)")
        if file_path:
            self.controller.save_recipe_to_file(file_path)

    def _gui_export_gcode(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export G-Code", "output.nc",
            "G-Code Files (*.nc *.gcode);;All Files (*)")
        if file_path:
            self.controller.export_gcode_to_file(file_path)

    def _on_vertices_toggled(self, checked):
        self.viewer.show_vertices = checked
        self.viewer.update_view()

    def _on_view_mode_toggled(self, checked):
        self.viewer.show_final_view = checked
        self.viewer.update_view()

    def _on_ui_rebuild(self):
        max_step = self.controller.get_operation_count()
        if self.viewer.current_step > max_step:
            self.viewer.current_step = max_step
        self.build_ui_for_current_step()

    def _on_compute_start(self, start_index: int):
        self.progress_panel.btn_cancel.setEnabled(True)
        self.progress_panel.btn_cancel.setStyleSheet(
            "background-color: #ff4444; color: white; font-weight: bold;")
        self.progress_panel.bar.setValue(start_index)
        self.progress_panel.bar.setFormat("Initializing...")

    def _on_step_streamed(self, event):
        # Access attributes directly from the StreamEvent and nested FrameData objects
        step = event.step
        total = event.total
        op_name = event.data.op_name
        
        safe_total = max(1, total)
        self.progress_panel.bar.setMaximum(safe_total)
        self.progress_panel.bar.setValue(step)
        self.progress_panel.bar.setFormat(
            f"{step} / {total} ({op_name}) - Rendering...")

        if self.viewer.show_final_view or step == self.viewer.current_step:
            self.stats_panel.update_stats(step, total, op_name,
                                          event.data.line_count,
                                          len(event.data.pos), False)
            self.viewer.set_live_vectors(event.data.pos,
                                         event.data.connect)
        self.progress_panel.bar.setFormat(f"{step} / {total} ({op_name})")

    def _on_compute_finish(self, final_store):
        self.progress_panel.btn_cancel.setEnabled(False)
        self.progress_panel.btn_cancel.setStyleSheet(
            "background-color: #8b0000; color: #aaaaaa; font-weight: bold;")
        self.progress_panel.bar.setValue(self.progress_panel.bar.maximum())
        self.progress_panel.bar.setFormat("Finalizing Display...")

        target = self.controller.get_operation_count(
        ) if self.viewer.show_final_view else self.viewer.current_step
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
        self.progress_panel.btn_cancel.setStyleSheet(
            "background-color: #8b0000; color: #aaaaaa; font-weight: bold;")

    def build_ui_for_current_step(self):
        self.properties_panel.rebuild_for_step(self.viewer.current_step)

    def closeEvent(self, event):
        self.controller.shutdown()
        event.accept()
