from functools import partial

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
        self._clear_layout()

        op_index = current_step - 1
        if not self._is_valid_operation(op_index):
            return

        operation = self.controller.get_operation(op_index)
        self.form_layout.addRow(
            QLabel(f"<b>Editing: {operation.__class__.__name__}</b>"))

        # --- PLUGIN UI DELEGATION HOOK ---
        if hasattr(operation, "build_custom_ui"):
            custom_widget = operation.build_custom_ui(self, op_index)
            if custom_widget:
                self.form_layout.addRow(custom_widget)
            return
        # ---------------------------------

        self._build_pydantic_ui(operation, op_index)

    def _clear_layout(self):
        while self.form_layout.count():
            child = self.form_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _is_valid_operation(self, op_index: int) -> bool:
        if op_index < 0 or op_index >= self.controller.get_operation_count():
            self.form_layout.addRow(
                QLabel("No configurable parameters for this state."))
            return False

        operation = self.controller.get_operation(op_index)
        if not operation or not operation.config:
            self.form_layout.addRow(
                QLabel(f"{operation.__class__.__name__} has no config."))
            return False

        return True

    def _build_pydantic_ui(self, operation, op_index: int):
        for field_name, field_info in operation.config.model_fields.items():
            current_value = getattr(operation.config, field_name)

            is_nested_dict = (isinstance(current_value, dict) or
                              field_info.annotation == dict or
                              getattr(field_info.annotation, '__origin__',
                                      None) is dict)

            if is_nested_dict:
                self._build_nested_fields(operation, op_index, field_name,
                                          current_value)
            else:
                self._build_standard_field(operation, op_index, field_name,
                                           field_info, current_value)

    def _build_nested_fields(self, operation, op_index: int, field_name: str,
                             current_value: dict):
        registry_key = None
        prefix = field_name.split('_')[0] if '_' in field_name else ""

        if prefix and hasattr(operation.config, prefix):
            registry_key = getattr(operation.config, prefix)
        elif hasattr(operation.config, "generator"):
            registry_key = getattr(operation.config, "generator")

        op_info = self.controller.get_operation_info(
            registry_key) if registry_key else None

        if op_info and op_info["config"]:
            sub_config_class = op_info["config"]
            self.form_layout.addRow(
                QLabel(
                    f"<br><i>Nested Context: {registry_key} ({field_name})</i>")
            )

            for sub_field_name, sub_field_info in sub_config_class.model_fields.items(
            ):
                sub_current_value = current_value.get(
                    sub_field_name, sub_field_info.default
                    if sub_field_info.default is not None else 0.0)

                update_cb = partial(self.controller.update_nested_parameter,
                                    op_index, field_name, sub_field_name)

                sub_container = WidgetFactory.build_field_widget(
                    sub_field_name,
                    sub_field_info,
                    sub_current_value,
                    update_cb,
                    registry=self.controller.engine.registry,
                    parent=self)
                if sub_container:
                    self.form_layout.addRow(f"↳ {sub_field_name}",
                                            sub_container)

    def _build_standard_field(self, operation, op_index: int, field_name: str,
                              field_info, current_value):
        schema_extra = field_info.json_schema_extra or {}
        widget_type = schema_extra.get("widget")

        if field_info.annotation == str:
            update_cb = partial(self._handle_string_update, op_index,
                                field_name, widget_type)
        else:
            update_cb = partial(self.controller.update_parameter, op_index,
                                field_name)

        container = WidgetFactory.build_field_widget(
            field_name,
            field_info,
            current_value,
            update_cb,
            registry=self.controller.engine.registry,
            parent=self)

        if container:
            self.form_layout.addRow(field_name, container)

    def _handle_string_update(self, op_index: int, field_name: str,
                              widget_type: str, text: str):
        op = self.controller.get_operation(op_index)
        if op and getattr(op.config, field_name) == text:
            return

        self.controller.update_parameter(op_index, field_name, text)

        if widget_type == "operation_selector" and op:
            settings_key = f"{field_name}_settings"
            if hasattr(op.config, settings_key):
                setattr(op.config, settings_key, {})
            # Current step is op_index + 1
            QTimer.singleShot(0, partial(self.rebuild_for_step, op_index + 1))
