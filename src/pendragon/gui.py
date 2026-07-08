from typing import List
import numpy as np
from shapely.geometry import Polygon, MultiPolygon
from vispy import scene

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSlider, QLabel, 
    QFormLayout, QApplication, QCheckBox, QGroupBox
)
from PyQt5.QtCore import Qt, QTimer

from pendragon.core.models import PipelineState


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
"""


class LiveEditorWindow(QMainWindow):
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

        # Dynamic form area for sliders
        self.dynamic_form_widget = QWidget()
        self.form_layout = QFormLayout(self.dynamic_form_widget)
        self.control_layout.addWidget(self.dynamic_form_widget)

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

        self.build_ui_for_current_step()
        self.viewer.update_view()  # Force initial stats update now that callbacks are bound

    def _on_view_mode_toggled(self, checked):
        """Swaps the viewer mode and forces a visual update."""
        self.viewer.show_final_view = checked
        self.viewer.update_view()

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
            return

        operation = self.engine.runner.operations[op_index]
        if not operation.config:
            self.form_layout.addRow(QLabel(f"{operation.__class__.__name__} has no config."))
            return

        self.form_layout.addRow(QLabel(f"<b>Editing: {operation.__class__.__name__}</b>"))

        for field_name, field_info in operation.config.model_fields.items():
            current_value = getattr(operation.config, field_name)
            
            if field_info.annotation == float:
                # 1. Create a container widget and horizontal layout
                container = QWidget()
                h_layout = QHBoxLayout(container)
                h_layout.setContentsMargins(0, 0, 0, 0)

                slider = QSlider(Qt.Horizontal)
                slider.setMinimum(0)
                slider.setMaximum(1000)
                slider.setValue(int(current_value * 10)) 
                
                # 2. Create the label to display the numerical value
                value_label = QLabel(f"{current_value:.1f}")
                value_label.setMinimumWidth(35)
                value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                
                # 3. Add both widgets to the row's layout
                h_layout.addWidget(slider)
                h_layout.addWidget(value_label)
                
                # 4. Use a closure to update both the engine state and the UI label
                def update_wrapper(val, fname=field_name, idx=op_index, lbl=value_label):
                    real_val = val / 10.0
                    lbl.setText(f"{real_val:.1f}")
                    self.update_parameter(idx, fname, real_val)
                    
                slider.valueChanged.connect(update_wrapper)
                
                # 5. Add the combined container to the form layout instead of just the slider
                self.form_layout.addRow(field_name, container)

    def update_parameter(self, op_index, field_name, new_value):
        operation = self.engine.runner.operations[op_index]
        setattr(operation.config, field_name, new_value)
        
        self._pending_op_index = op_index
        self.debounce_timer.start()

    def _execute_recalculation(self):
        if self._pending_op_index is not None:
            # Determine the calculation target based on view mode state
            target = len(self.engine.runner.operations) if self.viewer.show_final_view else self.viewer.current_step
            self.engine.runner.recompute_from(self._pending_op_index, target)
            self.viewer.update_view()


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

    def on_key_press(self, event):
        step_changed = False
        max_step = len(self.engine.runner.operations)
        
        if event.key.name == 'Right':
            if self.current_step < max_step:
                self.current_step += 1
                step_changed = True
        elif event.key.name == 'Left':
            if self.current_step > 0:
                self.current_step -= 1
                step_changed = True
        elif event.key.name == 'Escape':
            if self.on_close_requested is not None:
                self.on_close_requested()
            else:
                self.close()

        if step_changed:
            self.update_view()
            if self.on_step_changed is not None:
                self.on_step_changed()

    def update_view(self):
        # 1. Determine how far we need to compute based on the view mode
        target_step = len(self.engine.runner.operations) if self.show_final_view else self.current_step

        # 2. Lazily compute history if we haven't reached the required target step yet
        current_history_max = len(self.engine.runner.history) - 1
        if current_history_max < target_step:
            self.engine.runner.recompute_from(current_history_max, target_step)

        # 3. Fetch the appropriate state to display
        display_step = len(self.engine.runner.history) - 1 if self.show_final_view else self.current_step
        state = self.engine.runner.history[display_step]

        total_vertices = sum(len(line.coords) for line in state.lines)
        total_ops = len(self.engine.runner.operations)

        # 4. Trigger HUD update callback
        if self.on_stats_updated:
            self.on_stats_updated(
                self.current_step, 
                total_ops, 
                state.operation_name, 
                len(state.lines), 
                total_vertices, 
                self.show_final_view
            )

        # 5. Visual Rendering logic
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
