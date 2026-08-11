"""Clip result card + per-video result section widgets."""
import json
import os

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from .theme import ACCENT, BAD, GOOD, WARN, score_color

SIGNAL_ORDER = [("llm", "LLM"), ("replay", "Replay"), ("audio", "Audio"), ("chapter", "Chapter")]


def _hms(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:04.1f}"


def _shorten(text: str, limit: int = 160) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _badge(text: str, color: str = "") -> QLabel:
    label = QLabel(text)
    label.setAlignment(Qt.AlignCenter)
    label.setObjectName("badge" + {"#3ecf8e": "Good", "#f5b544": "Warn", "#f06060": "Bad"}.get(color, ""))
    if color not in (GOOD, WARN, BAD):
        label.setStyleSheet(f"color:{color};")
    return label


class RenderWorker(QThread):
    """Renders one clip with ffmpeg in the background."""

    done = Signal(str, str, str)  # out_path or "", error message, clip title

    def __init__(self, source: str, clip: dict, out_dir: str, accurate: bool, parent=None):
        super().__init__(parent)
        self._source = source
        self._clip = clip
        self._out_dir = out_dir
        self._accurate = accurate

    def run(self):
        try:
            from shorts_generator.clipper import render_clips

            results = render_clips(self._source, [self._clip], self._out_dir, accurate=self._accurate)
            path = (results[0].get("clip_path") or "") if results else ""
            err = results[0].get("error", "") if results else "render produced no output"
            self.done.emit(path, err, str(self._clip.get("title", "clip")))
        except Exception as e:  # noqa: BLE001
            self.done.emit("", str(e), str(self._clip.get("title", "clip")))


class ClipCard(QFrame):
    """A single ranked clip: score, times, hook, signal breakdown, actions."""

    render_finished = Signal()

    def __init__(self, clip: dict, video_id: str, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self._clip = clip
        self._video_id = video_id
        self._render_worker = None
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        top = QHBoxLayout()
        score = int(self._clip.get("score", 0))
        top.addWidget(_badge(f"#{self._clip.get('rank', '?')}", ACCENT))
        top.addWidget(_badge(f"{score}", score_color(score)))
        title = QLabel(str(self._clip.get("title", "Untitled")))
        title.setObjectName("h2")
        title.setWordWrap(True)
        top.addWidget(title, 1)
        top.addWidget(_badge(f"{_hms(self._clip.get('start_time', 0))} → {_hms(self._clip.get('end_time', 0))}"))
        lay.addLayout(top)

        hook = str(self._clip.get("hook_sentence") or "").strip()
        if hook:
            hook_label = QLabel(f'"{_shorten(hook)}"')
            hook_label.setWordWrap(True)
            hook_label.setStyleSheet(f"color:{WARN}; font-style: italic;")
            lay.addWidget(hook_label)

        reason = str(self._clip.get("virality_reason") or "").strip()
        if reason:
            reason_label = QLabel(_shorten(reason, 220))
            reason_label.setObjectName("dim")
            reason_label.setWordWrap(True)
            lay.addWidget(reason_label)

        excerpt = str(self._clip.get("transcript_excerpt") or "").strip()
        if excerpt:
            excerpt_label = QLabel(_shorten(excerpt, 280))
            excerpt_label.setWordWrap(True)
            excerpt_label.setStyleSheet("color:#c7cbd6; font-size:12px;")
            lay.addWidget(excerpt_label)

        signals = self._clip.get("signals") or {}
        if isinstance(signals, dict) and signals.get("signals_present"):
            bars = QHBoxLayout()
            bars.setSpacing(10)
            for key, label in SIGNAL_ORDER:
                if key in signals.get("signals_present", []):
                    val = float(signals.get(key, 0.0) or 0.0)
                    wrap = QVBoxLayout()
                    wrap.setSpacing(2)
                    bar = QProgressBar()
                    bar.setRange(0, 100)
                    bar.setValue(int(round(val * 100)))
                    bar.setTextVisible(False)
                    bar.setFixedWidth(64)
                    name = QLabel(f"{label} {val:.2f}")
                    name.setObjectName("dim")
                    name.setStyleSheet("font-size:11px;")
                    wrap.addWidget(bar, 0, Qt.AlignLeft)
                    wrap.addWidget(name)
                    bars.addLayout(wrap)
            bars.addStretch(1)
            lay.addLayout(bars)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.render_btn = QPushButton("Render MP4")
        self.render_btn.clicked.connect(self._start_render)
        actions.addWidget(self.render_btn)
        self.yt_btn = QPushButton("Open in YouTube")
        self.yt_btn.setObjectName("ghost")
        self.yt_btn.clicked.connect(self._open_youtube)
        actions.addWidget(self.yt_btn)
        self.open_btn = QPushButton("Open File")
        self.open_btn.setObjectName("ghost")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_file)
        actions.addWidget(self.open_btn)
        copy_btn = QPushButton("Copy JSON")
        copy_btn.setObjectName("ghost")
        copy_btn.clicked.connect(self._copy_json)
        actions.addWidget(copy_btn)
        lay.addLayout(actions)

    # -- actions --------------------------------------------------------- #
    def _clip_path(self) -> str:
        path = self._clip.get("clip_path") or ""
        return path if os.path.isfile(path) else ""

    def _open_youtube(self):
        start = int(float(self._clip.get("start_time", 0)))
        QDesktopServices.openUrl(QUrl(f"https://youtu.be/{self._video_id}?t={start}"))

    def _open_file(self):
        path = self._clip.get("clip_path") or ""
        if path and os.path.isfile(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _copy_json(self):
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(json.dumps(self._clip, indent=2, ensure_ascii=False))

    def _start_render(self):
        from shorts_generator.config import OUTPUT_DIR
        from shorts_generator.downloader import find_local_source

        if self._render_worker and self._render_worker.isRunning():
            return
        out_root = os.getenv("LOCAL_OUTPUT_DIR") or OUTPUT_DIR
        video_dir = os.path.join(out_root, self._video_id)
        source = find_local_source(video_dir, self._video_id) or ""
        if not source or not os.path.isfile(source):
            self.render_btn.setText("Download source first")
            return
        self.render_btn.setEnabled(False)
        self.render_btn.setText("Rendering…")
        self._render_worker = RenderWorker(source, self._clip, video_dir, False, self)
        self._render_worker.done.connect(self._render_done)
        self._render_worker.start()

    def _render_done(self, path: str, error: str, title: str):
        self.render_btn.setEnabled(True)
        if path and os.path.isfile(path):
            self._clip["clip_path"] = path
            self.render_btn.setText("Rendered ✓")
            self.open_btn.setEnabled(True)
        else:
            self.render_btn.setText("Render failed")
            self.render_btn.setToolTip(error or "unknown error")
        self.render_finished.emit()


class VideoResult(QFrame):
    """One video's result section: header + N clip cards."""

    def __init__(self, entry: dict, payload: dict | None, error: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self._build(entry, payload, error)

    def _build(self, entry: dict, payload: dict | None, error: str):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        header = QHBoxLayout()
        video_id = entry.get("video_id") or entry.get("url", "?")
        if error:
            header.addWidget(_badge("FAIL", BAD))
            title = QLabel(video_id)
            title.setObjectName("h2")
            header.addWidget(title, 1)
            lay.addLayout(header)
            err = QLabel(_shorten(error, 300))
            err.setStyleSheet(f"color:{BAD};")
            err.setWordWrap(True)
            lay.addWidget(err)
            return

        header.addWidget(_badge(f"{entry.get('clips', 0)} clips", GOOD))
        title_text = (payload or {}).get("video_title") or video_id
        title = QLabel(_shorten(title_text, 90))
        title.setObjectName("h2")
        header.addWidget(title, 1)
        duration = (payload or {}).get("duration") or 0
        header.addWidget(_badge(_hms(duration)))
        lay.addLayout(header)

        clips = (payload or {}).get("clips") or []
        for clip in clips:
            card = ClipCard(clip, video_id)
            lay.addWidget(card)
        if not clips:
            no = QLabel("No clips met the threshold for this video.")
            no.setObjectName("dim")
            lay.addWidget(no)
