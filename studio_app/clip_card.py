"""Clip result card + per-video result section widgets."""
import json
import os
import re

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
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


def _thumbnail_widget(path: str, width: int = 160) -> QLabel | None:
    """A QLabel with the image scaled to `width` px, or None if the file is unusable."""
    if not path or not os.path.isfile(path):
        return None
    pixmap = QPixmap(path)
    if pixmap.isNull():
        return None
    label = QLabel()
    label.setFixedWidth(width)
    label.setPixmap(pixmap.scaledToWidth(width, Qt.SmoothTransformation))
    label.setStyleSheet("border-radius:6px;")
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


class ShortsRenderWorker(QThread):
    """Renders one 9:16 short (face-aware crop + optional captions)."""

    done = Signal(str, str, str)  # short_path or "", error, title

    def __init__(self, source: str, clip: dict, out_dir: str, segments: list, parent=None):
        super().__init__(parent)
        self._source = source
        self._clip = clip
        self._out_dir = out_dir
        self._segments = segments

    def run(self):
        try:
            from shorts_generator.clipper import render_shorts

            result = render_shorts(self._source, self._clip, self._out_dir, self._segments)
            path = result.get("short_path") or ""
            err = result.get("error", "")
            self.done.emit(path, err, str(self._clip.get("title", "clip")))
        except Exception as e:  # noqa: BLE001
            self.done.emit("", str(e), str(self._clip.get("title", "clip")))


class BatchShortsWorker(QThread):
    """Renders every clip of one video as 9:16 shorts."""

    done = Signal(list)

    def __init__(self, source: str, clips: list, out_dir: str, segments: list, parent=None):
        super().__init__(parent)
        self._source = source
        self._clips = clips
        self._out_dir = out_dir
        self._segments = segments

    def run(self):
        try:
            from shorts_generator.clipper import render_all_shorts

            results = render_all_shorts(self._source, self._clips, self._out_dir, self._segments)
            self.done.emit(results)
        except Exception as e:  # noqa: BLE001
            self.done.emit([{"error": str(e), "short_path": None} for _ in self._clips])


class AudioExtractWorker(QThread):
    """Extracts MP3 audio from a downloaded video."""

    done = Signal(str, str)  # mp3 path or "", error

    def __init__(self, source: str, out_path: str, parent=None):
        super().__init__(parent)
        self._source = source
        self._out_path = out_path

    def run(self):
        try:
            from shorts_generator.clipper import extract_audio

            self.done.emit(extract_audio(self._source, self._out_path), "")
        except Exception as e:  # noqa: BLE001
            self.done.emit("", str(e))


def _video_assets(video_id: str) -> tuple:
    """(video_dir, source_path, transcript_segments) for a video id."""
    from shorts_generator.config import OUTPUT_DIR
    from shorts_generator.downloader import find_local_source
    from shorts_generator.transcriber import load_srt_file

    out_root = os.getenv("LOCAL_OUTPUT_DIR") or OUTPUT_DIR
    video_dir = os.path.join(out_root, video_id)
    source = find_local_source(video_dir, video_id) or ""
    segments = []
    if os.path.isdir(video_dir):
        for name in sorted(os.listdir(video_dir)):
            if name.endswith(".srt") and not name.endswith(".words.srt"):
                try:
                    loaded = load_srt_file(os.path.join(video_dir, name))
                    segments = loaded.get("segments", [])
                except (OSError, ValueError):
                    pass
                break
    return video_dir, source, segments


class ClipCard(QFrame):
    """A single ranked clip: score, times, hook, signal breakdown, actions."""

    render_finished = Signal()

    def __init__(self, clip: dict, video_id: str, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self._clip = clip
        self._video_id = video_id
        self._render_worker = None
        self._shorts_worker = None
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
        self.short_btn = QPushButton("Render Short 9:16")
        self.short_btn.clicked.connect(self._start_shorts)
        actions.addWidget(self.short_btn)
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
        upload_btn = QPushButton("Copy Upload Text")
        upload_btn.setObjectName("ghost")
        upload_btn.clicked.connect(self._copy_upload_text)
        actions.addWidget(upload_btn)
        copy_btn = QPushButton("Copy JSON")
        copy_btn.setObjectName("ghost")
        copy_btn.clicked.connect(self._copy_json)
        actions.addWidget(copy_btn)
        lay.addLayout(actions)

        self.thumb_label = QLabel()
        self.thumb_label.setVisible(False)
        lay.addWidget(self.thumb_label)

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

    # -- shorts ---------------------------------------------------------- #
    def _start_shorts(self):
        if self._shorts_worker and self._shorts_worker.isRunning():
            return
        video_dir, source, segments = _video_assets(self._video_id)
        if not source or not os.path.isfile(source):
            self.short_btn.setText("Download source first")
            return
        self.short_btn.setEnabled(False)
        self.short_btn.setText("Rendering short…")
        self._shorts_worker = ShortsRenderWorker(source, self._clip, video_dir, segments, self)
        self._shorts_worker.done.connect(self._shorts_done)
        self._shorts_worker.start()

    def _shorts_done(self, path: str, error: str, title: str):
        self.short_btn.setEnabled(True)
        if path and os.path.isfile(path):
            self._clip["short_path"] = path
            self._clip["thumb_path"] = (self._clip.get("thumb_path")
                                        or os.path.splitext(path)[0] + ".jpg")
            self.short_btn.setText("Short ✓")
            self._show_thumbnail(self._clip.get("thumb_path"))
            self.open_btn.setEnabled(True)
        else:
            self.short_btn.setText("Short failed")
            self.short_btn.setToolTip(error or "unknown error")
        self.render_finished.emit()

    def _show_thumbnail(self, path: str):
        pixmap = QPixmap(path) if path and os.path.isfile(path) else QPixmap()
        if not pixmap.isNull():
            self.thumb_label.setPixmap(pixmap.scaledToWidth(240, Qt.SmoothTransformation))
            self.thumb_label.setVisible(True)

    def _copy_upload_text(self):
        from PySide6.QtWidgets import QApplication

        title = str(self._clip.get("title", "")).strip()
        words = [w for w in re.findall(r"[a-zA-Z0-9]{4,}", title.lower())
                 if w not in {"with", "that", "this", "your", "from", "have", "they", "what",
                              "when", "them", "about", "would", "there", "their", "these",
                              "being", "could", "because", "really", "thing", "things"}]
        hashtags = " ".join("#" + w for w in list(dict.fromkeys(words))[:4])
        text = title
        if hashtags:
            text += "\n\n" + hashtags + " #shorts #fyp"
        QApplication.clipboard().setText(text)


class VideoResult(QFrame):
    """One video's result section: header + N clip cards."""

    def __init__(self, entry: dict, payload: dict | None, error: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self._entry = entry
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

        thumb = _thumbnail_widget((payload or {}).get("thumbnail_path") or "")
        if thumb:
            header.addWidget(thumb)
        header.addWidget(_badge(f"{entry.get('clips', 0)} clips", GOOD))
        title_text = (payload or {}).get("video_title") or video_id
        title = QLabel(_shorten(title_text, 90))
        title.setObjectName("h2")
        header.addWidget(title, 1)
        duration = (payload or {}).get("duration") or 0
        header.addWidget(_badge(_hms(duration)))
        lay.addLayout(header)

        self._cards = []
        self._batch_worker = None
        clips = (payload or {}).get("clips") or []
        for clip in clips:
            card = ClipCard(clip, video_id)
            self._cards.append(card)
            lay.addWidget(card)
        if clips:
            batch_row = QHBoxLayout()
            batch_row.addStretch(1)
            self.batch_btn = QPushButton("Render all as Shorts 9:16")
            self.batch_btn.setObjectName("ghost")
            self.batch_btn.clicked.connect(self._start_batch)
            batch_row.addWidget(self.batch_btn)
            lay.addLayout(batch_row)
        if not clips:
            no = QLabel("No clips met the threshold for this video.")
            no.setObjectName("dim")
            lay.addWidget(no)

    def _start_batch(self):
        if self._batch_worker and self._batch_worker.isRunning():
            return
        video_id = self._entry.get("video_id") or ""
        video_dir, source, segments = _video_assets(video_id)
        if not source or not os.path.isfile(source):
            self.batch_btn.setText("Download source first")
            return
        self.batch_btn.setEnabled(False)
        self.batch_btn.setText("Rendering shorts…")
        clips = [card._clip for card in self._cards]
        self._batch_worker = BatchShortsWorker(source, clips, video_dir, segments, self)
        self._batch_worker.done.connect(self._batch_done)
        self._batch_worker.start()

    def _batch_done(self, results: list):
        self.batch_btn.setEnabled(True)
        self.batch_btn.setText("Render all as Shorts 9:16")
        for card, result in zip(self._cards, results, strict=False):
            if result.get("short_path") and os.path.isfile(result["short_path"]):
                card._shorts_done(result["short_path"], "", str(card._clip.get("title", "clip")))


def _format_count(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


class TikTokResult(QFrame):
    """A downloaded TikTok video: thumbnail, title, author, stats, actions."""

    def __init__(self, entry: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self._entry = entry
        self._mp3_worker = None
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        entry = self._entry

        if not entry.get("ok"):
            header = QHBoxLayout()
            header.addWidget(_badge("FAIL", BAD))
            title = QLabel(entry.get("url", "?"))
            title.setObjectName("h2")
            header.addWidget(title, 1)
            lay.addLayout(header)
            err = QLabel(_shorten(str(entry.get("error", "")), 300))
            err.setStyleSheet(f"color:{BAD};")
            err.setWordWrap(True)
            lay.addWidget(err)
            return

        header = QHBoxLayout()
        thumb = _thumbnail_widget(entry.get("thumbnail_path") or "", 140)
        if thumb:
            header.addWidget(thumb)
        header.addWidget(_badge("DOWNLOADED", GOOD))
        title = QLabel(_shorten(str(entry.get("title", "TikTok video")), 80))
        title.setObjectName("h2")
        title.setWordWrap(True)
        header.addWidget(title, 1)
        if entry.get("duration"):
            header.addWidget(_badge(_hms(float(entry["duration"]))))
        lay.addLayout(header)

        meta = QHBoxLayout()
        author = str(entry.get("author") or "unknown")
        meta.addWidget(_badge(f"@{author}"))
        stats = entry.get("stats") or {}
        if stats.get("views"):
            meta.addWidget(_badge(f"{_format_count(stats['views'])} views"))
        if stats.get("likes"):
            meta.addWidget(_badge(f"{_format_count(stats['likes'])} likes", GOOD))
        if stats.get("comments"):
            meta.addWidget(_badge(f"{_format_count(stats['comments'])} comments"))
        meta.addStretch(1)
        lay.addLayout(meta)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.open_btn = QPushButton("Open File")
        self.open_btn.setObjectName("primary")
        self.open_btn.setEnabled(bool(entry.get("source_path")))
        self.open_btn.clicked.connect(self._open_file)
        actions.addWidget(self.open_btn)
        self.mp3_btn = QPushButton("Extract MP3")
        self.mp3_btn.setObjectName("ghost")
        self.mp3_btn.setEnabled(bool(entry.get("source_path")))
        self.mp3_btn.clicked.connect(self._extract_mp3)
        actions.addWidget(self.mp3_btn)
        tiktok_btn = QPushButton("Open in TikTok")
        tiktok_btn.setObjectName("ghost")
        tiktok_btn.clicked.connect(self._open_tiktok)
        actions.addWidget(tiktok_btn)
        copy_btn = QPushButton("Copy URL")
        copy_btn.setObjectName("ghost")
        copy_btn.clicked.connect(self._copy_url)
        actions.addWidget(copy_btn)
        lay.addLayout(actions)

    def _extract_mp3(self):
        if self._mp3_worker and self._mp3_worker.isRunning():
            return
        source = self._entry.get("source_path") or ""
        if not source or not os.path.isfile(source):
            return
        self.mp3_btn.setEnabled(False)
        self.mp3_btn.setText("Extracting…")
        out = os.path.splitext(source)[0] + ".mp3"
        self._mp3_worker = AudioExtractWorker(source, out, self)
        self._mp3_worker.done.connect(self._mp3_done)
        self._mp3_worker.start()

    def _mp3_done(self, path: str, error: str):
        self.mp3_btn.setEnabled(True)
        if path and os.path.isfile(path):
            self.mp3_btn.setText("MP3 ✓")
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            self.mp3_btn.setText("Extract failed")
            self.mp3_btn.setToolTip(error or "unknown error")

    def _open_file(self):
        path = self._entry.get("source_path") or ""
        if path and os.path.isfile(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_tiktok(self):
        video_id = self._entry.get("video_id")
        if video_id:
            QDesktopServices.openUrl(QUrl(f"https://www.tiktok.com/@x/video/{video_id}"))

    def _copy_url(self):
        from PySide6.QtWidgets import QApplication

        url = self._entry.get("url") or ""
        if url:
            QApplication.clipboard().setText(url)
