"""Embedded video preview panel (Qt Multimedia)."""
from PySide6.QtCore import Qt, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class PreviewPanel(QWidget):
    """Plays a local video file, optionally seeking to a timestamp."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)

        self.video = QVideoWidget()
        self.video.setMinimumSize(360, 420)
        self.player.setVideoOutput(self.video)
        lay.addWidget(self.video, 1)

        self.file_label = QLabel("No video loaded — use Preview on a clip card")
        self.file_label.setObjectName("dim")
        lay.addWidget(self.file_label)

        controls = QHBoxLayout()
        self.play_btn = QPushButton("Play")
        self.play_btn.setObjectName("primary")
        self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self._toggle_play)
        controls.addWidget(self.play_btn)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setEnabled(False)
        self.slider.sliderMoved.connect(self.player.setPosition)
        controls.addWidget(self.slider, 1)

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setObjectName("dim")
        controls.addWidget(self.time_label)
        lay.addLayout(controls)

        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.mediaStatusChanged.connect(self._on_status)

    # -- public ---------------------------------------------------------- #
    def play_file(self, path: str, seek_seconds: float = 0.0):
        self.file_label.setText(path)
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.setPosition(int(seek_seconds * 1000))
        self.play_btn.setEnabled(True)
        self.slider.setEnabled(True)
        self.player.play()

    # -- internals ------------------------------------------------------- #
    def _toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _on_position(self, pos: int):
        self.slider.blockSignals(True)
        self.slider.setValue(pos)
        self.slider.blockSignals(False)
        self.time_label.setText(f"{_fmt(pos)} / {_fmt(self.player.duration())}")

    def _on_duration(self, dur: int):
        self.slider.setRange(0, max(1, dur))

    def _on_state(self, state):
        self.play_btn.setText("Pause" if state == QMediaPlayer.PlaybackState.PlayingState else "Play")

    def _on_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.play_btn.setText("Play")


def _fmt(ms: int) -> str:
    s = max(0, ms // 1000)
    return f"{s // 60:02d}:{s % 60:02d}"
