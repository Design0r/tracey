from pathlib import Path

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

ICONS = (Path(__file__).parent / "icons").as_posix()

BG_BASE = "#131418"
BG_PANEL = "#1A1B20"
BG_POPUP = "#1C1D22"
FRAME = "#26272E"
FRAME_HOVER = "#2F3139"
FRAME_ACTIVE = "#393B45"
HEADER = "#292B33"
HEADER_HOVER = "#32343D"
HEADER_ACTIVE = "#3B3E48"
BORDER = "#2A2C33"
TEXT = "#E4E5E9"
TEXT_DIM = "#7D808B"
ACCENT = "#5B8CFF"
ACCENT_HOVER = "#7AA2FF"
ERROR = "#EB6666"
SCROLL = "#3A3D47"
SCROLL_HOVER = "#4A4E5A"
SCROLL_ACTIVE = "#5A5F6D"

STYLESHEET = f"""
QToolTip {{
    background: {BG_POPUP};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 4px 6px;
}}

QPushButton, QToolButton {{
    background: {FRAME};
    color: {TEXT};
    border: none;
    border-radius: 6px;
    padding: 6px 12px;
}}
QPushButton:hover, QToolButton:hover {{ background: {FRAME_HOVER}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {FRAME_ACTIVE}; }}
QPushButton:disabled, QToolButton:disabled {{ background: {BG_PANEL}; color: {TEXT_DIM}; }}

QPushButton[role="accent"] {{ background: {ACCENT}; color: #FFFFFF; }}
QPushButton[role="accent"]:hover {{ background: {ACCENT_HOVER}; }}
QPushButton[role="accent"]:disabled {{ background: {BG_PANEL}; color: {TEXT_DIM}; }}

QPushButton[role="small"], QToolButton[role="remove"] {{ padding: 2px 8px; }}

QToolButton[role="section"] {{
    background: {HEADER};
    padding: 6px 8px;
    font-weight: 600;
}}
QToolButton[role="section"]:hover {{ background: {HEADER_HOVER}; }}
QToolButton[role="section"]:pressed {{ background: {HEADER_ACTIVE}; }}

QLineEdit, QSpinBox, QComboBox {{
    background: {FRAME};
    color: {TEXT};
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: rgba(91, 140, 255, 0.35);
    selection-color: {TEXT};
}}
QLineEdit:hover, QSpinBox:hover, QComboBox:hover {{ background: {FRAME_HOVER}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url({ICONS}/down.svg); width: 10px; height: 6px; }}
QComboBox QAbstractItemView {{
    background: {BG_POPUP};
    border: 1px solid {BORDER};
    selection-background-color: {HEADER_HOVER};
    outline: 0;
    padding: 4px;
}}
QSpinBox {{ padding-right: 24px; }}
QSpinBox::up-button, QSpinBox::down-button {{
    subcontrol-origin: border;
    width: 22px;
    border: none;
    background: transparent;
}}
QSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: 6px; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 6px; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {FRAME_ACTIVE}; }}
QSpinBox::up-arrow {{ image: url({ICONS}/up.svg); width: 10px; height: 6px; }}
QSpinBox::down-arrow {{ image: url({ICONS}/down.svg); width: 10px; height: 6px; }}

QProgressBar {{
    background: {FRAME};
    border: none;
    border-radius: 6px;
    text-align: center;
    color: {TEXT};
    min-height: 24px;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 6px; }}

QFrame[role="panel"] {{
    border: 1px solid {BORDER};
    border-radius: 6px;
}}
QFrame[role="separator"] {{ background: {BORDER}; border: none; }}
QFrame[role="status"] {{ background: {BG_PANEL}; border-top: 1px solid {BORDER}; }}

QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:hover {{ background: rgba(91, 140, 255, 0.7); }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 0; }}
QScrollBar::handle {{ background: {SCROLL}; border-radius: 6px; min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: {SCROLL_HOVER}; }}
QScrollBar::handle:pressed {{ background: {SCROLL_ACTIVE}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QLabel[role="title"] {{ font-weight: 600; }}
QLabel[role="dim"] {{ color: {TEXT_DIM}; }}
QLabel[role="error"] {{ color: {ERROR}; }}
"""


def palette() -> QPalette:
    p = QPalette()
    colors = {
        QPalette.ColorRole.Window: BG_BASE,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: FRAME,
        QPalette.ColorRole.AlternateBase: BG_PANEL,
        QPalette.ColorRole.ToolTipBase: BG_POPUP,
        QPalette.ColorRole.ToolTipText: TEXT,
        QPalette.ColorRole.PlaceholderText: TEXT_DIM,
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.Button: FRAME,
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.BrightText: ERROR,
        QPalette.ColorRole.Highlight: ACCENT,
        QPalette.ColorRole.HighlightedText: "#FFFFFF",
        QPalette.ColorRole.Link: ACCENT_HOVER,
        QPalette.ColorRole.Light: FRAME_ACTIVE,
        QPalette.ColorRole.Midlight: FRAME_HOVER,
        QPalette.ColorRole.Mid: BORDER,
        QPalette.ColorRole.Dark: BG_PANEL,
        QPalette.ColorRole.Shadow: "#000000",
    }
    for role, color in colors.items():
        p.setColor(role, QColor(color))

    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(TEXT_DIM))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, QColor(BG_PANEL))

    return p


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setPalette(palette())
    app.setStyleSheet(STYLESHEET)

    font = app.font()
    font.setPointSizeF(max(font.pointSizeF(), 10.0))
    app.setFont(font)


def set_role(widget: QWidget, role: str) -> None:
    if widget.property("role") == role:
        return
    widget.setProperty("role", role)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
