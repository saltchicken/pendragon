# src/pendragon/gui.py

from typing import List

import numpy as np
from shapely.geometry import Polygon, MultiPolygon
from vispy import scene

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QSlider, QLabel, QFormLayout, QApplication
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
        
        # Central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # 1. The Vispy Canvas (Left Side)
        self.viewer = PipelineViewer(self.engine.runner.history)
        main_layout.addWidget(self.viewer.native, stretch=3)

        # 2. Parameter Control Panel (Right Side)
        self.control_panel = QWidget()
        self.form_layout = QFormLayout(self.control_panel)
        main_layout.addWidget(self.control_panel, stretch=1)

        self.viewer.on_step_changed = self.build_ui_for_current_step
        self.viewer.on_close_requested = self.close
        
        # --- Debounce Timer Setup ---
        self.debounce_timer = QTimer()
        self.debounce_timer.setSingleShot(True)
        self.debounce_timer.setInterval(300)  # 300ms delay
        self.debounce_timer.timeout.connect(self._execute_recalculation)
        self._pending_op_index = None
        # ----------------------------

        # Build initial UI for the current step
        self.build_ui_for_current_step()


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
                slider = QSlider(Qt.Horizontal)
                slider.setMinimum(0)
                slider.setMaximum(1000)
                slider.setValue(int(current_value * 10)) 
                
                slider.valueChanged.connect(
                    lambda val, fname=field_name, idx=op_index: self.update_parameter(idx, fname, val / 10.0)
                )
                self.form_layout.addRow(field_name, slider)


    def update_parameter(self, op_index, field_name, new_value):
        operation = self.engine.runner.operations[op_index]
        setattr(operation.config, field_name, new_value)
        
        self._pending_op_index = op_index
        self.debounce_timer.start()


    def _execute_recalculation(self):
        if self._pending_op_index is not None:
            self.engine.runner.recompute_from(self._pending_op_index)
            self.viewer.history = self.engine.runner.history
            self.viewer.update_view()


class PipelineViewer(scene.SceneCanvas):
    def __init__(self, history: List[PipelineState]):
        super().__init__(keys='interactive',
                         size=(800, 800),
                         title="Pendragon Pipeline Visualizer",
                         show=True)
        self.unfreeze()
        self.history = history
        self.current_step = min(1, len(self.history) - 1)

        self.on_step_changed = None
        self.on_close_requested = None

        self.view = self.central_widget.add_view()
        self.view.camera = 'panzoom'
        self.view.camera.aspect = 1.0

        self.lines_visual = scene.visuals.Line(parent=self.view.scene, color='white')
        self.boundary_visual = scene.visuals.Line(parent=self.view.scene, color='red')
        self.vertices_visual = scene.visuals.Markers(parent=self.view.scene)

        self.hud_text = scene.visuals.Text(
            text="",
            parent=self.central_widget,
            color='yellow',
            font_size=11,
            anchor_x='left',
            anchor_y='top',
            pos=(15, 15) 
        )

        self.freeze()
        self.update_view()
        
        if self.history and self.history[0].boundary:
            minx, miny, maxx, maxy = self.history[0].boundary.bounds
            self.view.camera.set_range(x=(minx, maxx), y=(miny, maxy))
        else:
            try:
                self.view.camera.set_range()
            except ValueError:
                pass

    def on_key_press(self, event):
        step_changed = False
        
        if event.key.name == 'Right':
            if self.current_step < len(self.history) - 1:
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
        state = self.history[self.current_step]

        total_vertices = sum(len(line.coords) for line in state.lines)

        hud_string = (f"Step: {self.current_step + 1}/{len(self.history)} | "
                      f"Operation: {state.operation_name} | "
                      f"Lines: {len(state.lines)} | "
                      f"Vertices: {total_vertices}")
        self.hud_text.text = hud_string

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
