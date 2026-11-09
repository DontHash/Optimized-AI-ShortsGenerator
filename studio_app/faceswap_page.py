"""Face Swap page — pick a video + reference photo, run locally, keep results."""
import os
import time
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from . import icons
from .faceswap_worker import FaceSwapWorker
from .theme import TEXT_DIM
from .widgets import EmptyState, PageHeader, Spinner

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


class DropZone(QFrame):
    """Drag-and-drop file target with a browse button."""

    file_selected = Signal(str)

    def __init__(self, icon_name: str, title: str, hint: str, exts: set, parent=None):
        super().__init__(parent)
        self.setObjectName("dropzone")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self._exts = exts
        self._path = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(6)

        self.icon = QLabel()
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon.setPixmap(icons.icon(icon_name, TEXT_DIM, 30).pixmap(30, 30))
        lay.addWidget(self.icon)

        self.title = QLabel(title)
        self.title.setObjectName("h3")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.title)

        self.path_label = QLabel(hint)
        self.path_label.setObjectName("faint")
        self.path_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.path_label.setWordWrap(True)
        lay.addWidget(self.path_label)

        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.setObjectName("ghost")
        self.browse_btn.clicked.connect(self._browse)
        lay.addWidget(self.browse_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        self.thumb = QLabel()
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.hide()
        lay.addWidget(self.thumb)

    def path(self) -> str:
        return self._path

    def set_path(self, path: str):
        self._path = path
        self.path_label.setText(os.path.basename(path))
        self.path_label.setStyleSheet(f"color:{TEXT_DIM};")
        self.title.setText("Ready")

    def clear(self):
        self._path = ""

    # -- drag & drop ------------------------------------------------------ #
    def dragEnterEvent(self, event: QDragEnterEvent):
        if self._accepts(event):
            self.setProperty("active", True)
            self.style().unpolish(self)
            self.style().polish(self)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setProperty("active", False)
        self.style().unpolish(self)
        self.style().polish(self)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent):
        self.setProperty("active", False)
        self.style().unpolish(self)
        self.style().polish(self)
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(tuple(self._exts)):
                self.set_path(path)
                self.file_selected.emit(path)
                event.acceptProposedAction()
                return
        event.ignore()

    def _accepts(self, event: QDragEnterEvent) -> bool:
        for url in event.mimeData().urls():
            if url.toLocalFile().lower().endswith(tuple(self._exts)):
                return True
        return False

    def _browse(self):
        exts = " ".join(f"*{e}" for e in sorted(self._exts))
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose file", "", f"Media files ({exts})")
        if path:
            self.set_path(path)
            self.file_selected.emit(path)


class FaceSwapResult(QFrame):
    """One finished swap: stats, preview-able file actions."""

    def __init__(self, result: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self._result = result
        self._build()

    def _badge(self, text: str, variant: str = "") -> QLabel:
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name = {"good": "Good", "warn": "Warn", "bad": "Bad", "accent": "Accent"}.get(variant, "")
        label.setObjectName("badge" + name)
        return label

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        result = self._result
        header = QHBoxLayout()
        out_path = result.get("out_path") or ""
        name = os.path.basename(out_path) if out_path else "face swap"
        header.addWidget(self._badge("SWAP", "accent"))
        title = QLabel(name)
        title.setObjectName("h2")
        title.setWordWrap(True)
        header.addWidget(title, 1)
        if result.get("frames"):
            header.addWidget(self._badge(f"{result.get('frames')} frames"))
            header.addWidget(self._badge(
                f"{result.get('width')}×{result.get('height')}"))
        lay.addLayout(header)

        meta = QHBoxLayout()
        if result.get("swapped_frames"):
            meta.addWidget(self._badge(
                f"{result.get('swapped_frames')} faces swapped", "good"))
        if result.get("seconds"):
            meta.addWidget(self._badge(
                f"{result.get('seconds'):.1f}s @ {result.get('fps', 0):.1f}fps"))
        meta.addStretch(1)
        lay.addLayout(meta)

        actions = QHBoxLayout()
        actions.addStretch(1)
        open_btn = QPushButton("Open File")
        open_btn.setObjectName("primary")
        open_btn.setIcon(icons.icon("folder", "#0a0e1c", 16))
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(out_path)))
        actions.addWidget(open_btn)
        copy_btn = QPushButton("Copy Path")
        copy_btn.setObjectName("ghost")
        copy_btn.clicked.connect(lambda: self._copy_path(out_path))
        actions.addWidget(copy_btn)
        lay.addLayout(actions)

    def _copy_path(self, path: str):
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(path)


class FaceSwapPage(QWidget):
    """Video + reference image -> swapped video, run locally with live progress."""

    log = Signal(str)
    status = Signal(str)
    busy = Signal(bool)

    def __init__(self, results_root: Path, parent=None):
        super().__init__(parent)
        self._out_root = results_root
        self._worker = None
        self._face_pixmap = None
        self._settings_controls = {}
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(14)

        lay.addWidget(PageHeader(
            "swap",
            "Face Swap",
            "Swap a face from one photo into a single-person video — fully local.",
            action=self._device_combo(),
        ))

        inputs = QHBoxLayout()
        inputs.setSpacing(14)
        self.video_zone = DropZone("film", "Video", "Drop a video file (mp4, mkv, webm…)", VIDEO_EXTS)
        self.face_zone = DropZone("image", "Reference photo", "Drop a clear face photo", IMAGE_EXTS)
        self.face_zone.file_selected.connect(self._on_face_selected)
        inputs.addWidget(self.video_zone, 1)
        inputs.addWidget(self.face_zone, 1)
        lay.addLayout(inputs)

        run_row = QHBoxLayout()
        run_row.setSpacing(10)
        self.start_btn = QPushButton("Start Swap")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self._start)
        run_row.addWidget(self.start_btn)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        run_row.addWidget(self.stop_btn)
        self.spinner = Spinner(18)
        run_row.addWidget(self.spinner)
        self.status_line = QLabel("Ready — pick a video and a reference photo.")
        self.status_line.setObjectName("dim")
        run_row.addWidget(self.status_line, 1)
        lay.addLayout(run_row)

        job_box = QHBoxLayout()
        job_box.setSpacing(12)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        job_box.addWidget(self.progress, 1)
        self.pct_label = QLabel("")
        self.pct_label.setObjectName("dim")
        job_box.addWidget(self.pct_label)
        self.frame_view = QLabel()
        self.frame_view.setFixedSize(240, 135)
        self.frame_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.frame_view.setStyleSheet("background-color:#0b0d12; border-radius:8px;")
        job_box.addWidget(self.frame_view)
        lay.addLayout(job_box)

        self.results_scroll = QScrollArea()
        self.results_scroll.setWidgetResizable(True)
        self.results_host = QWidget()
        self.results_lay = QVBoxLayout(self.results_host)
        self.results_lay.setContentsMargins(2, 8, 8, 8)
        self.results_lay.setSpacing(10)
        self._empty = EmptyState(
            "swap",
            "No swaps yet",
            "Drop a video and a reference photo, then press Start Swap — "
            "results land here.",
        )
        self.results_lay.addWidget(self._empty)
        self.results_lay.addStretch(1)
        self.results_scroll.setWidget(self.results_host)
        lay.addWidget(self.results_scroll, 1)

        self.hint = QLabel(
            "Tip: first run downloads ~850 MB of ONNX models into models/faceswap/. "
            "Auto uses your GPU (CUDA or DirectML) when available."
        )
        self.hint.setObjectName("dim")
        lay.addWidget(self.hint)

    def _device_combo(self) -> QWidget:
        wrap = QWidget()
        h = QHBoxLayout(wrap)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        lbl = QLabel("Device")
        lbl.setObjectName("dim")
        h.addWidget(lbl)
        self.device_combo = QComboBox()
        self.device_combo.addItem("Auto (GPU if available)", "auto")
        self.device_combo.addItem("CPU", "cpu")
        self.device_combo.addItem("GPU (CUDA / DirectML)", "gpu")
        self.device_combo.setCurrentIndex(
            {"cpu": 1, "gpu": 2}.get(os.getenv("FACESWAP_DEVICE", "auto"), 0))
        h.addWidget(self.device_combo)
        return wrap

    # -- wiring ----------------------------------------------------------- #
    def bind_settings(self, controls: dict):
        self._settings_controls = controls

    def _on_face_selected(self, path: str):
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return
        self.face_zone.thumb.setPixmap(pixmap.scaled(
            200, 110, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.face_zone.thumb.show()

    # -- job lifecycle ---------------------------------------------------- #
    def _start(self):
        video = self.video_zone.path()
        face = self.face_zone.path()
        if not video or not os.path.isfile(video):
            self.status_line.setText("Choose a video file first.")
            return
        if not face or not os.path.isfile(face):
            self.status_line.setText("Choose a reference photo first.")
            return
        if self._worker and self._worker.isRunning():
            return

        out_dir = self._out_root / "faceswap"
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(video).stem
        out_path = str(out_dir / f"{stem}_{int(time.time())}_swapped.mp4")

        self._clear_results()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.spinner.set_running(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.pct_label.setText("0%")
        self.status_line.setText("Swapping…")
        self.busy.emit(True)

        self._worker = FaceSwapWorker(
            video, face, out_path, self.device_combo.currentData(), self)
        self._worker.progress.connect(self._on_progress)
        self._worker.frame_preview.connect(self._on_frame)
        self._worker.log.connect(self.log.emit)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _stop(self):
        if self._worker and self._worker.isRunning():
            self.status_line.setText("Stopping…")
            self._worker.cancel()

    def _on_progress(self, index: int, total: int):
        if total <= 0:
            return
        pct = int(100 * index / total)
        self.progress.setRange(0, total)
        self.progress.setValue(index)
        self.pct_label.setText(f"{pct}%")
        self.status_line.setText(f"Swapping… {index}/{total} frames")

    def _on_frame(self, frame):
        h, w = frame.shape[:2]
        img = QImage(frame.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        self.frame_view.setPixmap(QPixmap.fromImage(img).scaled(
            240, 135, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _on_done(self, result: dict):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.spinner.set_running(False)
        self.progress.setVisible(False)
        self.busy.emit(False)
        if not result.get("ok"):
            error = str(result.get("error", "unknown error"))
            self.status_line.setText("Swap failed.")
            self.log.emit(f"[faceswap] FAIL: {error}")
            QMessageBox.warning(self, "Face swap failed", error)
            return
        self.pct_label.setText("100%")
        self.status_line.setText(f"Done — {result.get('swapped_frames')} faces swapped.")
        self.log.emit(f"[faceswap] OK {result.get('out_path')}")
        card = FaceSwapResult(result)
        self.results_lay.insertWidget(self.results_lay.count() - 1, card)
        self._empty.hide()
        self.frame_view.clear()

    # -- results ---------------------------------------------------------- #
    def _clear_results(self):
        """Remove result cards without deleting the reusable empty state."""
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

    def shutdown(self):
        """Cancel a running swap before the window closes."""
        self._stop()
        if self._worker:
            self._worker.wait(3000)
