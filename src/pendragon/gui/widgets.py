from typing import get_args, get_origin, Literal

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSlider, QSpinBox, QWidget
)

from pendragon.engine.registry import OPERATION_REGISTRY


class WidgetFactory:
    """A factory for creating standardized PyQt UI widgets from Pydantic fields."""

    @classmethod
    def build_field_widget(cls, field_name, field_info, current_value, update_callback, parent=None):
        """Routes the field to the appropriate widget builder based on its annotation."""
        origin = get_origin(field_info.annotation)
        annotation = field_info.annotation

        if annotation == float:
            return cls.build_float_widget(current_value, field_info, update_callback)
        elif annotation == int:
            return cls.build_int_widget(current_value, update_callback)
        elif annotation == bool:
            return cls.build_bool_widget(current_value, update_callback)
        elif origin is Literal:
            return cls.build_literal_widget(current_value, field_info, update_callback)
        elif annotation == str:
            return cls.build_str_widget(field_name, field_info, current_value, update_callback, parent)
        
        return None

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

            # Prevent division by zero if bounds are equal
            range_span = val_max - val_min if val_max > val_min else 1.0

            # Clamp the initial value to prevent UI mapping glitches
            clamped_val = max(val_min, min(val_max, current_value))
            current_percent = int(((clamped_val - val_min) / range_span) * 100)
            slider.setValue(current_percent)

            value_label = QLabel(f"{clamped_val:.2f}")
            value_label.setMinimumWidth(35)
            value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

            def update_label_only(val, lbl=value_label, v_min=val_min, r_span=range_span):
                real_val = v_min + (val / 100.0) * r_span
                lbl.setText(f"{real_val:.2f}")

            def update_value_wrapper(val, lbl=value_label, v_min=val_min, r_span=range_span, cb=update_callback):
                real_val = v_min + (val / 100.0) * r_span
                lbl.setText(f"{real_val:.2f}")
                cb(real_val)  # Emit back to caller

            slider.sliderMoved.connect(update_label_only)
            slider.valueChanged.connect(update_value_wrapper)
            h_layout.addWidget(slider)
            h_layout.addWidget(value_label)

        else:
            spin_box = QDoubleSpinBox()
            spin_box.setRange(-10000.0, 10000.0)
            spin_box.setDecimals(2)
            spin_box.setSingleStep(0.1)
            spin_box.setValue(current_value)
            spin_box.setKeyboardTracking(False)

            def update_spin_wrapper(val, cb=update_callback):
                cb(val)  # Emit back to caller

            spin_box.valueChanged.connect(update_spin_wrapper)
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

        def update_int_wrapper(val, cb=update_callback):
            cb(val)

        spin_box.valueChanged.connect(update_int_wrapper)

        h_layout.addWidget(spin_box)
        return container

    @staticmethod
    def build_bool_widget(current_value, update_callback):
        container = QWidget()
        h_layout = QHBoxLayout(container)
        h_layout.setContentsMargins(0, 0, 0, 0)

        checkbox = QCheckBox()
        checkbox.setChecked(bool(current_value))

        def update_bool_wrapper(state, cb=update_callback):
            cb(bool(state))

        checkbox.stateChanged.connect(update_bool_wrapper)

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

        def update_literal_wrapper(text, cb=update_callback):
            cb(text)

        combo_box.currentTextChanged.connect(update_literal_wrapper)

        h_layout.addWidget(combo_box)
        return container

    @staticmethod
    def build_str_widget(field_name, field_info, current_value, update_callback, parent=None):
        container = QWidget()
        h_layout = QHBoxLayout(container)
        h_layout.setContentsMargins(0, 0, 0, 0)

        schema_extra = field_info.json_schema_extra or {}
        widget_type = schema_extra.get("widget")

        def update_value(text, cb=update_callback):
            cb(text)

        if widget_type == "operation_selector":
            widget = QComboBox()
            widget.blockSignals(True)
            widget.addItems(sorted(OPERATION_REGISTRY.keys()))
            if current_value:
                widget.setCurrentText(str(current_value))
            widget.blockSignals(False)

            widget.currentTextChanged.connect(update_value)
            h_layout.addWidget(widget)

        else:
            widget = QLineEdit(str(current_value or ""))
            widget.textChanged.connect(update_value)
            h_layout.addWidget(widget)

            if widget_type == "file_picker":
                browse_btn = QPushButton("Browse...")

                def open_file_dialog(checked=False, le=widget, p=parent):
                    file_path, _ = QFileDialog.getOpenFileName(
                        p, f"Select {field_name}", "",
                        "Images (*.png *.jpg *.jpeg);;All Files (*)")
                    if file_path:
                        le.setText(file_path)

                browse_btn.clicked.connect(open_file_dialog)
                h_layout.addWidget(browse_btn)

        return container
