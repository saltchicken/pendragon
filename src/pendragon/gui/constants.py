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
QPushButton:disabled {
    background-color: #1a1a1a;
    color: #555555;
    border: 1px solid #333333;
}
QProgressBar {
    border: 1px solid #555555;
    border-radius: 4px;
    text-align: center;
    background-color: #333333;
}
QProgressBar::chunk {
    background-color: #007acc;
    width: 10px;
}
"""
