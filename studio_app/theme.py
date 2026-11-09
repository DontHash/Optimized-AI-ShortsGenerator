"""ClipClipper Studio theme — palette tokens + the global QSS stylesheet.

All colors live in this module so widgets never hard-code hex values.
Badges and score colors are exposed as variants (good/warn/bad/accent)
so the stylesheet owns the actual paint.
"""
from . import icons

# ------------------------------------------------------------------ palette -
BG = "#0f1117"          # app background
BG_PANEL = "#151823"    # cards / panels
BG_RAISED = "#1c2130"   # inputs, raised surfaces
BG_HOVER = "#252b3d"    # hover surfaces
BG_ACTIVE = "#2b3350"   # pressed / selected
BORDER = "#2b3245"      # default border
BORDER_STRONG = "#3a435e"
TEXT = "#e8ebf4"
TEXT_SOFT = "#b9c0d1"
TEXT_DIM = "#98a0b5"
TEXT_FAINT = "#69728a"
ACCENT = "#6c8cff"
ACCENT_HOVER = "#8ba6ff"
ACCENT_DIM = "#4a63c4"
ACCENT_DEEP = "#31407f"
GOOD = "#3ecf8e"
GOOD_DIM = "#24553f"
WARN = "#f5b544"
WARN_DIM = "#55401a"
BAD = "#f06060"
BAD_DIM = "#552727"
BAD_DEEP = "#5b2a2a"          # danger hover background
BAD_BRIGHT = "#ff8a8a"        # danger hover text/border
ON_ACCENT = "#0a0e1c"
ACCENT_DISABLED_TEXT = "#5a6794"
TOOLTIP_BG = "#232839"
BG_CONSOLE = "#0b0d12"

# ---------------------------------------------------------------------- QSS -
QSS = f"""
* {{
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
    color: {TEXT};
}}
QMainWindow, QWidget {{
    background-color: {BG};
}}
QDialog {{
    background-color: {BG};
}}
QWidget#panel {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QWidget#dropzone {{
    background-color: {BG_RAISED};
    border: 1px dashed {BORDER_STRONG};
    border-radius: 10px;
}}
QWidget#dropzone:hover {{
    border-color: {ACCENT_DIM};
    background-color: {BG_HOVER};
}}
QWidget#dropzone[active="true"] {{
    border-color: {ACCENT};
    background-color: {ACCENT_DEEP};
}}
QFrame#divider {{
    background-color: {BORDER};
    border: none;
    max-height: 1px;
}}

/* ------------------------------------------------------------- typography */
QLabel#h1 {{ font-size: 19px; font-weight: 700; color: {TEXT}; }}
QLabel#h2 {{ font-size: 14px; font-weight: 600; color: {TEXT}; }}
QLabel#h3 {{ font-size: 13px; font-weight: 600; color: {TEXT}; }}
QLabel#dim {{ color: {TEXT_DIM}; }}
QLabel#faint {{ color: {TEXT_FAINT}; }}
QLabel#soft {{ color: {TEXT_SOFT}; }}

/* ----------------------------------------------------------------- badges */
QLabel#badge {{
    font-size: 11px;
    font-weight: 700;
    padding: 2px 9px;
    border-radius: 9px;
    background-color: {BG_HOVER};
    color: {TEXT_DIM};
}}
QLabel#badgeGood {{ background-color: {GOOD_DIM}; color: {GOOD}; }}
QLabel#badgeWarn {{ background-color: {WARN_DIM}; color: {WARN}; }}
QLabel#badgeBad {{ background-color: {BAD_DIM}; color: {BAD}; }}
QLabel#badgeAccent {{ background-color: {ACCENT_DEEP}; color: {ACCENT_HOVER}; }}

/* ---------------------------------------------------------------- inputs */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: {ACCENT_DIM};
    selection-color: white;
}}
QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover,
QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{
    border-color: {BORDER_STRONG};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {ACCENT};
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
    color: {TEXT_FAINT};
    background-color: {BG_PANEL};
}}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{
    image: url({icons.url("chevron-down", TEXT_DIM, 24)});
    width: 14px;
    height: 14px;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_RAISED};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    selection-background-color: {ACCENT_DIM};
    selection-color: white;
    outline: none;
    padding: 4px;
}}

/* --------------------------------------------------------------- buttons */
QPushButton {{
    background-color: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 14px;
    font-weight: 600;
    color: {TEXT};
}}
QPushButton:hover {{
    background-color: {BG_HOVER};
    border-color: {BORDER_STRONG};
}}
QPushButton:pressed {{ background-color: {BG_ACTIVE}; }}
QPushButton:focus {{ border-color: {ACCENT_DIM}; }}
QPushButton:disabled {{
    color: {TEXT_FAINT};
    border-color: {BORDER};
    background-color: {BG_PANEL};
}}
QPushButton#primary {{
    background-color: {ACCENT};
    border: 1px solid {ACCENT};
    color: {ON_ACCENT};
}}
QPushButton#primary:hover {{
    background-color: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}
QPushButton#primary:pressed {{ background-color: {ACCENT_DIM}; }}
QPushButton#primary:disabled {{
    background-color: {ACCENT_DEEP};
    border-color: {ACCENT_DEEP};
    color: {ACCENT_DISABLED_TEXT};
}}
QPushButton#ghost {{
    background-color: transparent;
    border: 1px solid transparent;
    color: {TEXT_DIM};
    padding: 5px 10px;
    font-weight: 500;
}}
QPushButton#ghost:hover {{
    background-color: {BG_HOVER};
    border-color: {BORDER};
    color: {TEXT};
}}
QPushButton#danger {{
    background-color: {BAD_DIM};
    border: 1px solid {BAD};
    color: {BAD};
}}
QPushButton#danger:hover {{
    background-color: {BAD_DEEP};
    border-color: {BAD_BRIGHT};
    color: {BAD_BRIGHT};
}}
QPushButton#danger:disabled {{
    background-color: {BG_PANEL};
    border-color: {BORDER};
    color: {TEXT_FAINT};
}}

/* --------------------------------------------------------- tool buttons */
QToolButton {{
    background-color: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 12px;
    font-weight: 600;
    color: {TEXT};
}}
QToolButton:hover {{
    background-color: {BG_HOVER};
    border-color: {BORDER_STRONG};
}}
QToolButton:pressed, QToolButton::menu-button:pressed {{ background-color: {BG_ACTIVE}; }}
QToolButton:disabled {{
    color: {TEXT_FAINT};
    border-color: {BORDER};
    background-color: {BG_PANEL};
}}
QToolButton#moreBtn {{
    background-color: transparent;
    border: 1px solid transparent;
    color: {TEXT_DIM};
    font-weight: 500;
    padding: 6px 10px;
}}
QToolButton#moreBtn:hover {{
    background-color: {BG_HOVER};
    border-color: {BORDER};
    color: {TEXT};
}}
QToolButton::menu-indicator {{ image: none; }}

/* ------------------------------------------------------- check / radio */
QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {BORDER_STRONG};
    background-color: {BG_RAISED};
}}
QCheckBox::indicator {{ border-radius: 5px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {ACCENT_DIM};
}}
QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
    image: url({icons.url("check", ON_ACCENT, 24)});
}}
QRadioButton::indicator:checked {{
    background-color: {ACCENT};
    border: 4px solid {BG_RAISED};
    outline: 1px solid {ACCENT};
}}

/* ------------------------------------------------------------- lists */
QListWidget {{
    background-color: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: 8px;
    outline: none;
    padding: 4px;
}}
QListWidget::item {{
    padding: 4px 6px;
    border-radius: 8px;
    margin: 1px 0;
}}
QListWidget::item:selected {{ background-color: {ACCENT_DEEP}; }}
QListWidget::item:hover:!selected {{ background-color: {BG_HOVER}; }}

/* ----------------------------------------------------------- progress */
QProgressBar {{
    background-color: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: 6px;
    text-align: center;
    color: {TEXT_DIM};
    font-size: 11px;
    min-height: 12px;
}}
QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 5px;
}}

/* ---------------------------------------------------------- scrollbars */
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER_STRONG}; border-radius: 4px; min-height: 32px; }}
QScrollBar::handle:vertical:hover {{ background: {ACCENT_DIM}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER_STRONG}; border-radius: 4px; min-width: 32px; }}
QScrollBar::handle:horizontal:hover {{ background: {ACCENT_DIM}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ------------------------------------------------------------ splitter */
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 6px; }}
QSplitter::handle:vertical {{ height: 6px; }}
QSplitter::handle:hover {{ background: {ACCENT_DEEP}; }}

/* -------------------------------------------------------------- slider */
QSlider::groove:horizontal {{
    height: 4px;
    background: {BORDER_STRONG};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
    background: {TEXT};
    border: 1px solid {BORDER_STRONG};
}}
QSlider::handle:horizontal:hover {{ background: {ACCENT_HOVER}; }}

/* ----------------------------------------------------------------- tabs */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    top: -1px;
    background: {BG_PANEL};
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
QTabBar::tab:hover {{ color: {TEXT}; }}

/* ---------------------------------------------------------------- misc */
QToolTip {{
    background-color: {TOOLTIP_BG};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    padding: 6px 10px;
    border-radius: 6px;
}}
QStatusBar {{
    background-color: {BG_PANEL};
    border-top: 1px solid {BORDER};
    color: {TEXT_DIM};
}}
QStatusBar QLabel {{ color: {TEXT_DIM}; font-size: 12px; }}
QMenu {{
    background-color: {BG_RAISED};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background-color: {ACCENT_DIM}; color: white; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}
QMessageBox {{ background-color: {BG_PANEL}; }}

/* ------------------------------------------------------------ nav rail */
QWidget#sidebar {{
    background-color: {BG_PANEL};
    border-right: 1px solid {BORDER};
}}
QWidget#navItem {{
    border: none;
    border-radius: 8px;
    background: transparent;
}}
QWidget#navItem:hover {{ background-color: {BG_HOVER}; }}
QWidget#navItem[active="true"] {{ background-color: {ACCENT_DEEP}; }}
QFrame#navMarker {{
    background-color: {ACCENT};
    border-radius: 2px;
    border: none;
}}
QLabel#brand {{
    font-size: 15px;
    font-weight: 700;
    color: {TEXT};
}}
QLabel#brandSub {{ font-size: 10px; color: {TEXT_FAINT}; }}

/* --------------------------------------------------------- home cards */
QFrame#toolCard {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QFrame#toolCard:hover {{
    border-color: {ACCENT_DIM};
    background-color: {BG_RAISED};
}}
QLabel#cardIcon {{
    background-color: {ACCENT_DEEP};
    border-radius: 10px;
}}
QLabel#cardTitle {{ font-size: 15px; font-weight: 700; color: {TEXT}; }}
QLabel#cardBlurb {{ color: {TEXT_DIM}; }}
QLabel#cardCta {{ color: {ACCENT_HOVER}; font-weight: 600; font-size: 12px; }}
QFrame#cardNew {{
    background-color: {GOOD_DIM};
    border-radius: 8px;
}}

/* -------------------------------------------------------- console */
QWidget#console {{
    background-color: {BG_PANEL};
    border-top: 1px solid {BORDER};
}}
QPlainTextEdit#consoleView {{
    background-color: {BG_CONSOLE};
    border: none;
    border-radius: 0;
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 12px;
    color: {TEXT_SOFT};
}}
"""


def score_color(score: float) -> str:
    """Variant name for a 0-100 score: good >= 75, warn >= 50, else bad."""
    if score >= 75:
        return "good"
    if score >= 50:
        return "warn"
    return "bad"
