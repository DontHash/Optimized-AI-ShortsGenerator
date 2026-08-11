"""QThread wrapper around shorts_generator.tiktok.process_tiktok_queue."""
import sys

from PySide6.QtCore import QThread, Signal

from ._logpipe import LogPipe


class TikTokWorker(QThread):
    log = Signal(str)
    video_done = Signal(dict)
    queue_done = Signal(dict)
    fatal = Signal(str)

    def __init__(self, urls: list, options: dict, parent=None):
        super().__init__(parent)
        self._urls = list(urls)
        self._options = dict(options)
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        from shorts_generator.tiktok import process_tiktok_queue

        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = LogPipe(self.log.emit)
        sys.stderr = LogPipe(self.log.emit)
        try:
            report = process_tiktok_queue(
                self._urls,
                out_root=self._options.get("out_root"),
                workers=self._options.get("workers", 1),
                delay=self._options.get("delay", 0.0),
                on_video_done=self.video_done.emit,
                is_cancelled=lambda: self._cancelled,
            )
        except Exception as e:  # noqa: BLE001
            self.fatal.emit(str(e))
            report = {"ok": [], "failed": [{"ok": False, "url": "queue", "error": str(e)}]}
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        self.queue_done.emit(report)
