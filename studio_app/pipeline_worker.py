"""QThread wrapper around shorts_generator.queue.process_queue.

Captures stdout lines from the pipeline (they are print()-based) and re-emits
them as Qt signals so the UI log stays live. Env is applied before the first
shorts_generator import (deferred to run()) so settings take effect.
"""
import sys

from PySide6.QtCore import QThread, Signal


class _LogPipe:
    """Redirect target: buffers partial writes, emits whole lines."""

    def __init__(self, emit):
        self._emit = emit
        self._buf = ""

    def write(self, text):
        if not text:
            return
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.rstrip()
            if line:
                self._emit(line)

    def flush(self):
        pass

    def isatty(self):
        return False


class PipelineWorker(QThread):
    """Runs the queue. Emits log lines, per-video results, and a final report."""

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
        from shorts_generator.queue import process_queue

        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = _LogPipe(self.log.emit)
        sys.stderr = _LogPipe(self.log.emit)
        try:
            report = process_queue(
                self._urls,
                num_clips=self._options.get("num_clips", 3),
                download_format=self._options.get("format"),
                language=self._options.get("language"),
                min_score=self._options.get("min_score", 0),
                render=self._options.get("render", False),
                accurate_cut=self._options.get("accurate_cut", False),
                force=self._options.get("force", False),
                workers=self._options.get("workers", 1),
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
