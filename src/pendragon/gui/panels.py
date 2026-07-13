from PyQt5.QtWidgets import QComboBox
from PyQt5.QtWidgets import QFormLayout
from PyQt5.QtWidgets import QGroupBox
from PyQt5.QtWidgets import QHBoxLayout
from PyQt5.QtWidgets import QLabel
from PyQt5.QtWidgets import QProgressBar
from PyQt5.QtWidgets import QPushButton
from PyQt5.QtWidgets import QWidget


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
