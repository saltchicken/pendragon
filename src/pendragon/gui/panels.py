from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QComboBox
from PyQt5.QtWidgets import QFormLayout
from PyQt5.QtWidgets import QGroupBox
from PyQt5.QtWidgets import QHBoxLayout
from PyQt5.QtWidgets import QLabel
from PyQt5.QtWidgets import QProgressBar
from PyQt5.QtWidgets import QPushButton
from PyQt5.QtWidgets import QWidget

from pendragon.gui.widgets import WidgetFactory


class StatsPanel(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Pipeline Statistics", parent)
        layout = QFormLayout(self)
        self.step_label = QLabel("-")
        self.op_label = QLabel("-")
        self.lines_label = QLabel("-")
        self.vertices_label = QLabel("-")
        layout.addRow("Step:", self.step_label)
        layout.addRow("Operation:", self.op_label)
        layout.addRow("Lines:", self.lines_label)
        layout.addRow("Vertices:", self.vertices_label)

    def update_stats(self, step: int, total_ops: int, op_name: str, lines: int,
                     vertices: int, final_view: bool):
        step_text = f"{step} / {total_ops}"
        if final_view:
            step_text += " (FINAL VIEW)"
        self.step_label.setText(step_text)
        self.op_label.setText(str(op_name))
        self.lines_label.setText(str(lines))
        self.vertices_label.setText(str(vertices))


class ProgressPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.bar = QProgressBar()
        self.bar.setValue(0)
        self.bar.setTextVisible(True)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setStyleSheet(
            "background-color: #8b0000; font-weight: bold;")
        layout.addWidget(self.bar)
        layout.addWidget(self.btn_cancel)


class ActionPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.btn_load = QPushButton("Load Recipe")
        self.btn_save = QPushButton("Save Recipe")
        self.btn_export = QPushButton("Export G-Code")
        layout.addWidget(self.btn_load)
        layout.addWidget(self.btn_save)
        layout.addWidget(self.btn_export)


class EditPanel(QWidget):
    def __init__(self, op_names: list[str], parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.op_selector = QComboBox()
        self.op_selector.addItems(op_names)
        self.btn_add = QPushButton("Add Step")
        self.btn_remove = QPushButton("Remove Step")
        layout.addWidget(self.op_selector, stretch=2)
        layout.addWidget(self.btn_add, stretch=1)
        layout.addWidget(self.btn_remove, stretch=1)


class PropertiesPanel(QWidget):
    """Encapsulates the dynamic Pydantic schema reflection and UI generation."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.form_layout = QFormLayout(self)
        self.form_layout.setContentsMargins(0, 0, 0, 0)

    def rebuild_for_step(self, current_step: int):
        while self.form_layout.count():
            child = self.form_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        op_index = current_step - 1
        if op_index < 0 or op_index >= self.controller.engine.get_operation_count():
            self.form_layout.addRow(QLabel("No configurable parameters for this state."))
            return

        operation = self.controller.engine.get_operation(op_index)
        if not operation or not operation.config:
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
            
            if isinstance(current_value, dict) or field_info.annotation == dict or getattr(field_info.annotation, '__origin__', None) is dict:
                registry_key = None
                prefix = field_name.split('_')[0] if '_' in field_name else ""
                if prefix and hasattr(operation.config, prefix):
                    registry_key = getattr(operation.config, prefix)
                elif hasattr(operation.config, "generator"):
                    registry_key = getattr(operation.config, "generator")

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

            schema_extra = field_info.json_schema_extra or {}
            widget_type = schema_extra.get("widget")

            if field_info.annotation == str:
                def root_update_callback(text, fname=field_name, idx=op_index, wtype=widget_type):
                    op = self.controller.engine.get_operation(idx)
                    if op and getattr(op.config, fname) == text:
                        return
                    self.controller.update_parameter(idx, fname, text)
                    
                    if wtype == "operation_selector" and op:
                        settings_key = f"{fname}_settings"
                        if hasattr(op.config, settings_key):
                            setattr(op.config, settings_key, {})
                        QTimer.singleShot(0, lambda: self.rebuild_for_step(current_step))
            else:
                def root_update_callback(val, fname=field_name, idx=op_index):
                    self.controller.update_parameter(idx, fname, val)

            container = WidgetFactory.build_field_widget(
                field_name, field_info, current_value, root_update_callback, 
                registry=self.controller.engine.registry, parent=self
            )
            if container:
                self.form_layout.addRow(field_name, container)
