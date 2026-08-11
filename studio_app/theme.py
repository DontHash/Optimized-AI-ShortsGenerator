"""Dark professional Qt stylesheet for the ClipClipper studio."""

ACCENT = "#6c8cff"
ACCENT_DIM = "#4a63c4"
BG = "#16171c"
BG_PANEL = "#1e2027"
BG_RAISED = "#262933"
BORDER = "#343845"
TEXT = "#e6e8ee"
TEXT_DIM = "#9aa0b0"
GOOD = "#3ecf8e"
WARN = "#f5b544"
BAD = "#f06060"

QSS = f"""
* {{
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
    color: {TEXT};
}}
QMainWindow, QWidget {{
    background-color: {BG};
}}
QWidget#panel {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QLabel#h1 {{
    font-size: 17px;
    font-weight: 700;
    color: {TEXT};
}}
QLabel#h2 {{
    font-size: 14px;
    font-weight: 600;
    color: {TEXT};
}}
QLabel#dim {{
    color: {TEXT_DIM};
}}
QLabel#badge {{
    font-size: 12px;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 9px;
    background-color: {BG_RAISED};
    color: {TEXT};
}}
QLabel#badgeGood {{
    background-color: {GOOD};
    color: #0b1410;
}}
QLabel#badgeWarn {{
    background-color: {WARN};
    color: #1a1405;
}}
QLabel#badgeBad {{
    background-color: {BAD};
    color: #170b0b;
}}
QLabel#badgeAccent {{
    background-color: {ACCENT};
    color: #0a0e1c;
}}
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: {ACCENT_DIM};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border-color: {ACCENT};
}}
QPushButton {{
    background-color: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: #2d3140;
    border-color: {ACCENT_DIM};
}}
QPushButton:pressed {{
    background-color: #33374a;
}}
QPushButton:disabled {{
    color: {TEXT_DIM};
    border-color: {BORDER};
}}
QPushButton#primary {{
    background-color: {ACCENT};
    border: none;
    color: #0a0e1c;
}}
QPushButton#primary:hover {{
    background-color: #7e9aff;
}}
QPushButton#danger {{
    background-color: #4a2226;
    border: 1px solid #6b3038;
    color: {BAD};
}}
QPushButton#ghost {{
    background-color: transparent;
    border: 1px solid {BORDER};
    color: {TEXT_DIM};
    padding: 4px 10px;
    font-weight: 400;
}}
QListWidget {{
    background-color: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: 6px;
    outline: none;
}}
QListWidget::item {{
    padding: 7px 10px;
    border-radius: 5px;
    margin: 2px 4px;
}}
QListWidget::item:selected {{
    background-color: {ACCENT_DIM};
    color: white;
}}
QListWidget::item:hover {{
    background-color: #2d3140;
}}
QListWidget::item:selected:hover {{
    background-color: {ACCENT_DIM};
}}
QProgressBar {{
    background-color: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: 5px;
    text-align: center;
    color: {TEXT_DIM};
    height: 16px;
    font-size: 11px;
}}
QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 4px;
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: #3a3e4d;
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {ACCENT_DIM}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    padding: 8px 18px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    color: {TEXT_DIM};
    font-weight: 600;
}}
QTabBar::tab:selected {{
    color: {TEXT};
    border-bottom: 2px solid {ACCENT};
}}
QTabBar::tab:hover {{
    color: {TEXT};
}}
QToolTip {{
    background-color: {BG_RAISED};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 4px 8px;
}}
QStatusBar {{
    background-color: {BG_PANEL};
    border-top: 1px solid {BORDER};
    color: {TEXT_DIM};
}}
"""


def score_color(score: float) -> str:
    """Color a 0-100 score: green >= 75, amber >= 50, red below."""
    if score >= 75:
        return GOOD
    if score >= 50:
        return WARN
    return BAD
