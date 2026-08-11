"""Shared stdout capture for GUI workers: emits whole lines via a callback."""


class LogPipe:
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
