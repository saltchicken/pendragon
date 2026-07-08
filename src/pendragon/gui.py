import time
import yaml
from typing import List, Dict, Any
import numpy as np
from shapely.geometry import Polygon, MultiPolygon
from vispy import scene
from loguru import logger

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSlider, QLabel, 
    QFormLayout, QApplication, QCheckBox, QGroupBox, QPushButton,
    QFileDialog, QProgressBar
)
from PyQt5.QtCore import Qt, QTimer, QThread, QObject, pyqtSignal, pyqtSlot

from pendragon.core.models import PipelineState
from pendragon.core.registry import OPERATION_REGISTRY


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
"""


class PipelineWorker(QObject):
    computation_finished = pyqtSignal(object, int, int, bool)
    computation_cancelled = pyqtSignal()  
    progress_update = pyqtSignal(int, str)

    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self._cancel_flag = False

    @pyqtSlot()
    def request_cancel(self):
        self._cancel_flag = True

    def check_cancel(self):
        # Explicitly yield the GIL so the main thread's GUI event loop stays responsive
        time.sleep(0.001) 
        if self._cancel_flag:
            raise InterruptedError("Computation cancelled by user.")

    def _emit_progress(self, percent: int, message: str):
        self.progress_update.emit(percent, message)

    @pyqtSlot(int, int, bool)
    def compute(self, start_index: int, target_step: int, is_final: bool):
        self._cancel_flag = False
        try:
            runner = self.engine.runner
            
            # Pass both callbacks down into the runner
            runner.recompute_from(
                start_index, target_step, 
                cancel_callback=self.check_cancel,
                progress_callback=self._emit_progress
            )
            
            state_index = target_step if target_step < len(runner.history) else -1
            state = runner.history[state_index]
            total_ops = len(runner.operations)
            
            self.computation_finished.emit(state, target_step, total_ops, is_final)
        
        except InterruptedError:
            logger.warning("Worker caught cancellation request.")
            self.computation_cancelled.emit()
        except Exception as e:
            logger.error(f"Background computation error: {e}")


class LiveEditorWindow(QMainWindow):
    compute_requested = pyqtSignal(int, int, bool)

    def __init__(self, engine):
        super().__init__()
        self.setWindowTitle("Pendragon")
        self.engine = engine

        self.setStyleSheet(DARK_THEME_STYLESHEET)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # 1. The Vispy Canvas (Left Side)
        self.viewer = PipelineViewer(self.engine)
        main_layout.addWidget(self.viewer.native, stretch=3)

        # 2. Parameter Control Panel (Right Side)
        self.control_panel = QWidget()
        self.control_layout = QVBoxLayout(self.control_panel)
        self.control_layout.setAlignment(Qt.AlignTop)
        main_layout.addWidget(self.control_panel, stretch=1)

        # --- Pipeline Statistics HUD ---
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
        # -------------------------------

        # View Mode Toggle
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

        # --- Action Buttons ---
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

        # Dynamic form area for sliders
        self.dynamic_form_widget = QWidget()
        self.form_layout = QFormLayout(self.dynamic_form_widget)
        self.control_layout.addWidget(self.dynamic_form_widget)

        # --- Cancel & Progress UI ---
        self.process_layout = QHBoxLayout()
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet("QProgressBar { border: 1px solid #555; border-radius: 3px; text-align: center; } QProgressBar::chunk { background-color: #007acc; }")
        
        self.btn_cancel = QPushButton("Cancel & Revert")
        self.btn_cancel.setEnabled(True)
        self.btn_cancel.setStyleSheet("background-color: #8b0000; font-weight: bold;")
        
        self.process_layout.addWidget(self.progress_bar, stretch=3)
        self.process_layout.addWidget(self.btn_cancel, stretch=1)
        self.control_layout.addLayout(self.process_layout)

        # --- QThread Setup ---
        self.worker_thread = QThread()
        self.worker = PipelineWorker(self.engine)
        self.worker.moveToThread(self.worker_thread)
        
        # Connect core computation signals
        self.compute_requested.connect(self.worker.compute)
        self.worker.computation_finished.connect(self._on_computation_ready)
        
        # Connect Cancel & Progress signals
        self.btn_cancel.clicked.connect(self.worker.request_cancel)
        self.worker.computation_cancelled.connect(self._on_computation_cancelled)
        self.worker.progress_update.connect(self._on_progress_update)
        
        self.worker_thread.start()
        # ---------------------

        # Hook up viewer callbacks
        self.viewer.on_step_changed = self.build_ui_for_current_step
        self.viewer.on_close_requested = self.close
        self.viewer.on_stats_updated = self.update_stats_ui
        
        # Debounce Timer Setup
        self.debounce_timer = QTimer()
        self.debounce_timer.setSingleShot(True)
        self.debounce_timer.setInterval(300) 
        self.debounce_timer.timeout.connect(self._execute_recalculation)
        self._pending_op_index = None

        self._backup_state = None  # Tuple: (op_index, field_name, old_value)
        self.build_ui_for_current_step()

    def closeEvent(self, event):
        """Ensure thread is safely terminated when GUI closes."""
        self.worker_thread.quit()
        self.worker_thread.wait()
        super().closeEvent(event)

    @pyqtSlot(int, str)
    def _on_progress_update(self, value, text):
        """Update the progress bar from the background thread."""
        self.progress_bar.setValue(value)
        self.progress_bar.setFormat(f"{text} %p%")

    def _trigger_computation(self, start_index=None):
        self.dynamic_form_widget.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress_bar.setValue(0)
        
        target = len(self.engine.runner.operations) if self.viewer.show_final_view else self.viewer.current_step
        if start_index is None:
            start_index = len(self.engine.runner.history) - 1
        
        start = max(0, min(start_index, target))
        self.compute_requested.emit(start, target, self.viewer.show_final_view)

    @pyqtSlot(object, int, int, bool)
    def _on_computation_ready(self, state, display_step, total_ops, is_final):
        self._backup_state = None
        self.dynamic_form_widget.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("Ready")
        self.viewer.render_state(state, display_step, total_ops, is_final)

    @pyqtSlot()
    def _on_computation_cancelled(self):
        if self._backup_state:
            op_idx, field, old_val = self._backup_state
            operation = self.engine.runner.operations[op_idx]
            
            setattr(operation.config, field, old_val)
            logger.info(f"Reverted {field} back to {old_val}")
            
            self._backup_state = None
            self.build_ui_for_current_step()
            self.viewer.update_view()

        self.dynamic_form_widget.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Cancelled")

    def _on_view_mode_toggled(self, checked):
        """Swaps the viewer mode and triggers a background computation."""
        self.viewer.show_final_view = checked
        self._trigger_computation()

    def update_stats_ui(self, step, total_ops, op_name, lines, vertices, final_view):
        """Updates the discrete PyQt labels for pipeline statistics."""
        step_text = f"{step} / {total_ops}"
        if final_view:
            step_text += " (FINAL VIEW)"
            
        self.step_label.setText(step_text)
        self.op_label.setText(str(op_name))
        self.lines_label.setText(str(lines))
        self.vertices_label.setText(str(vertices))

    def build_ui_for_current_step(self):
        while self.form_layout.count():
            child = self.form_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        op_index = self.viewer.current_step - 1 
        if op_index < 0 or op_index >= len(self.engine.runner.operations):
            self.form_layout.addRow(QLabel("No configurable parameters for this state."))
            self._trigger_computation()
            return

        operation = self.engine.runner.operations[op_index]
        if not operation.config:
            self.form_layout.addRow(QLabel(f"{operation.__class__.__name__} has no config."))
            self._trigger_computation()
            return

        self.form_layout.addRow(QLabel(f"<b>Editing: {operation.__class__.__name__}</b>"))

        for field_name, field_info in operation.config.model_fields.items():
            current_value = getattr(operation.config, field_name)
            
            # --- Handle Root Float Parameters ---
            if field_info.annotation == float:
                container = QWidget()
                h_layout = QHBoxLayout(container)
                h_layout.setContentsMargins(0, 0, 0, 0)

                slider = QSlider(Qt.Horizontal)
                slider.setMinimum(0)
                slider.setMaximum(1000)
                slider.setValue(int(current_value * 10)) 
                
                value_label = QLabel(f"{current_value:.1f}")
                value_label.setMinimumWidth(35)
                value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                
                h_layout.addWidget(slider)
                h_layout.addWidget(value_label)
                
                def update_wrapper(val, fname=field_name, idx=op_index, lbl=value_label):
                    real_val = val / 10.0
                    lbl.setText(f"{real_val:.1f}")
                    self.update_parameter(idx, fname, real_val)
                    
                slider.valueChanged.connect(update_wrapper)
                self.form_layout.addRow(field_name, container)

            # --- Dynamic Poly-morphic Nested Settings Section ---
            elif isinstance(current_value, dict) or field_info.annotation == dict or getattr(field_info.annotation, '__origin__', None) is dict:
                registry_key = None
                
                prefix = field_name.split('_')[0] if '_' in field_name else ""
                if prefix and hasattr(operation.config, prefix):
                    registry_key = getattr(operation.config, prefix)
                elif hasattr(operation.config, "generator"):
                    registry_key = getattr(operation.config, "generator")

                op_info = OPERATION_REGISTRY.get(registry_key) if registry_key else None
                
                if op_info and op_info["config"]:
                    sub_config_class = op_info["config"]
                    self.form_layout.addRow(QLabel(f"<br><i>Nested Context: {registry_key} ({field_name})</i>"))
                    
                    for sub_field_name, sub_field_info in sub_config_class.model_fields.items():
                        if sub_field_info.annotation == float:
                            sub_current_value = current_value.get(
                                sub_field_name, 
                                sub_field_info.default if sub_field_info.default is not None else 0.0
                            )
                            
                            sub_container = QWidget()
                            sub_h_layout = QHBoxLayout(sub_container)
                            sub_h_layout.setContentsMargins(0, 0, 0, 0)

                            sub_slider = QSlider(Qt.Horizontal)
                            sub_slider.setMinimum(0)
                            sub_slider.setMaximum(1000)
                            sub_slider.setValue(int(sub_current_value * 10)) 
                            
                            sub_value_label = QLabel(f"{sub_current_value:.1f}")
                            sub_value_label.setMinimumWidth(35)
                            sub_value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                            
                            sub_h_layout.addWidget(sub_slider)
                            sub_h_layout.addWidget(sub_value_label)
                            
                            def sub_update_wrapper(val, parent_dict=field_name, fname=sub_field_name, idx=op_index, lbl=sub_value_label):
                                real_val = val / 10.0
                                lbl.setText(f"{real_val:.1f}")
                                self.update_nested_parameter(idx, parent_dict, fname, real_val)
                                
                            sub_slider.valueChanged.connect(sub_update_wrapper)
                            self.form_layout.addRow(f"↳ {sub_field_name}", sub_container)
        
        # Trigger an update now that step UI is built
        self._trigger_computation()

    def update_parameter(self, op_index, field_name, new_value):
        operation = self.engine.runner.operations[op_index]
        current_val = getattr(operation.config, field_name)
        
        # Only backup if we aren't currently dragging/computing
        if self._backup_state is None or self._backup_state[1] != field_name:
            self._backup_state = (op_index, field_name, current_val)

        setattr(operation.config, field_name, new_value)
        
        self._pending_op_index = op_index
        self.debounce_timer.start()

    def update_nested_parameter(self, op_index, parent_dict_name, sub_field_name, new_value):
        operation = self.engine.runner.operations[op_index]
        
        if hasattr(operation.config, parent_dict_name):
            target_dict = getattr(operation.config, parent_dict_name)
            if isinstance(target_dict, dict):
                target_dict[sub_field_name] = new_value
                
                self._pending_op_index = op_index
                self.debounce_timer.start()

    def _execute_recalculation(self):
        """Fired by debounce timer; signals background thread to process the edit."""
        if self._pending_op_index is not None:
            self._trigger_computation(self._pending_op_index)
            self._pending_op_index = None

    def _load_live_recipe(self):
        """Prompts the user to select a YAML recipe, loads it, and refreshes the GUI."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Recipe", "", "YAML Files (*.yaml *.yml);;All Files (*)"
        )
        
        if not file_path:
            return

        try:
            with open(file_path, 'r') as f:
                new_recipe = yaml.safe_load(f)
                
            if not isinstance(new_recipe, list):
                logger.error("Invalid recipe format: must be a list of operations.")
                return

            # 1. Inject the new recipe into the engine
            success = self.engine.load_recipe(new_recipe)
            
            if success:
                # 2. Reset the viewer state to the end of the new pipeline
                self.viewer.current_step = len(self.engine.runner.operations)
                
                # 3. Rebuild the dynamic sliders for the current step (implicitly triggers computation)
                self.build_ui_for_current_step()
                
        except Exception as e:
            logger.error(f"Error loading recipe from {file_path}: {e}")

    def _export_live_gcode(self):
        """Prompts the user for a save location and exports the current final paths."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export G-Code", "output.nc", "G-Code Files (*.nc *.gcode);;All Files (*)"
        )
        
        if file_path:
            # We enforce a synchronous computation finish for exporting accurately
            self.engine.runner.recompute_from(0, len(self.engine.runner.operations))
            final_lines = self.engine.runner.get_final_lines()
            self.engine.export_gcode(lines=final_lines, output_path=file_path)

    def _save_live_recipe(self):
        """Serializes the current pipeline state back into a YAML recipe."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Recipe", "preset.yaml", "YAML Files (*.yaml *.yml);;All Files (*)"
        )
        
        if not file_path:
            return

        current_recipe = []
        
        for op in self.engine.runner.operations:
            op_name = next(
                (name for name, info in OPERATION_REGISTRY.items() if isinstance(op, info["class"])), 
                None
            )
            
            if not op_name:
                continue
                
            step = {"operation": op_name}
            if op.config:
                step["settings"] = op.config.model_dump()
                
            current_recipe.append(step)

        try:
            with open(file_path, 'w') as f:
                yaml.safe_dump(current_recipe, f, sort_keys=False, default_flow_style=False)
            logger.success(f"Recipe successfully saved to {file_path}")
        except Exception as e:
            logger.error(f"Failed to save recipe: {e}")


class PipelineViewer(scene.SceneCanvas):
    def __init__(self, engine):
        super().__init__(keys='interactive',
                         size=(800, 800),
                         title="Pendragon Pipeline Visualizer",
                         show=True)
        self.unfreeze()
        self.engine = engine
        self.current_step = min(1, len(self.engine.runner.operations))
        self.show_final_view = False

        self.on_step_changed = None
        self.on_close_requested = None
        self.on_stats_updated = None

        self.view = self.central_widget.add_view()
        self.view.camera = 'panzoom'
        self.view.camera.aspect = 1.0

        self.lines_visual = scene.visuals.Line(parent=self.view.scene, color='white')
        self.boundary_visual = scene.visuals.Line(parent=self.view.scene, color='red')
        self.vertices_visual = scene.visuals.Markers(parent=self.view.scene)

        self.vertices_visual.set_data(pos=np.array([[0.0, 0.0]], dtype=np.float32))
        self.vertices_visual.visible = False
        self.lines_visual.visible = False
        self.boundary_visual.visible = False

        self.freeze()
        
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
            if self.on_step_changed is not None:
                self.on_step_changed()

    def step_backward(self):
        if self.current_step > 0:
            self.current_step -= 1
            if self.on_step_changed is not None:
                self.on_step_changed()

    def on_key_press(self, event):
        if event.key.name == 'Right':
            self.step_forward()
        elif event.key.name == 'Left':
            self.step_backward()
        elif event.key.name == 'Escape':
            if self.on_close_requested is not None:
                self.on_close_requested()
            else:
                self.close()

    def render_state(self, state: PipelineState, display_step: int, total_ops: int, is_final: bool):
        """Re-renders the visualizer objects given an immutable PipelineState instance."""
        total_vertices = sum(len(line.coords) for line in state.lines)

        # Trigger HUD update callback
        if self.on_stats_updated:
            self.on_stats_updated(
                self.current_step, 
                total_ops, 
                state.operation_name, 
                len(state.lines), 
                total_vertices, 
                is_final
            )

        # Rendering Logic
        if state.boundary and not state.boundary.is_empty:
            polygons = []
            if isinstance(state.boundary, Polygon):
                polygons = [state.boundary]
            elif isinstance(state.boundary, MultiPolygon):
                polygons = list(state.boundary.geoms)

            b_pos = []
            b_connect = []
            b_idx = 0

            for poly in polygons:
                rings = [poly.exterior] + list(poly.interiors)
                for ring in rings:
                    coords = np.array(ring.coords)
                    b_pos.append(coords)
                    n_pts = len(coords)
                    for i in range(n_pts - 1):
                        b_connect.append([b_idx + i, b_idx + i + 1])
                    b_idx += n_pts

            if b_pos:
                stacked_b_pos = np.vstack(b_pos)
                self.boundary_visual.set_data(pos=stacked_b_pos, connect=np.array(b_connect))
                self.boundary_visual.visible = True
            else:
                self.boundary_visual.visible = False
        else:
            self.boundary_visual.visible = False

        if state.lines:
            pos = []
            connect = []
            idx = 0
            for line in state.lines:
                coords = np.array(line.coords)
                pos.append(coords)
                n_pts = len(coords)
                for i in range(n_pts - 1):
                    connect.append([idx + i, idx + i + 1])
                idx += n_pts
                
            stacked_pos = np.vstack(pos)
            
            self.lines_visual.set_data(pos=stacked_pos, connect=np.array(connect))
            self.lines_visual.visible = True
            
            self.vertices_visual.set_data(pos=stacked_pos, face_color='red', edge_color=None, size=10)
            self.vertices_visual.visible = True
        else:
            self.lines_visual.visible = False
            self.vertices_visual.visible = False
