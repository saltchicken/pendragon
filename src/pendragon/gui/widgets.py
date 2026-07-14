from functools import partial
from typing import get_args, get_origin, Literal

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QCheckBox
from PyQt5.QtWidgets import QComboBox
from PyQt5.QtWidgets import QDoubleSpinBox
from PyQt5.QtWidgets import QFileDialog
from PyQt5.QtWidgets import QHBoxLayout
from PyQt5.QtWidgets import QLabel
from PyQt5.QtWidgets import QLineEdit
from PyQt5.QtWidgets import QPushButton
from PyQt5.QtWidgets import QSlider
from PyQt5.QtWidgets import QSpinBox
from PyQt5.QtWidgets import QWidget


class WidgetFactory:
    """A factory for creating standardized PyQt UI widgets from Pydantic fields."""

    @classmethod
    def build_field_widget(cls, field_name, field_info, current_value, update_callback, registry=None, parent=None):
        origin = get_origin(field_info.annotation)
        annotation = field_info.annotation

        if origin is Literal:
            return cls.build_literal_widget(current_value, field_info, update_callback)

        dispatch_table = {
            float: partial(cls.build_float_widget, current_value, field_info, update_callback),
            int: partial(cls.build_int_widget, current_value, update_callback),
            bool: partial(cls.build_bool_widget, current_value, update_callback),
            str: partial(cls.build_str_widget, field_name, field_info, current_value, update_callback, registry, parent)
        }

        builder = dispatch_table.get(annotation)
        if builder:
            return builder()
        
        return None

    @staticmethod
    def _update_float_label(val, lbl, v_min, r_span):
        real_val = v_min + (val / 100.0) * r_span
        lbl.setText(f"{real_val:.2f}")

    @staticmethod
    def _update_float_value(val, lbl, v_min, r_span, cb):
        real_val = v_min + (val / 100.0) * r_span
        lbl.setText(f"{real_val:.2f}")
        cb(real_val)

    @staticmethod
    def build_float_widget(current_value, field_info, update_callback):
        container = QWidget()
        h_layout = QHBoxLayout(container)
        h_layout.setContentsMargins(0, 0, 0, 0)

        val_min = None
        val_max = None
        for m in field_info.metadata:
            if hasattr(m, 'ge'):
                val_min = m.ge
            if hasattr(m, 'le'):
                val_max = m.le

        if val_min is not None and val_max is not None:
            slider = QSlider(Qt.Horizontal)
            slider.setMinimum(0)
            slider.setMaximum(100)
            slider.setTracking(False)

            range_span = val_max - val_min if val_max > val_min else 1.0
            clamped_val = max(val_min, min(val_max, current_value))
            current_percent = int(((clamped_val - val_min) / range_span) * 100)
            slider.setValue(current_percent)

            value_label = QLabel(f"{clamped_val:.2f}")
            value_label.setMinimumWidth(35)
            value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

            slider.sliderMoved.connect(
                partial(WidgetFactory._update_float_label, lbl=value_label, v_min=val_min, r_span=range_span)
            )
            slider.valueChanged.connect(
                partial(WidgetFactory._update_float_value, lbl=value_label, v_min=val_min, r_span=range_span, cb=update_callback)
            )
            
            h_layout.addWidget(slider)
            h_layout.addWidget(value_label)

        else:
            spin_box = QDoubleSpinBox()
            spin_box.setRange(-10000.0, 10000.0)
            spin_box.setDecimals(2)
            spin_box.setSingleStep(0.1)
            spin_box.setValue(current_value)
            spin_box.setKeyboardTracking(False)

            # DoubleSpinBox valueChanged emits a float directly
            spin_box.valueChanged.connect(update_callback)
            h_layout.addWidget(spin_box)

        return container

    @staticmethod
    def build_int_widget(current_value, update_callback):
        container = QWidget()
        h_layout = QHBoxLayout(container)
        h_layout.setContentsMargins(0, 0, 0, 0)

        spin_box = QSpinBox()
        spin_box.setRange(0, 10000)
        spin_box.setValue(int(current_value) if current_value is not None else 0)

        # Spinbox valueChanged emits an int directly
        spin_box.valueChanged.connect(update_callback)

        h_layout.addWidget(spin_box)
        return container

    @staticmethod
    def _update_bool_value(state, cb):
        cb(bool(state))

    @staticmethod
    def build_bool_widget(current_value, update_callback):
        container = QWidget()
        h_layout = QHBoxLayout(container)
        h_layout.setContentsMargins(0, 0, 0, 0)

        checkbox = QCheckBox()
        checkbox.setChecked(bool(current_value))

        checkbox.stateChanged.connect(
            partial(WidgetFactory._update_bool_value, cb=update_callback)
        )

        h_layout.addWidget(checkbox)
        return container

    @staticmethod
    def build_literal_widget(current_value, field_info, update_callback):
        container = QWidget()
        h_layout = QHBoxLayout(container)
        h_layout.setContentsMargins(0, 0, 0, 0)

        combo_box = QComboBox()
        allowed_options = get_args(field_info.annotation)

        combo_box.blockSignals(True)
        combo_box.addItems([str(opt) for opt in allowed_options])

        if current_value in allowed_options:
            combo_box.setCurrentText(str(current_value))
        elif allowed_options:
            combo_box.setCurrentText(str(allowed_options[0]))

        combo_box.blockSignals(False)

        # currentTextChanged emits a string directly
        combo_box.currentTextChanged.connect(update_callback)

        h_layout.addWidget(combo_box)
        return container

    @staticmethod
    def _open_file_dialog(le, p, field_name):
        file_path, _ = QFileDialog.getOpenFileName(
            p, f"Select {field_name}", "",
            "Images (*.png *.jpg *.jpeg);;All Files (*)")
        if file_path:
            le.setText(file_path)

    @staticmethod
    def build_str_widget(field_name, field_info, current_value, update_callback, registry=None, parent=None):
        container = QWidget()
        h_layout = QHBoxLayout(container)
        h_layout.setContentsMargins(0, 0, 0, 0)

        schema_extra = field_info.json_schema_extra or {}
        widget_type = schema_extra.get("widget")

        if widget_type == "operation_selector":
            widget = QComboBox()
            widget.blockSignals(True)
            if registry:
                widget.addItems(registry.get_operation_names())
            if current_value:
                widget.setCurrentText(str(current_value))
            widget.blockSignals(False)

            widget.currentTextChanged.connect(update_callback)
            h_layout.addWidget(widget)

        else:
            widget = QLineEdit(str(current_value or ""))
            widget.textChanged.connect(update_callback)
            h_layout.addWidget(widget)

            if widget_type == "file_picker":
                browse_btn = QPushButton("Browse...")
                
                browse_btn.clicked.connect(
                    partial(WidgetFactory._open_file_dialog, le=widget, p=parent, field_name=field_name)
                )
                h_layout.addWidget(browse_btn)

        return container
