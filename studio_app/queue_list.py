"""URL queue list with drag-and-drop: drop .txt files or pasted URLs in,
drag rows to reorder."""
import re

from PySide6.QtCore import Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)


def parse_dropped_text(text: str) -> list:
    """Extract candidate URLs/lines from dropped or pasted text."""
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


class QueueList(QListWidget):
    """Accepts drops of .txt files (URL per line) and plain text URLs."""

    urls_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setToolTip("Drop urls.txt or paste YouTube URLs")

    # -- data ------------------------------------------------------------ #
    def urls(self) -> list:
        return [self.item(i).text() for i in range(self.count())]

    def add_urls(self, urls: list) -> int:
        existing = set(self.urls())
        added = 0
        for u in urls:
            if u and u not in existing:
                item = QListWidgetItem(u)
                item.setToolTip(u)
                self.addItem(item)
                existing.add(u)
                added += 1
        if added:
            self.urls_changed.emit()
        return added

    def remove_selected(self):
        for item in self.selectedItems():
            self.takeItem(self.row(item))
        self.urls_changed.emit()

    def clear_all(self):
        super().clear()
        self.urls_changed.emit()

    # -- drag & drop ----------------------------------------------------- #
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        mime = event.mimeData()
        if mime.hasUrls():
            files = [u.toLocalFile() for u in mime.urls()]
            collected = []
            for path in files:
                if path.lower().endswith(".txt"):
                    try:
                        with open(path, encoding="utf-8") as f:
                            collected.extend(parse_dropped_text(f.read()))
                    except OSError:
                        continue
                else:
                    collected.extend(parse_dropped_text(path))
            self.add_urls(collected)
            event.acceptProposedAction()
            return
        if mime.hasText():
            self.add_urls(parse_dropped_text(mime.text()))
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class SourcePanel(QWidget):
    """Left-side panel: mode switch, URL input, queue list, run controls."""

    start_requested = Signal()
    stop_requested = Signal()
    urls_changed = Signal()
    mode_changed = Signal(str)  # "youtube" | "tiktok"

    MODES = [("youtube", "YouTube Clips (rank + download)"), ("tiktok", "TikTok Download (no watermark)")]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("ClipClipper Studio")
        title.setObjectName("h1")
        layout.addWidget(title)
        self.subtitle = QLabel("Drop YouTube URLs or a urls.txt file")
        self.subtitle.setObjectName("dim")
        layout.addWidget(self.subtitle)

        self.mode_combo = QComboBox()
        for value, label in self.MODES:
            self.mode_combo.addItem(label, value)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        layout.addWidget(self.mode_combo)

        input_row = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Paste a YouTube URL…")
        self.url_input.returnPressed.connect(self._add_from_input)
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._add_from_input)
        input_row.addWidget(self.url_input, 1)
        input_row.addWidget(add_btn)
        layout.addLayout(input_row)

        self.queue = QueueList()
        self.queue.urls_changed.connect(self.urls_changed)
        layout.addWidget(self.queue, 1)

        file_row = QHBoxLayout()
        self.file_btn = QPushButton("Load .txt")
        self.file_btn.clicked.connect(self._load_txt)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self.queue.remove_selected)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.queue.clear_all)
        file_row.addWidget(self.file_btn)
        file_row.addWidget(self.remove_btn)
        file_row.addWidget(self.clear_btn)
        layout.addLayout(file_row)

        run_row = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.start_requested)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_requested)
        run_row.addWidget(self.start_btn, 1)
        run_row.addWidget(self.stop_btn)
        layout.addLayout(run_row)

        self.count_label = QLabel("0 videos in queue")
        self.count_label.setObjectName("dim")
        layout.addWidget(self.count_label)
        self.urls_changed.connect(self._refresh_count)
        self._refresh_count()

    def mode(self) -> str:
        return self.mode_combo.currentData() or "youtube"

    def _on_mode_changed(self):
        tiktok = self.mode() == "tiktok"
        self.url_input.setPlaceholderText("Paste a TikTok video URL…" if tiktok else "Paste a YouTube URL…")
        self.subtitle.setText(
            "Drop TikTok video URLs (no watermark — no ranking)" if tiktok
            else "Drop YouTube URLs or a urls.txt file"
        )
        self.mode_changed.emit(self.mode())

    def _refresh_count(self):
        n = self.queue.count()
        self.count_label.setText(f"{n} video{'s' if n != 1 else ''} in queue")

    def _add_from_input(self):
        text = self.url_input.text().strip()
        if text:
            added = self.queue.add_urls(parse_dropped_text(text))
            if added:
                self.url_input.clear()
            else:
                self.url_input.selectAll()

    def _load_txt(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load URL list", "", "Text files (*.txt)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                self.queue.add_urls(parse_dropped_text(f.read()))
        except OSError as e:
            print(f"Could not read {path}: {e}")

    def set_running(self, running: bool):
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.url_input.setEnabled(not running)
        self.file_btn.setEnabled(not running)
