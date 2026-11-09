"""Home hub — hero header + tool cards that launch each module."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from . import icons
from .theme import ACCENT, GOOD, TEXT_FAINT

TOOL_CARDS = [
    {
        "id": "shorts",
        "icon": "shorts",
        "title": "YouTube Shorts Creator",
        "blurb": "Paste YouTube URLs, rank viral moments with AI, and render 9:16 "
                 "shorts with face-aware cropping and burned captions.",
        "cta": "Open Shorts Creator",
        "new": False,
    },
    {
        "id": "tiktok",
        "icon": "tiktok",
        "title": "TikTok Downloader",
        "blurb": "Watermark-free TikTok downloads with title, author, and stats. "
                 "A paced queue keeps you safely under rate limits.",
        "cta": "Open TikTok Downloader",
        "new": False,
    },
    {
        "id": "swap",
        "icon": "swap",
        "title": "Face Swap",
        "blurb": "Swap a face in any single-person video using one reference photo. "
                 "Runs entirely on your machine with ONNX — nothing is uploaded.",
        "cta": "Open Face Swap",
        "new": True,
    },
]


class ToolCard(QFrame):
    """Clickable hub card: icon tile, title, blurb, CTA + optional NEW badge."""

    clicked = Signal(str)  # tool id

    def __init__(self, spec: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("toolCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._id = spec["id"]
        self.setMinimumSize(300, 210)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)

        top = QHBoxLayout()
        tile = QLabel()
        tile.setFixedSize(46, 46)
        tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tile.setPixmap(icons.icon(spec["icon"], ACCENT, 26).pixmap(26, 26))
        tile.setObjectName("cardIcon")
        top.addWidget(tile)
        if spec.get("new"):
            badge = QLabel("NEW")
            badge.setObjectName("cardNew")
            badge.setStyleSheet(
                f"color:{GOOD}; font-weight:700; font-size:10px; padding:3px 8px;"
            )
            top.addWidget(badge)
        top.addStretch(1)
        lay.addLayout(top)

        title = QLabel(spec["title"])
        title.setObjectName("cardTitle")
        lay.addWidget(title)

        blurb = QLabel(spec["blurb"])
        blurb.setObjectName("cardBlurb")
        blurb.setWordWrap(True)
        blurb.setMinimumHeight(60)
        lay.addWidget(blurb)
        lay.addStretch(1)

        cta = QLabel(spec["cta"] + "  →")
        cta.setObjectName("cardCta")
        lay.addWidget(cta)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._id)
        super().mousePressEvent(event)


class HomePage(QWidget):
    """Landing page with the tool hub."""

    tool_launch = Signal(str)  # tool id -> MainWindow navigates

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 24)
        lay.setSpacing(20)

        hero = QVBoxLayout()
        hero.setSpacing(6)
        title = QLabel("Welcome to ClipClipper Studio")
        title.setObjectName("h1")
        title.setStyleSheet("font-size:24px;")
        hero.addWidget(title)
        sub = QLabel(
            "Find viral moments, produce vertical shorts, and swap faces — "
            "all local, no uploads, no monthly fees."
        )
        sub.setObjectName("dim")
        sub.setStyleSheet("font-size:14px;")
        hero.addWidget(sub)
        lay.addLayout(hero)

        grid = QHBoxLayout()
        grid.setSpacing(16)
        for spec in TOOL_CARDS:
            card = ToolCard(spec)
            card.clicked.connect(self.tool_launch.emit)
            grid.addWidget(card, 1)
        lay.addLayout(grid)
        lay.addStretch(1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        version = QLabel("ClipClipper Studio · local-first · MIT")
        version.setStyleSheet(f"color:{TEXT_FAINT}; font-size:11px;")
        footer.addWidget(version)
        lay.addLayout(footer)
