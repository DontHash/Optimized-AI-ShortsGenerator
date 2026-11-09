"""Render plan data structures shared by the CLI, Studio, and ffmpeg engine."""
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class RenderSegment:
    """One source range with a precomputed crop window."""

    start: float
    end: float
    crop: Dict[str, int]

    @property
    def duration(self) -> float:
        return max(0.0, float(self.end) - float(self.start))


@dataclass
class RenderPlan:
    """Everything the ffmpeg renderer needs for one vertical short."""

    source: str
    output: str
    segments: List[RenderSegment] = field(default_factory=list)
    width: int = 1080
    height: int = 1920
    fps: int = 30
    crf: int = 20
    encoder: str = "libx264"
    ass_path: str = ""
    fade: float = 0.5
    hdr: bool = False
    audio: bool = True
    loudness_lufs: float = -14.0
    true_peak_db: float = -1.5

    @property
    def duration(self) -> float:
        return sum(seg.duration for seg in self.segments)

    @property
    def first_start(self) -> float:
        return min((float(seg.start) for seg in self.segments), default=0.0)
