# src/pendragon/core/engine.py

from typing import List, Optional

from loguru import logger
import numpy as np
from shapely.geometry import LineString
from shapely.geometry import Polygon, MultiPolygon
from vispy import app
from vispy import scene

from pendragon.core.models import PipelineState
from pendragon.core.registry import OPERATION_REGISTRY

from .pen import PenConfig
from .pen import PenTool
from .runner import PipelineRunner

from PyQt5.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSlider, QLabel, QFormLayout, QApplication
from PyQt5.QtCore import Qt, QTimer

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

        # TODO: Us there a better way to handle this so I don't need self.on_step_changed = None in PipelineViewer
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
        # Clear existing widgets in the form layout
        while self.form_layout.count():
            child = self.form_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # The viewer's current_step maps to the history index.
        # history index 1 corresponds to operation 0.
        op_index = self.viewer.current_step - 1 
        if op_index < 0 or op_index >= len(self.engine.runner.operations):
            self.form_layout.addRow(QLabel("No configurable parameters for this state."))
            return

        operation = self.engine.runner.operations[op_index]
        if not operation.config:
            self.form_layout.addRow(QLabel(f"{operation.__class__.__name__} has no config."))
            return

        self.form_layout.addRow(QLabel(f"<b>Editing: {operation.__class__.__name__}</b>"))

        # Introspect Pydantic model
        for field_name, field_info in operation.config.model_fields.items():
            current_value = getattr(operation.config, field_name)
            
            # Handle float parameters with a slider
            if field_info.annotation == float:
                slider = QSlider(Qt.Horizontal)
                slider.setMinimum(0)
                slider.setMaximum(1000) # You'd scale this based on expected ranges
                slider.setValue(int(current_value * 10)) 
                
                # Connect slider movement to our update function
                slider.valueChanged.connect(
                    lambda val, fname=field_name, idx=op_index: self.update_parameter(idx, fname, val / 10.0)
                )
                self.form_layout.addRow(field_name, slider)
            
            # You can add elif blocks here for int (QSpinBox), str (QLineEdit), etc.


    def update_parameter(self, op_index, field_name, new_value):
        """Updates the internal config immediately, but defers the heavy computation."""
        # 1. Update the Pydantic config
        operation = self.engine.runner.operations[op_index]
        setattr(operation.config, field_name, new_value)
        
        # 2. Queue the recalculation and restart the debounce timer
        self._pending_op_index = op_index
        self.debounce_timer.start()


    def _execute_recalculation(self):
        """Executes the pipeline re-run when the debounce timer times out."""
        if self._pending_op_index is not None:
            # 1. Trigger partial re-run from this operation onwards
            self.engine.runner.recompute_from(self._pending_op_index)
            
            # 2. Refresh the viewer
            self.viewer.history = self.engine.runner.history
            self.viewer.update_view()


class PipelineViewer(scene.SceneCanvas):

    def __init__(self, history: List[PipelineState]):
        # Keep window title clean and static
        super().__init__(keys='interactive',
                         size=(800, 800),
                         title="Pendragon Pipeline Visualizer",
                         show=True)
        self.unfreeze()
        self.history = history
        # Start on second step (index 1), or step 0 if there are no operations
        self.current_step = min(1, len(self.history) - 1)

        self.on_step_changed = None
        self.on_close_requested = None

        # Setup view and camera
        self.view = self.central_widget.add_view()
        self.view.camera = 'panzoom'
        self.view.camera.aspect = 1.0

        # Geometry visuals
        self.lines_visual = scene.visuals.Line(parent=self.view.scene,
                                               color='white')
        self.boundary_visual = scene.visuals.Line(parent=self.view.scene,
                                                  color='red')
        self.vertices_visual = scene.visuals.Markers(parent=self.view.scene)

        # Screen-space Text HUD for current step metrics
        # Parented directly to the canvas widget so it stays fixed in place during pan/zoom
        self.hud_text = scene.visuals.Text(
            text="",
            parent=self.central_widget,
            color='yellow',
            font_size=11,
            anchor_x='left',
            anchor_y='top',
            pos=(15, 15)  # Offset slightly from top-left corner
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

        # Calculate totals
        total_vertices = sum(len(line.coords) for line in state.lines)

        # Construct single-line textbox string
        hud_string = (f"Step: {self.current_step + 1}/{len(self.history)} | "
                      f"Operation: {state.operation_name} | "
                      f"Lines: {len(state.lines)} | "
                      f"Vertices: {total_vertices}")
        self.hud_text.text = hud_string

        # --- NEW BOUNDARY RENDERING LOGIC ---
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
                # Grab the exterior perimeter + any internal holes
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
                self.boundary_visual.set_data(pos=stacked_b_pos,
                                              connect=np.array(b_connect))
                self.boundary_visual.visible = True
            else:
                self.boundary_visual.visible = False
        else:
            self.boundary_visual.visible = False
        # ------------------------------------

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
                
            # Stack the positions once so we can use them for both lines and markers
            stacked_pos = np.vstack(pos)
            
            self.lines_visual.set_data(pos=stacked_pos,
                                       connect=np.array(connect))
            self.lines_visual.visible = True
            
            # Update the vertices visual
            self.vertices_visual.set_data(pos=stacked_pos, 
                                          face_color='red', 
                                          edge_color=None, 
                                          size=10)
            self.vertices_visual.visible = True
        else:
            self.lines_visual.visible = False
            self.vertices_visual.visible = False


class PendragonEngine:

    def __init__(self, recipe: list, boundary: Optional[Polygon] = None):
        """
        Initializes the engine with a recipe and an optional boundary.
        """
        self.recipe = recipe
        self.boundary = boundary or Polygon([(0, 0), (200, 0), (200, 200),
                                             (0, 200), (0, 0)])

        initial_state = PipelineState(boundary=self.boundary,
                                      operation_name="base_geometry")
        self.runner = PipelineRunner(initial_state)

    def build_pipeline(self) -> bool:
        """
        Validates the recipe and queues up the configured plugin operations.
        Returns True if successful, False if validation fails.
        """
        for step in self.recipe:
            op_name = step.get("operation")
            if not op_name:
                logger.error(
                    f"Invalid step configuration, missing 'operation' key: {step}"
                )
                return False

            op_info = OPERATION_REGISTRY.get(op_name)
            if not op_info:
                logger.error(f"Operation '{op_name}' not found in registry.")
                return False

            PluginClass = op_info["class"]
            ConfigClass = op_info["config"]

            validated_config = None
            if ConfigClass:
                try:
                    validated_config = ConfigClass(**step.get("settings", {}))
                    logger.success(
                        f"Successfully validated config for {op_name}")
                except Exception as e:
                    logger.error(f"Configuration error for '{op_name}': {e}")
                    return False

            plugin_instance = PluginClass(config=validated_config)
            self.runner.add_operation(plugin_instance)

        return True

    def run(self) -> List[LineString]:
        """
        Executes the pipeline sequentially and returns the final geometries.
        """
        self.runner.execute_all()
        return self.runner.get_final_lines()

    def export_gcode(self,
                     lines: List[LineString],
                     output_path: str,
                     pen_config: Optional[PenConfig] = None):
        """
        Translates LineStrings into G-code using the PenTool context manager.
        """
        if not lines:
            logger.warning("No lines to export!")
            return

        config = pen_config or PenConfig()
        logger.info(f"Generating G-code to {output_path}...")

        with PenTool(config=config, output_filename=output_path) as pen:
            for line in lines:
                points = list(line.coords)
                pen.draw_path(points)

    def visualize(self):
        """Renders the pipeline history in an interactive PyQt/Vispy window."""
        if not self.runner.history:
            logger.warning("No pipeline history to visualize!")
            return

        logger.info("Opening live editor visualization window...")

        # Initialize Qt App
        qt_app = QApplication.instance() or QApplication([])
        
        self.editor = LiveEditorWindow(self)
        self.editor.resize(1200, 800)
        self.editor.show()
        
        qt_app.exec_()
