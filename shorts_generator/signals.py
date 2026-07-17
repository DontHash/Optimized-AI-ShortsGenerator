"""Measurable ranking signals fused on top of the LLM (see UPLIFT_PLAN.md).

Everything here is CPU-only and uses deps we already ship (yt-dlp for the
YouTube "Most Replayed" heatmap + chapters, ffmpeg + numpy for audio energy).
Every function degrades gracefully: absent data returns None/empty, never raises.
"""
import json
import os
import re
import subprocess
from typing import Dict, List, Optional, Tuple

_WORD_RE = re.compile(r"[a-z0-9']+")
_STOPWORDS = frozenset(
    "the a an and or but so if of to in on at for with from as is are was were be been "
    "being it its this that these those i you he she we they them his her their our your "
    "me my mine not no yes do does did done have has had will would can could should just "
    "about into over than then there here what which who whom how when where why".split()
)


def hms(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def content_words(text: str) -> set:
    return {w for w in _WORD_RE.findall((text or "").lower()) if w not in _STOPWORDS and len(w) > 2}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


# --------------------------------------------------------------------------- #
# Replay heatmap (YouTube "Most Replayed")
# --------------------------------------------------------------------------- #

def normalize_heatmap(heatmap: object) -> List[Dict]:
    """Coerce yt-dlp heatmap into a clean sorted list of {start,end,value}."""
    if not isinstance(heatmap, list):
        return []
    points = []
    for p in heatmap:
        if not isinstance(p, dict):
            continue
        try:
            start = float(p["start_time"])
            end = float(p["end_time"])
            value = float(p["value"])
        except (KeyError, TypeError, ValueError):
            continue
        if end > start:
            points.append({"start": start, "end": end, "value": value})
    points.sort(key=lambda x: x["start"])
    return points


def heatmap_mean(heatmap: List[Dict], start: float, end: float) -> float:
    """Duration-weighted mean replay value over [start, end]. 0.0 if no data."""
    if not heatmap or end <= start:
        return 0.0
    total_w = 0.0
    acc = 0.0
    for p in heatmap:
        lo = max(start, p["start"])
        hi = min(end, p["end"])
        overlap = hi - lo
        if overlap > 0:
            acc += p["value"] * overlap
            total_w += overlap
    return acc / total_w if total_w else 0.0


def peak_windows(heatmap: List[Dict], top_n: int = 5, rel_threshold: float = 0.6) -> List[Dict]:
    """Merge high-replay points into peak windows, strongest first."""
    if not heatmap:
        return []
    max_v = max(p["value"] for p in heatmap)
    if max_v <= 0:
        return []
    cutoff = rel_threshold * max_v
    windows: List[Dict] = []
    cur: Optional[Dict] = None
    for p in heatmap:
        if p["value"] >= cutoff:
            if cur and p["start"] <= cur["end"] + 1e-6:
                cur["end"] = p["end"]
                cur["value"] = max(cur["value"], p["value"])
            else:
                if cur:
                    windows.append(cur)
                cur = {"start": p["start"], "end": p["end"], "value": p["value"]}
    if cur:
        windows.append(cur)
    windows.sort(key=lambda w: w["value"], reverse=True)
    return windows[:top_n]


def sparkline(heatmap: List[Dict], width: int = 40) -> str:
    if not heatmap:
        return ""
    bars = "▁▂▃▄▅▆▇█"
    duration = heatmap[-1]["end"]
    if duration <= 0:
        return ""
    buckets = []
    for i in range(width):
        lo = duration * i / width
        hi = duration * (i + 1) / width
        buckets.append(heatmap_mean(heatmap, lo, hi))
    mx = max(buckets) or 1.0
    return "".join(bars[min(len(bars) - 1, int(v / mx * (len(bars) - 1)))] for v in buckets)


def write_heatmap_json(video_dir: str, heatmap: List[Dict]) -> Optional[str]:
    if not heatmap:
        return None
    path = os.path.join(video_dir, "heatmap.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(heatmap, f, indent=2)
    return path


# --------------------------------------------------------------------------- #
# Chapters
# --------------------------------------------------------------------------- #

_CHAPTER_INTEREST = re.compile(
    r"mistake|truth|secret|why|how i|nobody|wrong|confession|fight|exposed|reveal|"
    r"worst|best|shock|crazy|insane|never|fail|regret|lesson|story|moment",
    re.IGNORECASE,
)


def normalize_chapters(chapters: object) -> List[Dict]:
    if not isinstance(chapters, list):
        return []
    out = []
    for c in chapters:
        if not isinstance(c, dict):
            continue
        try:
            start = float(c.get("start_time"))
        except (TypeError, ValueError):
            continue
        end = c.get("end_time")
        out.append(
            {
                "start": start,
                "end": float(end) if end is not None else None,
                "title": str(c.get("title") or "").strip(),
            }
        )
    out.sort(key=lambda x: x["start"])
    return out


def chapter_score(chapters: List[Dict], start: float, end: float) -> Optional[float]:
    """1.0 if the overlapping chapter title looks clip-worthy, else 0.5. None if no chapters."""
    if not chapters:
        return None
    mid = (start + end) / 2.0
    title = ""
    for c in chapters:
        c_end = c["end"] if c["end"] is not None else float("inf")
        if c["start"] <= mid < c_end:
            title = c["title"]
            break
    return 1.0 if title and _CHAPTER_INTEREST.search(title) else 0.5


# --------------------------------------------------------------------------- #
# Audio energy (ffmpeg -> numpy RMS per second)
# --------------------------------------------------------------------------- #

def compute_audio_energy(
    source_path: str,
    cache_path: Optional[str] = None,
    sr: int = 16000,
) -> Optional[Dict]:
    """Per-second normalized RMS + spike/pause markers. None if ffmpeg/numpy unavailable."""
    if cache_path and os.path.isfile(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass

    try:
        import numpy as np
    except ImportError:
        return None

    cmd = [
        "ffmpeg", "-i", source_path,
        "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-loglevel", "error", "-",
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except (OSError, FileNotFoundError):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None

    audio = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    n = len(audio) // sr
    if n < 2:
        return None
    frames = audio[: n * sr].reshape(n, sr)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    mx = float(rms.max()) or 1.0
    norm = rms / mx

    mean = float(norm.mean())
    std = float(norm.std()) or 1e-6
    spike_thr = mean + 2.0 * std
    spikes = [i for i in range(n) if norm[i] >= spike_thr]
    pause_thr = max(0.04, mean * 0.4)
    pauses = [i for i in range(n) if norm[i] <= pause_thr]

    energy = {
        "window_seconds": 1.0,
        "values": [round(float(v), 4) for v in norm],
        "mean": round(mean, 4),
        "std": round(std, 4),
        "spikes": spikes,
        "pauses": pauses,
    }
    if cache_path:
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(energy, f)
        except OSError:
            pass
    return energy


def audio_score(energy: Optional[Dict], start: float, end: float) -> Optional[float]:
    """Mean energy over the window + a bonus for spikes inside it. None if no energy."""
    if not energy:
        return None
    values = energy.get("values") or []
    if not values:
        return None
    lo = max(0, int(start))
    hi = min(len(values), int(end) + 1)
    if hi <= lo:
        return 0.0
    window = values[lo:hi]
    base = sum(window) / len(window)
    spikes_in = sum(1 for s in energy.get("spikes", []) if lo <= s < hi)
    bonus = min(0.3, 0.1 * spikes_in)
    return min(1.0, 0.7 * base + bonus + (0.3 if spikes_in else 0.0) * base)


def tone_onset(energy: Optional[Dict], peak_time: float, floor_time: float) -> Optional[float]:
    """Walk back from a peak to where energy first rose above baseline — the setup start."""
    if not energy:
        return None
    values = energy.get("values") or []
    if not values:
        return None
    mean = energy.get("mean", 0.0)
    idx = min(len(values) - 1, int(peak_time))
    floor_idx = max(0, int(floor_time))
    onset = idx
    while onset > floor_idx and values[onset] > mean:
        onset -= 1
    return float(onset)


# --------------------------------------------------------------------------- #
# Candidate boundaries (pause + topic shift)
# --------------------------------------------------------------------------- #

def pause_boundaries(segments: List[Dict], min_gap: float = 1.0) -> List[float]:
    times = []
    for i in range(len(segments) - 1):
        gap = float(segments[i + 1]["start"]) - float(segments[i]["end"])
        if gap >= min_gap:
            times.append(float(segments[i + 1]["start"]))
    return times


def sentence_starts(segments: List[Dict]) -> List[float]:
    return [float(s["start"]) for s in segments]


def topic_boundaries(segments: List[Dict], block: float = 30.0) -> List[float]:
    """Local minima of adjacent-block word overlap = topic shifts. Pure Python."""
    if not segments:
        return []
    duration = float(segments[-1]["end"])
    n_blocks = max(1, int(duration // block) + 1)
    block_words: List[set] = [set() for _ in range(n_blocks)]
    for s in segments:
        bi = min(n_blocks - 1, int(float(s["start"]) // block))
        block_words[bi] |= content_words(s.get("text", ""))
    sims = []
    for i in range(len(block_words) - 1):
        sims.append(jaccard(block_words[i], block_words[i + 1]))
    boundaries = []
    for i in range(1, len(sims) - 1):
        if sims[i] < sims[i - 1] and sims[i] < sims[i + 1]:
            boundaries.append((i + 1) * block)
    return boundaries


def candidate_boundaries(
    segments: List[Dict],
    heatmap: List[Dict],
    energy: Optional[Dict],
) -> List[float]:
    pts = set(pause_boundaries(segments))
    pts.update(topic_boundaries(segments))
    for w in peak_windows(heatmap, top_n=8):
        pts.add(w["start"])
    if energy:
        for s in energy.get("spikes", []):
            pts.add(float(s))
    return sorted(pts)


# --------------------------------------------------------------------------- #
# LLM hint block
# --------------------------------------------------------------------------- #

def build_hints(
    heatmap: List[Dict],
    chapters: List[Dict],
    boundaries: List[float],
    energy: Optional[Dict],
    max_items: int = 6,
) -> str:
    lines: List[str] = []

    peaks = peak_windows(heatmap, top_n=max_items)
    if peaks:
        spans = ", ".join(f"{hms(p['start'])}-{hms(p['end'])}" for p in peaks)
        lines.append(
            "Audience replay peaks (YouTube Most Replayed) — moments overlapping these "
            f"are proven rewatch-worthy, look closely here: {spans}"
        )

    if chapters:
        chap = " | ".join(f"{hms(c['start'])} {c['title']}" for c in chapters[:max_items] if c["title"])
        if chap:
            lines.append(f"Creator chapters (editorial table of contents): {chap}")

    if energy and energy.get("spikes"):
        spikes = ", ".join(hms(float(s)) for s in energy["spikes"][:max_items])
        lines.append(f"Loud/emotional audio moments (laughter, shouting, applause): {spikes}")

    if boundaries:
        bounds = ", ".join(hms(b) for b in boundaries[:max_items])
        lines.append(
            f"Natural clip boundaries (pauses / topic shifts) — start and end clips near these, "
            f"never mid-thought: {bounds}"
        )

    if not lines:
        return ""
    return "Signal hints (use as guidance, not gospel):\n" + "\n".join(f"- {l}" for l in lines)
