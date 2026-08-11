"""Intelligent 9:16 crop planning — keep faces in frame.

How it works:
1. Sample frames (~2/sec, downscaled) and detect the largest face per frame
   with OpenCV's bundled Haar cascade (no model download).
2. Smooth face x-centers with a rolling median so the crop doesn't jitter.
3. Quantize the smoothed x to bins; consecutive frames in the same bin become
   one constant-crop segment — a 60s short renders as a handful of segments,
   not a per-frame crop (fast + accurate).
4. No faces anywhere -> pure center crop. Portrait source -> caller skips.

Everything here is pure logic given frames; `plan_crop_from_frames` is the
only function that touches OpenCV, so tests can exercise the planning
without the dependency.
"""
import os
from typing import Dict, List, Tuple

# normalized face sample: (t_seconds, cx [0..1], cy [0..1], face_w [0..1])
FaceSample = Tuple[float, float, float, float]

# (start, end, x [0..1]) — constant crop x for a time range
CropSegment = Tuple[float, float, float]

_X_BINS = 12  # quantize face x into 1/12-wide bins
_MIN_SEGMENT_SECONDS = 1.0


def _rolling_median(values: List[float], window: int = 3) -> List[float]:
    """Median filter that preserves length (window must be odd)."""
    if not values:
        return []
    window = max(1, window | 1)
    out = []
    for i in range(len(values)):
        lo = max(0, i - window // 2)
        hi = min(len(values), i + window // 2 + 1)
        chunk = sorted(values[lo:hi])
        out.append(chunk[len(chunk) // 2])
    return out


def plan_crop_segments(
    samples: List[FaceSample],
    duration: float,
    min_segment: float = _MIN_SEGMENT_SECONDS,
) -> List[CropSegment]:
    """Turn face samples into constant-crop segments.

    Returns [(start, end, x)] with x in [0,1] (0=left, 1=right). Empty list
    when there are no faces — callers fall back to center crop.
    """
    if not samples:
        return []
    times = [s[0] for s in samples]
    cx = [s[1] for s in samples]
    cx = _rolling_median(cx, 3)

    # quantize to bins
    binned = [min(_X_BINS - 1, max(0, int(round(v * _X_BINS)))) for v in cx]

    segments: List[Tuple[float, float, float]] = []
    seg_start = times[0]
    seg_bin = binned[0]
    for i in range(1, len(samples)):
        if binned[i] != seg_bin and times[i] - seg_start >= min_segment:
            segments.append((seg_start, times[i], (seg_bin + 0.5) / _X_BINS))
            seg_start = times[i]
            seg_bin = binned[i]
    segments.append((seg_start, duration, (seg_bin + 0.5) / _X_BINS))

    # merge tiny slivers into the neighbor with the closest x
    merged: List[CropSegment] = []
    for seg in segments:
        if merged and seg[1] - seg[0] < min_segment:
            prev = merged[-1]
            if abs(prev[2] - seg[2]) < (1.0 / _X_BINS):
                merged[-1] = (prev[0], seg[1], prev[2])
                continue
        merged.append(seg)
    return merged


def compute_crop_window(
    src_w: int,
    src_h: int,
    target_w: int,
    target_h: int,
    seg_x: float,
) -> Dict[str, int]:
    """Crop window for one segment. Returns {x, y, w, h} in source pixels.

    Handles both landscape (crop horizontally) and portrait (crop vertically
    to 9:16) sources; y biases slightly above center so faces sit high.
    """
    target_ratio = target_w / target_h
    src_ratio = src_w / src_h

    if src_ratio >= target_ratio:
        # landscape/square: crop width
        h = src_h
        w = int(h * target_ratio)
        max_x = src_w - w
        x = max(0, min(int(seg_x * max_x), max_x))
        y = 0
    else:
        # portrait but not 9:16: crop height
        w = src_w
        h = int(w / target_ratio)
        max_y = src_h - h
        x = 0
        y = max(0, min(int(max_y * 0.45), max_y))  # bias up toward faces
    return {"x": x, "y": y, "w": max(2, w), "h": max(2, h)}


def sample_faces(video_path: str, sample_every: float = 0.5) -> List[FaceSample]:
    """Detect the largest face per sampled frame. Empty list if OpenCV is
    unavailable or the video can't be read. Samples at most ~400 frames."""
    try:
        import cv2
    except ImportError:
        return []

    cascade_path = os.path.join(os.path.dirname(cv2.__file__), "data",
                                "haarcascade_frontalface_default.xml")
    if not os.path.isfile(cascade_path):
        return []
    cascade = cv2.CascadeClassifier(cascade_path)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total <= 0:
        cap.release()
        return []

    step = max(1, int(round(fps * sample_every)))
    frame_idx = 0
    samples: List[FaceSample] = []
    max_frames = 400

    while frame_idx < total and len(samples) < max_frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame = cap.read()
        frame_idx += step
        if not ok or frame is None:
            break
        h, w = frame.shape[:2]
        scale = min(1.0, 480.0 / w) if w > 480 else 1.0
        small = frame if scale == 1.0 else cv2.resize(frame, (0, 0), fx=scale, fy=scale,
                                                      interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5,
                                         minSize=(max(24, gray.shape[0] // 20),)*2)
        if len(faces):
            # largest face by area
            largest = max(faces, key=lambda f: f[2] * f[3])
            fx, fy, fw, fh = largest
            sw, sh = small.shape[1], small.shape[0]
            t = frame_idx / fps
            samples.append((t, (fx + fw / 2) / sw, (fy + fh / 2) / sh, fw / sw))
    cap.release()
    return samples
