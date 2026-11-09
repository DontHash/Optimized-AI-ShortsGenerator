"""Shorts Creator page — YouTube queue, ranked results, embedded preview."""
import json
import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from . import icons
from .clip_card import VideoResult
from .pipeline_worker import PipelineWorker
from .preview import PreviewPanel
from .queue_list import SourcePanel
from .theme import TEXT_DIM
from .widgets import EmptyState, PageHeader


class ShortsCreatorPage(QWidget):
    """Rank + render YouTube clips: queue, results, and a preview pane."""

    log = Signal(str)
    status = Signal(str)
    busy = Signal(bool)

    def __init__(self, results_root: Path, parent=None):
        super().__init__(parent)
        self._results_root = results_root
        self._worker = None
        self._preview_visible = False
        self._settings_controls = {}
        self._build()

    # -- layout ----------------------------------------------------------- #
    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(14)

        self.preview_toggle = QPushButton("Preview")
        self.preview_toggle.setObjectName("ghost")
        self.preview_toggle.setIcon(icons.icon("film", TEXT_DIM, 16))
        self.preview_toggle.setCheckable(True)
        self.preview_toggle.toggled.connect(self._set_preview_visible)
        lay.addWidget(PageHeader(
            "shorts",
            "Shorts Creator",
            "Rank viral moments with AI, then render 9:16 shorts — all local.",
            action=self.preview_toggle,
        ))

        splitter = QSplitter(Qt.Horizontal)
        lay.addWidget(splitter, 1)

        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(10)

        self.sources = SourcePanel(
            mode="youtube",
            title="Source queue",
            subtitle="Drop YouTube URLs or a urls.txt file",
        )
        self.sources.start_requested.connect(self._start)
        self.sources.stop_requested.connect(self._stop)
        left_lay.addWidget(self.sources)

        self.results_scroll = QScrollArea()
        self.results_scroll.setWidgetResizable(True)
        self.results_host = QWidget()
        self.results_lay = QVBoxLayout(self.results_host)
        self.results_lay.setContentsMargins(2, 8, 8, 8)
        self.results_lay.setSpacing(10)
        self._empty = EmptyState(
            "shorts",
            "No results yet",
            "Add YouTube URLs to the queue and press Start — ranked clips "
            "land here with render and preview actions.",
        )
        self.results_lay.addWidget(self._empty)
        self.results_lay.addStretch(1)
        self.results_scroll.setWidget(self.results_host)
        left_lay.addWidget(self.results_scroll, 1)

        splitter.addWidget(left)

        self.preview = PreviewPanel()
        self.preview.setMinimumWidth(380)
        self.preview.hide()
        splitter.addWidget(self.preview)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([900, 0])
        self._splitter = splitter

        self.hint = QLabel("Tip: double-click a queue row to open the video in your browser.")
        self.hint.setObjectName("dim")
        lay.addWidget(self.hint)

    # -- queue lifecycle -------------------------------------------------- #
    def _options(self) -> dict:
        controls = self.settings_controls
        num_clips = int(controls["num_clips"][0].value())
        return {
            "num_clips": num_clips,
            "format": None,
            "language": None,
            "min_score": 0,
            "render": False,
            "accurate_cut": False,
            "force": False,
            "workers": 2,
        }

    def _start(self):
        urls = self.sources.queue.urls()
        if not urls:
            self.status.emit("Nothing to do — add some YouTube URLs first.")
            return
        if self._worker and self._worker.isRunning():
            return

        self._apply_settings_to_env()
        self._clear_results()
        mode = self.sources.mode()
        for url in urls:
            self.log.emit(f"queued [{mode}] {url}")

        self.sources.set_running(True)
        self.busy.emit(True)
        self.status.emit(f"Processing {len(urls)} video(s)…")

        self._worker = PipelineWorker(urls, self._options(), self)
        self._worker.video_done.connect(self._on_video_done)
        self._worker.log.connect(self.log.emit)
        self._worker.queue_done.connect(self._on_queue_done)
        self._worker.fatal.connect(lambda e: self.log.emit(f"[studio] fatal: {e}"))
        self._worker.start()

    def _stop(self):
        if self._worker and self._worker.isRunning():
            self.log.emit("[studio] stopping after current videos…")
            self._worker.cancel()

    def _on_video_done(self, entry: dict):
        if not entry.get("ok"):
            self.log.emit(f"FAIL {entry.get('url')}: {entry.get('error')}")
            self._add_result(VideoResult(entry, None, error=str(entry.get("error", ""))))
            return
        video_id = entry.get("video_id") or ""
        payload = {}
        if video_id:
            clips_path = self._results_root / video_id / "clips.json"
            if clips_path.is_file():
                try:
                    payload = json.loads(clips_path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as e:
                    self.log.emit(f"[studio] could not read {clips_path}: {e}")
            thumb = self._results_root / video_id / "thumbnail.jpg"
            payload.setdefault("thumbnail_path", str(thumb) if thumb.is_file() else "")
        self.log.emit(f"OK {video_id or entry.get('url')}: {entry.get('clips', 0)} clips")
        self._add_result(VideoResult(entry, payload))
        self.status.emit(f"Finished {video_id or entry.get('url')}")

    def _on_queue_done(self, report: dict):
        self.sources.set_running(False)
        self.busy.emit(False)
        ok = len(report.get("ok", []))
        failed = len(report.get("failed", []))
        cancelled = report.get("cancelled", False)
        tail = " (cancelled)" if cancelled else ""
        self.status.emit(f"Done — {ok} ok, {failed} failed{tail}")
        self.log.emit(f"[queue] done — {ok} ok, {failed} failed{tail}")

    # -- settings bridge --------------------------------------------------- #
    @property
    def settings_controls(self) -> dict:
        return self._settings_controls

    def bind_settings(self, controls: dict):
        self._settings_controls = controls

    def _apply_settings_to_env(self):
        import os

        for ctrl, env_key, kind in self._settings_controls.values():
            if env_key.startswith("_"):
                if env_key == "_SHORTS_FADE":
                    os.environ["SHORTS_FADE_SECONDS"] = str(ctrl.value())
                elif env_key == "_SHORTS_UPSCALE":
                    os.environ["SHORTS_MAX_UPSCALE"] = str(ctrl.value())
                continue
            if kind == "check":
                os.environ[env_key] = "true" if ctrl.isChecked() else "false"
            elif kind == "combo":
                os.environ[env_key] = ctrl.currentText()
            elif kind == "spin":
                os.environ[env_key] = str(ctrl.value())
            else:
                value = ctrl.text().strip()
                if value:
                    os.environ[env_key] = value

    # -- results ----------------------------------------------------------- #
    def _shutdown_results(self):
        for i in range(self.results_lay.count()):
            item = self.results_lay.itemAt(i)
            widget = item.widget() if item else None
            if widget is not None and hasattr(widget, "shutdown"):
                widget.shutdown()

    def _clear_results(self):
        """Remove result widgets without deleting the reusable empty state."""
        for i in range(self.results_lay.count() - 1, -1, -1):
            item = self.results_lay.itemAt(i)
            widget = item.widget() if item else None
            if widget is None or widget is self._empty:
                continue
            self.results_lay.takeAt(i)
            if hasattr(widget, "shutdown"):
                widget.shutdown()
            widget.deleteLater()
        self._empty.hide()

    def _add_result(self, widget):
        self.results_lay.insertWidget(self.results_lay.count() - 1, widget)
        self._empty.hide()
        if hasattr(widget, "_cards"):
            for card in widget._cards:
                card.preview_cb = self.play_preview

    def play_preview(self, video_id: str, start_seconds: float):
        from .clip_card import _video_assets

        _video_dir, source, _segments = _video_assets(video_id)
        if not source or not os.path.isfile(source):
            self.status.emit(f"Source not downloaded yet for {video_id}")
            return
        self._set_preview_visible(True)
        self.preview.play_file(source, start_seconds)

    def _set_preview_visible(self, visible: bool):
        self._preview_visible = visible
        self.preview.setVisible(visible)
        self.preview_toggle.setChecked(visible)
        if visible:
            self._splitter.setSizes([max(400, self._splitter.width() - 460), 420])

    def shutdown(self):
        """Cancel running work before the window closes."""
        self._stop()
        self.sources.shutdown()
        self._shutdown_results()
        if self._worker:
            self._worker.wait(3000)
