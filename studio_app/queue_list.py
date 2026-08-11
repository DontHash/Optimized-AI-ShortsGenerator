"""URL queue list with drag-and-drop: drop .txt files or pasted URLs in,
drag rows to reorder. Items show the video thumbnail + title (fetched
lazily in a background thread, cached on disk) instead of the raw URL.
Persists the queue to output/studio_queue.json."""
import hashlib
import json
import os
import re
import time
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent, QPixmap
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
_CACHE_TTL_SECONDS = 30 * 24 * 3600  # refresh titles/thumbnails after 30 days


def parse_dropped_text(text: str) -> list:
    """Extract candidate URLs/lines from dropped or pasted text."""
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def _normalize(url: str) -> str:
    url = (url or "").strip()
    if url and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        return "https://" + url
    return url


def _is_tiktok(url: str) -> bool:
    return "tiktok.com" in url.lower()


def _thumb_name(url: str) -> str:
    return "q_" + hashlib.md5(url.encode("utf-8")).hexdigest()[:12] + ".jpg"


def _fmt_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


class QueueItemWidget(QWidget):
    """Thumbnail + title + dim URL, with a loading state while meta is fetched."""

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self._url = url
        self._build()
        self.set_loading()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(8)

        self.thumb = QLabel()
        self.thumb.setFixedSize(80, 45)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setStyleSheet("background-color:#14151a; border-radius:4px;")
        lay.addWidget(self.thumb, 0, Qt.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        self.title = QLabel("")
        self.title.setWordWrap(False)
        self.title.setStyleSheet("font-weight:600;")
        text_col.addWidget(self.title)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.badge = QLabel("YouTube")
        self.badge.setStyleSheet("color:#6c8cff; font-size:10px;")
        row.addWidget(self.badge)
        self.duration = QLabel("")
        self.duration.setStyleSheet("color:#9aa0b0; font-size:10px;")
        row.addWidget(self.duration)
        row.addStretch(1)
        text_col.addLayout(row)

        self.url_label = QLabel("")
        self.url_label.setStyleSheet("color:#6a7080; font-size:10px;")
        text_col.addWidget(self.url_label)
        lay.addLayout(text_col, 1)

        self._elide()

    def _elide(self):
        width = max(60, self.width() - 110)
        from PySide6.QtGui import QFontMetrics

        text = getattr(self, "_title_text", "") or ""
        fm = QFontMetrics(self.title.font())
        self.title.setText(fm.elidedText(text, Qt.ElideRight, width))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def set_loading(self):
        self._title_text = "Fetching title…"
        self.title.setText(self._title_text)
        self.url_label.setText(self._url)
        self.duration.setText("")
        self.thumb.setPixmap(QPixmap())

    def set_meta(self, meta: dict):
        platform = "TikTok" if _is_tiktok(self._url) else "YouTube"
        self.badge.setText(platform)
        title = str(meta.get("title") or "").strip()
        self._title_text = title or self._url
        self.title.setText(self._title_text)
        self.url_label.setText(self._url)
        duration = meta.get("duration") or 0
        self.duration.setText(_fmt_duration(duration) if duration else "")
        thumb_path = meta.get("thumb_path") or ""
        pixmap = QPixmap(thumb_path) if thumb_path and os.path.isfile(thumb_path) else QPixmap()
        if pixmap.isNull():
            self.thumb.setText("")
            return
        scaled = pixmap.scaled(80, 45, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.thumb.setPixmap(scaled)
        self.thumb.setStyleSheet("border-radius:4px;")


class MetaFetcher(QThread):
    """Fetches title/thumbnail/duration for a list of URLs (network calls)."""

    meta_ready = Signal(str, dict)  # url, meta (or {} on failure)

    def __init__(self, urls: list, thumb_dir: Path, parent=None):
        super().__init__(parent)
        self._urls = list(urls)
        self._thumb_dir = thumb_dir
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        from shorts_generator.downloader import fetch_meta, fetch_thumbnail

        for url in self._urls:
            if self._cancelled:
                break
            try:
                meta = fetch_meta(url) or {}
                if meta.get("thumbnail"):
                    path = fetch_thumbnail(
                        meta["thumbnail"], str(self._thumb_dir), _thumb_name(url)
                    )
                    if path:
                        meta["thumb_path"] = path
                self.meta_ready.emit(url, meta)
            except Exception:  # noqa: BLE001
                self.meta_ready.emit(url, {})


class QueueList(QListWidget):
    """Accepts drops of .txt files (URL per line) and plain text URLs."""

    urls_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setToolTip("Drop urls.txt or paste YouTube URLs")
        self.itemDoubleClicked.connect(self._open_item)

    # -- data ------------------------------------------------------------ #
    def urls(self) -> list:
        return [self.item(i).data(Qt.UserRole) for i in range(self.count())]

    def add_urls(self, urls: list) -> int:
        existing = set(self.urls())
        added = 0
        for u in urls:
            norm = _normalize(u)
            if norm and norm not in existing:
                item = QListWidgetItem()
                item.setData(Qt.UserRole, norm)
                item.setToolTip(norm)
                widget = QueueItemWidget(norm)
                item.setSizeHint(widget.sizeHint())
                self.addItem(item)
                self.setItemWidget(item, widget)
                existing.add(norm)
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

    def widget_for(self, url: str) -> QueueItemWidget | None:
        for i in range(self.count()):
            item = self.item(i)
            if item.data(Qt.UserRole) == url:
                return self.itemWidget(item)
        return None

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

    def _open_item(self, item: QListWidgetItem):
        url = item.data(Qt.UserRole) or ""
        if url:
            QDesktopServices.openUrl(QUrl(url))


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
        self._out_root = Path(os.getenv("LOCAL_OUTPUT_DIR") or "output")
        self._queue_path = self._out_root / "studio_queue.json"
        self._cache_path = self._out_root / "studio_queue_cache.json"
        self._thumb_dir = self._out_root / ".queue_thumbs"
        self._meta_cache = self._load_cache()
        self._meta_worker = None
        self._build()
        self._restore_queue()

    # -- meta cache ------------------------------------------------------ #
    def _load_cache(self) -> dict:
        try:
            if not self._cache_path.is_file():
                return {}
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            now = time.time()
            return {u: m for u, m in data.items()
                    if now - m.get("ts", 0) < _CACHE_TTL_SECONDS}
        except (OSError, ValueError):
            return {}

    def _save_cache(self):
        try:
            self._cache_path.write_text(
                json.dumps(self._meta_cache, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass

    def _refresh_meta(self):
        """Restart the metadata fetcher for URLs missing a fresh cache entry."""
        urls = self.queue.urls()
        missing = [u for u in urls if not self._meta_cache.get(u)]
        if not missing:
            return
        if self._meta_worker and self._meta_worker.isRunning():
            self._meta_worker.cancel()
        self._meta_worker = MetaFetcher(missing, self._thumb_dir, self)
        self._meta_worker.meta_ready.connect(self._on_meta)
        self._meta_worker.finished.connect(self._save_cache)
        self._meta_worker.start()

    def _on_meta(self, url: str, meta: dict):
        if meta:
            meta = {**meta, "ts": time.time()}
            self._meta_cache[url] = meta
        widget = self.queue.widget_for(url)
        if widget:
            widget.set_meta(meta)

    # -- queue state ----------------------------------------------------- #
    def _queue_state(self) -> dict:
        return {"mode": self.mode(), "urls": self.queue.urls()}

    def _save_queue(self):
        try:
            self._queue_path.parent.mkdir(parents=True, exist_ok=True)
            self._queue_path.write_text(
                json.dumps(self._queue_state(), ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass

    def _restore_queue(self):
        try:
            if not self._queue_path.is_file():
                return
            state = json.loads(self._queue_path.read_text(encoding="utf-8"))
            mode = state.get("mode")
            for i, (value, _label) in enumerate(self.MODES):
                if value == mode:
                    self.mode_combo.setCurrentIndex(i)
            self.queue.add_urls([u for u in state.get("urls", []) if u])
        except (OSError, ValueError):
            pass

    def _persist_hook(self):
        self.urls_changed.emit()
        self._save_queue()
        self._refresh_meta()

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
        self.queue.urls_changed.connect(self._persist_hook)
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
        self._save_queue()
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
