"""QThread wrapper around shorts_generator.faceswap.swap_video."""
import sys

from PySide6.QtCore import QThread, Signal

from ._logpipe import LogPipe


class FaceSwapWorker(QThread):
    """Runs one face-swap job. Emits log lines, frame progress, previews."""

    log = Signal(str)
    progress = Signal(int, int)  # current frame, total frames
    frame_preview = Signal(object)  # numpy RGB frame (throttled)
    done = Signal(dict)  # {ok, out_path, error, frames, ...}

    def __init__(self, video_path: str, ref_image_path: str, out_path: str,
                 device: str = "auto", parent=None):
        super().__init__(parent)
        self._video = video_path
        self._face = ref_image_path
        self._out = out_path
        self._device = device
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        from shorts_generator.faceswap import FaceSwapError, swap_video
        from shorts_generator.faceswap.models import ensure_models

        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = LogPipe(self.log.emit)
        sys.stderr = LogPipe(self.log.emit)
        try:
            try:
                ensure_models(progress_cb=self._model_progress)
            except Exception as e:  # noqa: BLE001
                self.done.emit({"ok": False, "error": f"Model download failed: {e}"})
                return
            result = swap_video(
                self._video,
                self._face,
                self._out,
                device=self._device,
                progress_cb=self._on_progress,
                frame_cb=self._on_frame,
                is_cancelled=lambda: self._cancelled,
            )
            self.done.emit({**result, "ok": True})
        except FaceSwapError as e:
            self.done.emit({"ok": False, "error": str(e)})
        except Exception as e:  # noqa: BLE001
            self.done.emit({"ok": False, "error": str(e)})
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    def _model_progress(self, label: str, done: int, total: int):
        if total:
            self.log.emit(f"[model] {label}  {int(100 * done / total)}%")
        else:
            self.log.emit(f"[model] {label} …")

    def _on_progress(self, index: int, total: int):
        self.progress.emit(index, total)

    def _on_frame(self, frame):
        self.frame_preview.emit(frame)
