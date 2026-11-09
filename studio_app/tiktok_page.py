"""TikTok Downloader page — watermark-free TikTok queue + result cards."""
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .clip_card import TikTokResult
from .queue_list import SourcePanel
from .tiktok_worker import TikTokWorker
from .widgets import EmptyState, PageHeader


class TikTokPage(QWidget):
    """Download TikTok videos without watermark, paced and logged."""

    log = Signal(str)
    status = Signal(str)
    busy = Signal(bool)

    def __init__(self, results_root: Path, parent=None):
        super().__init__(parent)
        self._results_root = results_root
        self._worker = None
        self._settings_controls = {}
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(14)
        lay.addWidget(PageHeader(
            "tiktok",
            "TikTok Downloader",
            "Watermark-free downloads with title, author, and stats.",
        ))

        self.sources = SourcePanel(
            mode="tiktok",
            title="Source queue",
            subtitle="Drop TikTok video URLs (no watermark — no ranking)",
        )
        self.sources.start_requested.connect(self._start)
        self.sources.stop_requested.connect(self._stop)
        lay.addWidget(self.sources)

        self.results_scroll = QScrollArea()
        self.results_scroll.setWidgetResizable(True)
        self.results_host = QWidget()
        self.results_lay = QVBoxLayout(self.results_host)
        self.results_lay.setContentsMargins(2, 8, 8, 8)
        self.results_lay.setSpacing(10)
        self._empty = EmptyState(
            "tiktok",
            "No downloads yet",
            "Paste TikTok video URLs and press Start — watermark-free videos "
            "land in output/tiktok/.",
        )
        self.results_lay.addWidget(self._empty)
        self.results_lay.addStretch(1)
        self.results_scroll.setWidget(self.results_host)
        lay.addWidget(self.results_scroll, 1)

        self.hint = QLabel("Tip: TikTok rate-limits aggressively — the queue paces itself.")
        self.hint.setObjectName("dim")
        lay.addWidget(self.hint)

    # -- queue lifecycle -------------------------------------------------- #
    def _start(self):
        urls = self.sources.queue.urls()
        if not urls:
            self.status.emit("Nothing to do — add some TikTok URLs first.")
            return
        if self._worker and self._worker.isRunning():
            return

        self._clear_results()
        for url in urls:
            self.log.emit(f"queued [tiktok] {url}")

        self.sources.set_running(True)
        self.busy.emit(True)
        self.status.emit(f"Processing {len(urls)} video(s)…")

        self._worker = TikTokWorker(
            urls,
            {"out_root": str(self._results_root), "workers": 1, "delay": self._tiktok_delay()},
            self,
        )
        self._worker.video_done.connect(self._on_tiktok_done)
        self._worker.log.connect(self.log.emit)
        self._worker.queue_done.connect(self._on_queue_done)
        self._worker.fatal.connect(lambda e: self.log.emit(f"[studio] fatal: {e}"))
        self._worker.start()

    def _tiktok_delay(self) -> float:
        try:
            return float(self._tiktok_delay_value())
        except (TypeError, ValueError):
            return 8.0

    def _tiktok_delay_value(self):
        if getattr(self, "_settings_controls", None):
            return self._settings_controls["tiktok_delay"][0].value()
        return 8.0

    def _stop(self):
        if self._worker and self._worker.isRunning():
            self.log.emit("[studio] stopping after current videos…")
            self._worker.cancel()

    def _on_tiktok_done(self, entry: dict):
        if entry.get("ok"):
            self.log.emit(f"OK tiktok/{entry.get('video_id')}: {entry.get('title')}")
        else:
            self.log.emit(f"FAIL {entry.get('url')}: {entry.get('error')}")
        self._add_result(TikTokResult(entry))
        self.status.emit(f"Finished tiktok/{entry.get('video_id') or '?'}")

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
    def bind_settings(self, controls: dict):
        self._settings_controls = controls

    # -- results ----------------------------------------------------------- #
    def _clear_results(self):
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

    def shutdown(self):
        """Cancel running work before the window closes."""
        self._stop()
        self.sources.shutdown()
        if self._worker:
            self._worker.wait(3000)
