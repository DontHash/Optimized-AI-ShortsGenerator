"""Encoder discovery and argument mapping (hardware first, libx264 fallback)."""
import subprocess
from functools import lru_cache
from typing import List

_PRIORITY = ("h264_nvenc", "h264_qsv", "h264_amf", "h264_videotoolbox")
_KNOWN = set(_PRIORITY) | {"libx264"}


@lru_cache(maxsize=1)
def available_encoders() -> set:
    """Return the H.264 encoders advertised by the local ffmpeg build."""
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    text = proc.stdout or ""
    return {name for name in _PRIORITY if f" {name} " in text}


def choose_encoder(preference: str = "auto") -> str:
    """Resolve ``auto`` to the best advertised encoder, else libx264."""
    pref = (preference or "auto").strip().lower()
    if pref in _KNOWN:
        return pref
    advertised = available_encoders()
    for name in _PRIORITY:
        if name in advertised:
            return name
    return "libx264"


def video_args(encoder: str, crf: int, preset: str = "fast") -> List[str]:
    """Map a quality target to each encoder's native rate-control knobs."""
    crf = max(0, min(51, int(crf)))
    if encoder == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", str(crf), "-b:v", "0"]
    if encoder == "h264_qsv":
        return ["-c:v", "h264_qsv", "-global_quality", str(crf), "-look_ahead", "0"]
    if encoder == "h264_amf":
        return ["-c:v", "h264_amf", "-quality", "balanced",
                "-rc", "cqp", "-qp_i", str(crf), "-qp_p", str(crf)]
    if encoder == "h264_videotoolbox":
        return ["-c:v", "h264_videotoolbox", "-q:v", str(max(1, 100 - crf))]
    return ["-c:v", "libx264", "-preset", preset, "-crf", str(crf)]
