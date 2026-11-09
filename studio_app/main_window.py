"""ClipClipper Studio main window — nav rail + tool pages + console drawer."""
import os
from collections import deque
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import icons
from .home_page import HomePage
from .nav_sidebar import NavSidebar
from .settings_panel import SettingsPanel
from .shorts_creator_page import ShortsCreatorPage
from .tiktok_page import TikTokPage
from .widgets import Spinner

CONSOLE_HEIGHT = 200


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ClipClipper Studio")
        self.resize(1360, 860)
        self.setMinimumSize(1000, 640)
        self._results_root = Path(os.getenv("LOCAL_OUTPUT_DIR") or "output")
        self._busy_pages: dict[QWidget, bool] = {}
        self._log_lines: deque[str] = deque(maxlen=5000)
        self._build()
        self._build_shortcuts()

    # -- shell ------------------------------------------------------------- #
    def _build(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.sidebar = NavSidebar()
        self.sidebar.item_clicked.connect(self._on_nav)
        body.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)

        self._build_statusbar()
        self._build_pages()
        self._build_console()
        root.addWidget(self._console, 0)

    def _build_pages(self):
        self.home = HomePage()
        self.home.tool_launch.connect(self._launch_tool)
        self.stack.addWidget(self.home)

        self.shorts_page = ShortsCreatorPage(self._results_root)
        self.tiktok_page = TikTokPage(self._results_root)

        from .faceswap_page import FaceSwapPage

        self.swap_page = FaceSwapPage(self._results_root)

        for page in (self.shorts_page, self.tiktok_page, self.swap_page):
            page.log.connect(self._log)
            page.status.connect(self.status_label.setText)
            page.busy.connect(lambda on, p=page: self._set_busy(p, on))

        self.stack.addWidget(self.shorts_page)
        self.stack.addWidget(self.tiktok_page)
        self.stack.addWidget(self.swap_page)

        settings_host = QScrollArea()
        settings_host.setWidgetResizable(True)
        self.settings = SettingsPanel()
        settings_host.setWidget(self.settings)
        self.stack.addWidget(settings_host)

        controls = self.settings._controls
        self.shorts_page.bind_settings(controls)
        self.tiktok_page.bind_settings(controls)
        self.swap_page.bind_settings(controls)

    def _build_console(self):
        self._console = QFrame()
        self._console.setObjectName("console")
        self._console.setFixedHeight(CONSOLE_HEIGHT)
        lay = QVBoxLayout(self._console)
        lay.setContentsMargins(12, 6, 12, 10)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("Console")
        title.setObjectName("h3")
        head.addWidget(title)
        self.console_filter = QLineEdit()
        self.console_filter.setPlaceholderText("Filter…")
        self.console_filter.setClearButtonEnabled(True)
        self.console_filter.setFixedWidth(220)
        self.console_filter.textChanged.connect(self._refilter_log)
        head.addWidget(self.console_filter)
        head.addStretch(1)
        clear_btn = QLabel()
        clear_btn.setPixmap(icons.icon("trash", "#98a0b5", 16).pixmap(16, 16))
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setToolTip("Clear console")
        clear_btn.mousePressEvent = lambda e: self._clear_log()
        head.addWidget(clear_btn)
        close_btn = QLabel("Hide")
        close_btn.setObjectName("dim")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.mousePressEvent = lambda e: self._toggle_console(False)
        head.addWidget(close_btn)
        lay.addLayout(head)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("consoleView")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        lay.addWidget(self.log_view, 1)
        self._console.hide()

    def _build_statusbar(self):
        self.status_label = QLabel("Ready — pick a tool to get started")
        self.statusBar().addWidget(self.status_label, 1)

        self.spinner = Spinner(16)
        self.statusBar().addPermanentWidget(self.spinner)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setFixedWidth(180)
        self.statusBar().addPermanentWidget(self.progress)

        console_toggle = QLabel("Console")
        console_toggle.setObjectName("dim")
        console_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        console_toggle.mousePressEvent = lambda e: self._toggle_console(None)
        self.statusBar().addPermanentWidget(console_toggle)

    def _build_shortcuts(self):
        for index in range(4):
            QShortcut(QKeySequence(f"Ctrl+{index + 1}"), self, activated=lambda i=index: self._on_nav(i))
        QShortcut(QKeySequence("Ctrl+5"), self, activated=lambda: self._on_nav(5))
        QShortcut(QKeySequence("Ctrl+`"), self, activated=lambda: self._toggle_console(None))
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self._focus_console)

    # -- navigation --------------------------------------------------------- #
    def _on_nav(self, index: int):
        if index == 4:  # console toggle
            self._toggle_console(None)
            return
        page_index = {5: 4}.get(index, index)  # 5 -> settings page
        if page_index >= self.stack.count():
            return
        self.sidebar.set_active(index if index < 4 else 0)
        self._switch_page(page_index)

    def _launch_tool(self, tool_id: str):
        target = {"shorts": 1, "tiktok": 2, "swap": 3}.get(tool_id)
        if target is None:
            return
        self.sidebar.set_active(target)
        self._switch_page(target)

    def _switch_page(self, index: int):
        if self.stack.currentIndex() == index:
            return
        self.stack.setCurrentIndex(index)
        from PySide6.QtWidgets import QGraphicsOpacityEffect

        widget = self.stack.currentWidget()
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(160)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(0.35)
        anim.setEndValue(1.0)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    # -- console ------------------------------------------------------------ #
    def _toggle_console(self, force: bool | None):
        visible = force if force is not None else not self._console.isVisible()
        self._console.setVisible(visible)
        if visible:
            self._focus_console()

    def _focus_console(self):
        self._console.setVisible(True)
        self.console_filter.setFocus()

    def _log(self, line: str):
        self._log_lines.append(line)
        if self._filter_match(line):
            self.log_view.appendPlainText(line)

    def _filter_match(self, line: str) -> bool:
        text = self.console_filter.text().strip().lower()
        return not text or text in line.lower()

    def _refilter_log(self, _text: str):
        self.log_view.clear()
        for line in self._log_lines:
            if self._filter_match(line):
                self.log_view.appendPlainText(line)

    def _clear_log(self):
        self._log_lines.clear()
        self.log_view.clear()

    # -- busy state ---------------------------------------------------------- #
    def _set_busy(self, page: QWidget, busy: bool):
        self._busy_pages[page] = busy
        any_busy = any(self._busy_pages.values())
        self.spinner.set_running(any_busy)
        self.progress.setVisible(any_busy)

    def closeEvent(self, event):
        for page in (self.shorts_page, self.tiktok_page, self.swap_page):
            page.shutdown()
        super().closeEvent(event)
