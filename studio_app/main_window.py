"""ClipClipper Studio main window: queue + results + settings + log."""
import json
import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .clip_card import TikTokResult, VideoResult
from .pipeline_worker import PipelineWorker
from .queue_list import SourcePanel
from .settings_panel import SettingsPanel
from .tiktok_worker import TikTokWorker


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ClipClipper Studio — find viral moments")
        self.resize(1280, 820)
        self._worker = None
        self._results_root = Path(os.getenv("LOCAL_OUTPUT_DIR") or "output")
        self._build()

    def _build(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        # -- left: sources + queue --------------------------------------- #
        self.sources = SourcePanel()
        self.sources.start_requested.connect(self._start)
        self.sources.stop_requested.connect(self._stop)
        splitter.addWidget(self.sources)
        splitter.setStretchFactor(0, 0)

        # -- right: results / settings / log ----------------------------- #
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(8)

        self.tabs = QTabWidget()
        self.results_scroll = QScrollArea()
        self.results_scroll.setWidgetResizable(True)
        self.results_scroll.setMinimumWidth(560)
        self.results_host = QWidget()
        self.results_lay = QVBoxLayout(self.results_host)
        self.results_lay.setContentsMargins(2, 8, 8, 8)
        self.results_lay.setSpacing(10)
        self.results_lay.addStretch(1)
        self.results_scroll.setWidget(self.results_host)
        self.tabs.addTab(self.results_scroll, "Results")

        self.settings = SettingsPanel()
        self.tabs.addTab(self.settings, "Settings")

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.tabs.addTab(self.log_view, "Log")
        right_lay.addWidget(self.tabs, 1)

        # -- status bar --------------------------------------------------- #
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # busy indicator while running
        self.progress.setVisible(False)
        self.progress.setFixedWidth(220)
        self.status_label = QLabel("Ready — add YouTube URLs and press Start")
        self.status_label.setObjectName("dim")
        self.statusBar().addWidget(self.status_label, 1)
        self.statusBar().addPermanentWidget(self.progress)

        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 960])

    # -- queue lifecycle -------------------------------------------------- #
    def _options(self) -> dict:
        controls = self.settings._controls
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
            self.status_label.setText("Nothing to do — add some URLs first.")
            return
        if self._worker and self._worker.isRunning():
            return

        self._apply_settings_to_env()

        self._clear_results()
        self.log_view.clear()
        mode = self.sources.mode()
        for url in urls:
            self.log(f"queued [{mode}] {url}")

        self.sources.set_running(True)
        self.progress.setVisible(True)
        self.status_label.setText(f"Processing {len(urls)} video(s)…")

        if mode == "tiktok":
            delay = self.settings._controls["tiktok_delay"][0].value()
            self._worker = TikTokWorker(
                urls,
                {"out_root": str(self._results_root), "workers": 1, "delay": float(delay)},
                self,
            )
            self._worker.video_done.connect(self._on_tiktok_done)
        else:
            self._worker = PipelineWorker(urls, self._options(), self)
            self._worker.video_done.connect(self._on_video_done)
        self._worker.log.connect(self.log)
        self._worker.queue_done.connect(self._on_queue_done)
        self._worker.fatal.connect(lambda e: self.log(f"[studio] fatal: {e}"))
        self._worker.start()

    def _stop(self):
        if self._worker and self._worker.isRunning():
            self.log("[studio] stopping after current videos…")
            self._worker.cancel()

    def _on_video_done(self, entry: dict):
        if not entry.get("ok"):
            self.log(f"FAIL {entry.get('url')}: {entry.get('error')}")
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
                    self.log(f"[studio] could not read {clips_path}: {e}")
            # thumbnail may predate the payload (re-run of an old run)
            thumb = self._results_root / video_id / "thumbnail.jpg"
            payload.setdefault("thumbnail_path", str(thumb) if thumb.is_file() else "")
        self.log(
            f"OK {video_id or entry.get('url')}: {entry.get('clips', 0)} clips"
        )
        self._add_result(VideoResult(entry, payload))
        self.status_label.setText(f"Finished {entry.get('video_id') or entry.get('url')}")

    def _on_tiktok_done(self, entry: dict):
        if entry.get("ok"):
            self.log(f"OK tiktok/{entry.get('video_id')}: {entry.get('title')}")
        else:
            self.log(f"FAIL {entry.get('url')}: {entry.get('error')}")
        self._add_result(TikTokResult(entry))
        self.status_label.setText(f"Finished tiktok/{entry.get('video_id') or '?'}")

    def _on_queue_done(self, report: dict):
        self.sources.set_running(False)
        self.progress.setVisible(False)
        ok = len(report.get("ok", []))
        failed = len(report.get("failed", []))
        cancelled = report.get("cancelled", False)
        tail = " (cancelled)" if cancelled else ""
        self.status_label.setText(f"Done — {ok} ok, {failed} failed{tail}")
        self.log(f"[queue] done — {ok} ok, {failed} failed{tail}")

    # -- helpers ---------------------------------------------------------- #
    def _apply_settings_to_env(self):
        """Push current settings into the process env so the worker's config
        import (deferred to run()) picks them up without a restart."""
        import os

        for ctrl, env_key, kind in self.settings._controls.values():
            if env_key.startswith("_"):
                if env_key == "_SHORTS_FADE":
                    os.environ["SHORTS_FADE_SECONDS"] = str(ctrl.value())
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

    def log(self, line: str):
        self.log_view.appendPlainText(line)

    def _clear_results(self):
        while self.results_lay.count() > 1:  # keep trailing stretch
            item = self.results_lay.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _add_result(self, widget):
        self.results_lay.insertWidget(self.results_lay.count() - 1, widget)
