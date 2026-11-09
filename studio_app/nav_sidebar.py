"""Left navigation rail — icon + label items with an animated active bar."""
from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QEnterEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import icons
from .theme import ACCENT, ACCENT_HOVER, TEXT, TEXT_FAINT

ITEM_IDLE = TEXT_FAINT
ITEM_HOVER = TEXT
ITEM_ACTIVE = ACCENT_HOVER


class NavItem(QWidget):
    """One clickable rail entry with hover/active states."""

    clicked = Signal()

    def __init__(self, icon_name: str, text: str, parent=None):
        super().__init__(parent)
        self.setObjectName("navItem")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._icon_name = icon_name
        self._active = False
        self._hovered = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)
        self.icon = QLabel()
        self.icon.setFixedSize(18, 18)
        lay.addWidget(self.icon)
        self.label = QLabel(text)
        lay.addWidget(self.label)
        lay.addStretch(1)
        self._render()

    def _color(self) -> str:
        if self._active:
            return ITEM_ACTIVE
        if self._hovered:
            return ITEM_HOVER
        return ITEM_IDLE

    def _render(self):
        self.icon.setPixmap(icons.icon(self._icon_name, self._color(), 18).pixmap(18, 18))
        self.label.setStyleSheet(f"color:{self._color()}; font-weight:{'600' if self._active else '500'};")

    def set_active(self, active: bool):
        self._active = active
        self._render()

    def enterEvent(self, event: QEnterEvent):
        self._hovered = True
        self._render()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._render()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class NavSidebar(QWidget):
    """Brand header + nav items + a marker bar that slides between items."""

    item_clicked = Signal(int)  # index into NAV_ITEMS (0 = Home)

    NAV_ITEMS = [
        ("home", "Home"),
        ("shorts", "Shorts Creator"),
        ("tiktok", "TikTok Downloader"),
        ("swap", "Face Swap"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(216)
        self._items: list[NavItem] = []
        self._active_index = 0
        self._anim = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 16, 12, 12)
        lay.setSpacing(2)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(8)
        logo = QLabel()
        logo.setPixmap(icons.icon("spark", ACCENT, 22).pixmap(22, 22))
        brand_row.addWidget(logo)
        brand_col = QVBoxLayout()
        brand_col.setSpacing(0)
        name = QLabel("ClipClipper")
        name.setObjectName("brand")
        brand_col.addWidget(name)
        sub = QLabel("STUDIO")
        sub.setObjectName("brandSub")
        brand_col.addWidget(sub)
        brand_row.addLayout(brand_col)
        brand_row.addStretch(1)
        lay.addLayout(brand_row)

        lay.addSpacing(14)

        self._list_host = QWidget()
        self._list_lay = QVBoxLayout(self._list_host)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(2)

        self._marker = QFrame()
        self._marker.setObjectName("navMarker")
        self._marker.setFixedSize(3, 26)
        self._marker.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._marker.hide()

        for icon_name, label in self.NAV_ITEMS:
            item = NavItem(icon_name, label)
            item.clicked.connect(lambda i=len(self._items): self._select(i))
            self._items.append(item)
            self._list_lay.addWidget(item)
        self._list_lay.addStretch(1)
        lay.addWidget(self._list_host, 1)

        self.console_btn = NavItem("terminal", "Console")
        self.console_btn.clicked.connect(lambda: self.item_clicked.emit(len(self.NAV_ITEMS)))
        lay.addWidget(self.console_btn)

        self.settings_btn = NavItem("sliders", "Settings")
        self.settings_btn.clicked.connect(lambda: self.item_clicked.emit(len(self.NAV_ITEMS) + 1))
        lay.addWidget(self.settings_btn)

        # marker must sit above the items; reparent to the list host
        self._marker.setParent(self._list_host)
        self._marker.show()
        self.set_active(0)

    def set_active(self, index: int):
        index = max(0, min(index, len(self._items) - 1))
        for i, item in enumerate(self._items):
            item.set_active(i == index)
        if 0 <= index < len(self._items):
            self._animate_marker_to(self._items[index])

    def _animate_marker_to(self, item: NavItem):
        pos = item.mapTo(self._list_host, QPoint(0, 0))
        target = QPoint(0, pos.y() + (item.height() - self._marker.height()) // 2)
        self._anim = QPropertyAnimation(self._marker, b"pos")
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setStartValue(self._marker.pos())
        self._anim.setEndValue(target)
        self._anim.setObjectName("navAnim")
        self._anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def _select(self, index: int):
        self.set_active(index)
        self.item_clicked.emit(index)
