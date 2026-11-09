"""Shared building blocks: fluid spinner, empty states, page headers."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from . import icons
from .theme import ACCENT, TEXT_FAINT


class Spinner(QWidget):
    """Indeterminate rotating arc — a fluid busy indicator."""

    def __init__(self, size: int = 18, color: str = ACCENT, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(24)
        self._timer.timeout.connect(self._tick)
        self.setFixedSize(size, size)
        self.hide()

    def _tick(self):
        self._angle = (self._angle + 10) % 360
        self.update()

    def set_running(self, running: bool):
        self._timer.start() if running else self._timer.stop()
        self.setVisible(running)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(self._color)
        pen.setWidth(max(2, self.width() // 7))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        rect = self.rect().adjusted(2, 2, -2, -2)
        painter.drawArc(rect, -self._angle * 16, 100 * 16)


class EmptyState(QWidget):
    """Icon + title + hint shown when a results area has nothing yet."""

    def __init__(self, icon_name: str, title: str, hint: str, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 32, 24, 32)
        lay.setSpacing(8)

        pic = QLabel()
        pic.setPixmap(icons.icon(icon_name, TEXT_FAINT, 64).pixmap(64, 64))
        pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(pic)

        t = QLabel(title)
        t.setObjectName("h2")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)

        h = QLabel(hint)
        h.setObjectName("dim")
        h.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.setWordWrap(True)
        lay.addWidget(h)


class PageHeader(QWidget):
    """Tool page header: icon tile + title/subtitle, optional action widget."""

    def __init__(self, icon_name: str, title: str, subtitle: str, action=None, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        tile = QLabel()
        tile.setFixedSize(42, 42)
        tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tile.setPixmap(icons.icon(icon_name, ACCENT, 26).pixmap(26, 26))
        tile.setObjectName("cardIcon")
        lay.addWidget(tile, 0, Qt.AlignmentFlag.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        t = QLabel(title)
        t.setObjectName("h1")
        text_col.addWidget(t)
        s = QLabel(subtitle)
        s.setObjectName("dim")
        text_col.addWidget(s)
        lay.addLayout(text_col)

        if action is not None:
            lay.addStretch(1)
            lay.addWidget(action)
