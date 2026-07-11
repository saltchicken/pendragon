from typing import get_args, get_origin, Any, Dict, List, Literal

from loguru import logger
import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication
from PyQt5.QtWidgets import QCheckBox
from PyQt5.QtWidgets import QFileDialog
from PyQt5.QtWidgets import QFormLayout
from PyQt5.QtWidgets import QGroupBox
from PyQt5.QtWidgets import QHBoxLayout
from PyQt5.QtWidgets import QLabel
from PyQt5.QtWidgets import QMainWindow
from PyQt5.QtWidgets import QPushButton
from PyQt5.QtWidgets import QSlider
from PyQt5.QtWidgets import QVBoxLayout
from PyQt5.QtWidgets import QWidget
from PyQt5.QtWidgets import QSpinBox
from PyQt5.QtWidgets import QLineEdit
from PyQt5.QtWidgets import QComboBox

from shapely.geometry import MultiPolygon
from shapely.geometry import Polygon
from vispy import scene
import yaml

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

        # Add this near your existing final_view_checkbox
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
        # ----------------------

        # --- Pipeline Editing Tools ---
        self.edit_layout = QHBoxLayout()
        
        self.op_selector = QComboBox()
        # Populate dropdown directly from the registry keys
        self.op_selector.addItems(sorted(OPERATION_REGISTRY.keys()))
        
        self.btn_add_op = QPushButton("Add Step")
        self.btn_remove_op = QPushButton("Remove Step")
        
        self.btn_add_op.clicked.connect(self._add_operation)
        self.btn_remove_op.clicked.connect(self._remove_operation)
        
        self.edit_layout.addWidget(self.op_selector, stretch=2)
        self.edit_layout.addWidget(self.btn_add_op, stretch=1)
        self.edit_layout.addWidget(self.btn_remove_op, stretch=1)
        
        self.control_layout.addLayout(self.edit_layout)
        # -----------------------------------

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

    def _on_vertices_toggled(self, checked):
        """Updates the visibility of vertices in the viewer."""
        self.viewer.show_vertices = checked
        self.viewer.update_view()

    def update_stats_ui(self, step, total_ops, op_name, lines, vertices,
                        final_view):
        """Updates the discrete PyQt labels for pipeline statistics."""
        step_text = f"{step} / {total_ops}"
        if final_view:
            step_text += " (FINAL VIEW)"

        self.step_label.setText(step_text)
        self.op_label.setText(str(op_name))
        self.lines_label.setText(str(lines))
        self.vertices_label.setText(str(vertices))

    def build_ui_for_current_step(self):
        # 1. Safely obliterate the old layout container and start fresh
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

            # --- Handle Float Parameters (Existing Logic) ---
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

                def update_float_wrapper(val, fname=field_name, idx=op_index, lbl=value_label):
                    real_val = val / 10.0
                    lbl.setText(f"{real_val:.1f}")
                    self.update_parameter(idx, fname, real_val)

                slider.valueChanged.connect(update_float_wrapper)
                self.form_layout.addRow(field_name, container)

            # --- Handle Integer Parameters ---
            elif field_info.annotation == int:
                container = QWidget()
                h_layout = QHBoxLayout(container)
                h_layout.setContentsMargins(0, 0, 0, 0)

                spin_box = QSpinBox()
                spin_box.setRange(0, 10000) # Give it a generous default range
                # If current_value is None for some reason, default to 0 to prevent crashes
                spin_box.setValue(int(current_value) if current_value is not None else 0)

                def update_int_wrapper(val, fname=field_name, idx=op_index):
                    self.update_parameter(idx, fname, val)

                spin_box.valueChanged.connect(update_int_wrapper)
                
                h_layout.addWidget(spin_box)
                self.form_layout.addRow(field_name, container)

            # --- Handle Boolean Parameters ---
            elif field_info.annotation == bool:
                container = QWidget()
                h_layout = QHBoxLayout(container)
                h_layout.setContentsMargins(0, 0, 0, 0)

                checkbox = QCheckBox()
                checkbox.setChecked(bool(current_value))

                def update_bool_wrapper(state, fname=field_name, idx=op_index):
                    # state is an int (0 for unchecked, 2 for checked), bool() converts it safely
                    self.update_parameter(idx, fname, bool(state))

                checkbox.stateChanged.connect(update_bool_wrapper)
                
                h_layout.addWidget(checkbox)
                self.form_layout.addRow(field_name, container)

            elif origin is Literal:
                container = QWidget()
                h_layout = QHBoxLayout(container)
                h_layout.setContentsMargins(0, 0, 0, 0)

                combo_box = QComboBox()
                
                # get_args extracts the allowed values from the Literal
                allowed_options = get_args(field_info.annotation)
                
                combo_box.blockSignals(True)
                combo_box.addItems([str(opt) for opt in allowed_options])

                # Set the current active text
                if current_value in allowed_options:
                    combo_box.setCurrentText(str(current_value))
                elif allowed_options:
                    combo_box.setCurrentText(str(allowed_options[0]))
                
                combo_box.blockSignals(False)

                def update_literal_wrapper(text, fname=field_name, idx=op_index):
                    self.update_parameter(idx, fname, text)

                # currentTextChanged fires whenever the user selects a new dropdown option
                combo_box.currentTextChanged.connect(update_literal_wrapper)
                
                h_layout.addWidget(combo_box)
                self.form_layout.addRow(field_name, container)

            # --- Handle String Parameters ---
            elif field_info.annotation == str:
                container = QWidget()
                h_layout = QHBoxLayout(container)
                h_layout.setContentsMargins(0, 0, 0, 0)
                
                schema_extra = field_info.json_schema_extra or {}
                widget_type = schema_extra.get("widget")

                # Shared updater 
                def update_value(text, fname=field_name, idx=op_index, wtype=widget_type):
                    op = self.engine.runner.operations[idx]
                    
                    if getattr(op.config, fname) == text:
                        return
                        
                    self.update_parameter(idx, fname, text)

                    if wtype == "operation_selector":
                        settings_key = f"{fname}_settings"
                        if hasattr(op.config, settings_key):
                            setattr(op.config, settings_key, {})
                        
                        QTimer.singleShot(0, self.build_ui_for_current_step)

                # 1. Custom Operation Selector Dropdown
                if widget_type == "operation_selector":
                    widget = QComboBox()
                    
                    widget.blockSignals(True)
                    widget.addItems(sorted(OPERATION_REGISTRY.keys()))
                    if current_value:
                        widget.setCurrentText(str(current_value))
                    widget.blockSignals(False)
                    
                    widget.currentTextChanged.connect(update_value)
                    h_layout.addWidget(widget)

                # 2. Standard Text Box / File Picker
                else:
                    widget = QLineEdit(str(current_value or ""))
                    widget.textChanged.connect(update_value)
                    h_layout.addWidget(widget)
                    
                    if widget_type == "file_picker":
                        browse_btn = QPushButton("Browse...")
                        
                        def open_file_dialog(checked=False, le=widget):
                            file_path, _ = QFileDialog.getOpenFileName(
                                self, 
                                f"Select {field_name}", 
                                "", 
                                "Images (*.png *.jpg *.jpeg);;All Files (*)"
                            )
                            if file_path:
                                le.setText(file_path)

                        browse_btn.clicked.connect(open_file_dialog)
                        h_layout.addWidget(browse_btn)

                self.form_layout.addRow(field_name, container)

            # --- Dynamic Poly-morphic Nested Settings Section ---
            elif isinstance(current_value, dict) or field_info.annotation == dict or getattr(field_info.annotation, '__origin__', None) is dict:
                # Infer what the target sub-registry schema is by checking adjacent sibling attributes
                # e.g., if we are looking at generator_settings, check if self.config.generator exists.
                registry_key = None

                # Dynamic inference strategy: Look for a field named like the root prefix (e.g. "generator")
                prefix = field_name.split('_')[0] if '_' in field_name else ""
                if prefix and hasattr(operation.config, prefix):
                    registry_key = getattr(operation.config, prefix)
                elif hasattr(operation.config,
                             "generator"):  # Fallback standard
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
                            # Safely capture current map value or use the fallback default
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

                            # Closure passes the targeted container dictionary name dynamically
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

        self._pending_op_index = op_index
        self.debounce_timer.start()

    def update_nested_parameter(self, op_index, parent_dict_name,
                                sub_field_name, new_value):
        operation = self.engine.runner.operations[op_index]

        if hasattr(operation.config, parent_dict_name):
            target_dict = getattr(operation.config, parent_dict_name)
            if isinstance(target_dict, dict):
                target_dict[sub_field_name] = new_value

                self._pending_op_index = op_index
                self.debounce_timer.start()

    def _execute_recalculation(self):
        if self._pending_op_index is not None:
            # Determine the calculation target based on view mode state
            target = len(
                self.engine.runner.operations
            ) if self.viewer.show_final_view else self.viewer.current_step
            self.engine.runner.recompute_from(self._pending_op_index, target)
            self.viewer.update_view()

    def _get_current_recipe(self) -> list:
        """Extracts the live operation list back into a dictionary recipe."""
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
        """Loads a new recipe and securely transitions the UI/viewer state."""
        success = self.engine.load_recipe(new_recipe)
        if success:
            # Clamp the target step to ensure we don't go out of bounds
            max_step = len(self.engine.runner.operations)
            self.viewer.current_step = max(0, min(target_step, max_step))
            
            self.build_ui_for_current_step()
            self.viewer.update_view()

    def _add_operation(self):
        """Inserts a new default operation after the current step."""
        op_name = self.op_selector.currentText()
        if not op_name:
            return
            
        recipe = self._get_current_recipe()
        insert_idx = self.viewer.current_step
        
        # Insert a fresh operation with default settings
        recipe.insert(insert_idx, {"operation": op_name, "settings": {}})
        
        # Reload and step forward into the new operation
        self._reload_pipeline(recipe, target_step=insert_idx + 1)

    def _remove_operation(self):
        """Removes the currently viewed operation from the pipeline."""
        recipe = self._get_current_recipe()
        remove_idx = self.viewer.current_step - 1
        
        if 0 <= remove_idx < len(recipe):
            recipe.pop(remove_idx)
            # Reload and step back to the previous operation
            self._reload_pipeline(recipe, target_step=max(0, remove_idx))

    def _load_live_recipe(self):
        """Prompts the user to select a YAML recipe, loads it, and refreshes the GUI."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Recipe", "", "YAML Files (*.yaml *.yml);;All Files (*)")

        if not file_path:
            return

        try:
            with open(file_path, 'r') as f:
                new_recipe = yaml.safe_load(f)

            # Basic validation to ensure it matches the current expected schema
            if not isinstance(new_recipe, list):
                logger.error(
                    "Invalid recipe format: must be a list of operations.")
                return

            # 1. Inject the new recipe into the engine
            success = self.engine.load_recipe(new_recipe)

            if success:
                # 2. Reset the viewer state to the end of the new pipeline
                self.viewer.current_step = len(self.engine.runner.operations)

                # 3. Rebuild the dynamic sliders for the current step
                self.build_ui_for_current_step()

                # 4. Force Vispy to recalculate and redraw the canvas
                self.viewer.update_view()

        except Exception as e:
            logger.error(f"Error loading recipe from {file_path}: {e}")

    def _export_live_gcode(self):
        """Prompts the user for a save location and exports the current final paths."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export G-Code", "output.nc",
            "G-Code Files (*.nc *.gcode);;All Files (*)")

        if file_path:
            # Ensure the pipeline is fully computed to the end
            self.engine.runner.recompute_from(
                0, len(self.engine.runner.operations))
            final_lines = self.engine.runner.get_final_lines()
            self.engine.export_gcode(lines=final_lines, output_path=file_path)

    def _save_live_recipe(self):
        """Serializes the current pipeline state back into a YAML recipe."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Recipe", "preset.yaml",
            "YAML Files (*.yaml *.yml);;All Files (*)")

        if not file_path:
            return

        current_recipe = self._get_current_recipe()

        # Write the reconstructed recipe to disk
        try:
            with open(file_path, 'w') as f:
                yaml.safe_dump(current_recipe,
                               f,
                               sort_keys=False,
                               default_flow_style=False)
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
        
        # Hide them initially. update_view() will reveal them when data exists.
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

    def update_view(self):
        # 1. Determine how far we need to compute based on the view mode
        target_step = len(self.engine.runner.operations
                          ) if self.show_final_view else self.current_step

        # 2. Lazily compute history if we haven't reached the required target step yet
        current_history_max = len(self.engine.runner.history) - 1
        if current_history_max < target_step:
            self.engine.runner.recompute_from(current_history_max, target_step)

        # 3. Fetch the appropriate state to display
        display_step = len(self.engine.runner.history
                           ) - 1 if self.show_final_view else self.current_step
        state = self.engine.runner.history[display_step]

        total_vertices = sum(len(line.coords) for line in state.lines)
        total_ops = len(self.engine.runner.operations)

        # 4. Trigger HUD update callback
        if self.on_stats_updated:
            self.on_stats_updated(self.current_step,
                                  total_ops, state.operation_name,
                                  len(state.lines), total_vertices,
                                  self.show_final_view)

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
                self.boundary_visual.set_data(pos=stacked_b_pos,
                                              connect=np.array(b_connect))
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

            self.lines_visual.set_data(pos=stacked_pos,
                                       connect=np.array(connect))
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
