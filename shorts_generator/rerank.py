"""Signal-fusion reranker (see UPLIFT_PLAN.md).

The LLM stops being the sole judge: its score becomes one feature among replay,
audio, and chapter signals. Every present signal is rank-normalized within the
video (kills chunk-calibration drift and cross-signal scale mismatch), then
weighted-summed with a missing-signal renormalization rule.
"""
from typing import Dict, List, Optional

from . import signals as sig
from .config import (
    BOUNDARY_PAD_SECONDS,
    DEDUPE_SIMILARITY,
    MAX_CLIP_SECONDS,
    PEAK_LEAD_MAX_SECONDS,
    PEAK_LEAD_SECONDS,
    PEAK_TAIL_SECONDS,
    RERANK_WEIGHTS,
)


def rank_normalize(values: List[float]) -> List[float]:
    """Map raw values to [0,1] by average rank (ties share the mean rank)."""
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [1.0]
    order = sorted(range(n), key=lambda i: values[i])
    out = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0
        for k in range(i, j + 1):
            out[order[k]] = avg_rank / (n - 1)
        i = j + 1
    return out


def _active_weights(present: set) -> Dict[str, float]:
    active = {k: w for k, w in RERANK_WEIGHTS.items() if k in present and w > 0}
    total = sum(active.values())
    if total <= 0:
        return {"llm": 1.0}
    return {k: w / total for k, w in active.items()}


def fuse(
    highlights: List[Dict],
    heatmap: List[Dict],
    chapters: List[Dict],
    energy: Optional[Dict],
) -> List[Dict]:
    """Attach a fused 0-100 `score` and a `signals` breakdown to each highlight."""
    if not highlights:
        return highlights

    present = {"llm"}
    if heatmap:
        present.add("replay")
    if energy:
        present.add("audio")
    if chapters:
        present.add("chapter")
    weights = _active_weights(present)

    llm_raw = [float(h.get("score", 0)) for h in highlights]
    replay_raw = [sig.heatmap_mean(heatmap, float(h["start_time"]), float(h["end_time"])) for h in highlights]
    audio_raw = [sig.audio_score(energy, float(h["start_time"]), float(h["end_time"])) or 0.0 for h in highlights]
    chapter_raw = [
        sig.chapter_score(chapters, float(h["start_time"]), float(h["end_time"])) or 0.0
        for h in highlights
    ]

    norm = {
        "llm": rank_normalize(llm_raw),
        "replay": rank_normalize(replay_raw) if "replay" in present else None,
        "audio": rank_normalize(audio_raw) if "audio" in present else None,
        "chapter": rank_normalize(chapter_raw) if "chapter" in present else None,
    }

    for i, h in enumerate(highlights):
        fused = 0.0
        breakdown: Dict[str, float] = {}
        for key, w in weights.items():
            val = norm[key][i]
            fused += w * val
            breakdown[key] = round(val, 4)
        h["llm_score"] = int(h.get("score", 0))
        h["score"] = int(round(fused * 100))
        h["signals"] = {
            **breakdown,
            "replay_raw": round(replay_raw[i], 4),
            "audio_raw": round(audio_raw[i], 4),
            "final_score": round(fused * 100, 2),
            "signals_present": sorted(present),
            "weights": {k: round(v, 3) for k, v in weights.items()},
        }

    highlights.sort(key=lambda h: h["score"], reverse=True)
    return highlights


# --------------------------------------------------------------------------- #
# Context-aware peak expansion (3.7): setup -> peak -> payoff
# --------------------------------------------------------------------------- #

def _overlapping_peak(clip: Dict, heatmap: List[Dict], energy: Optional[Dict]) -> Optional[float]:
    """Start time of the strongest peak/spike inside the clip, else None."""
    start, end = float(clip["start_time"]), float(clip["end_time"])
    best_t = None
    best_v = -1.0
    for w in sig.peak_windows(heatmap, top_n=10):
        if w["start"] < end and w["end"] > start and w["value"] > best_v:
            best_v = w["value"]
            best_t = w["start"]
    if best_t is not None:
        return best_t
    if energy:
        for s in energy.get("spikes", []):
            if start <= s <= end:
                return float(s)
    return None


def expand_for_context(
    clips: List[Dict],
    segments: List[Dict],
    heatmap: List[Dict],
    energy: Optional[Dict],
) -> List[Dict]:
    """Expand peak-anchored clips backward to the setup and forward past the payoff.

    Non-peak clips are untouched (their LLM-chosen hook is already the opener).
    """
    if not segments:
        return clips

    boundaries = sorted(set(sig.pause_boundaries(segments)) | set(sig.sentence_starts(segments)))
    seg_ends = [float(s["end"]) for s in segments]
    video_end = seg_ends[-1] if seg_ends else 0.0

    for clip in clips:
        peak = _overlapping_peak(clip, heatmap, energy)
        if peak is None:
            clip["context_expanded"] = False
            continue

        start = float(clip["start_time"])
        end = float(clip["end_time"])

        # --- lead-in: at least PEAK_LEAD_SECONDS before the peak, snapped to a setup edge ---
        target = max(0.0, peak - PEAK_LEAD_SECONDS)
        floor = max(0.0, peak - PEAK_LEAD_MAX_SECONDS)
        new_start = min(start, target)

        onset = sig.tone_onset(energy, peak, floor)
        if onset is not None:
            new_start = min(new_start, max(onset, floor))

        # Snap to the nearest clean boundary at/just before new_start (within the cap)
        cands = [b for b in boundaries if floor <= b <= target + 0.5]
        if cands:
            snapped = max(b for b in cands if b <= new_start + 0.5) if any(
                b <= new_start + 0.5 for b in cands
            ) else min(cands)
            new_start = snapped
        new_start = max(floor, min(new_start, target))
        new_start = max(0.0, new_start - BOUNDARY_PAD_SECONDS)

        # --- tail: extend past the payoff, snap forward to a sentence end ---
        target_end = end + PEAK_TAIL_SECONDS
        new_end = target_end
        for e in seg_ends:
            if e >= target_end - 0.05:
                new_end = e
                break
        new_end = min(new_end + BOUNDARY_PAD_SECONDS, video_end + BOUNDARY_PAD_SECONDS)

        # --- duration guard: trim the tail first, never the lead-in ---
        if new_end - new_start > MAX_CLIP_SECONDS:
            new_end = new_start + MAX_CLIP_SECONDS

        clip["start_time"] = new_start
        clip["end_time"] = max(new_end, new_start + 1.0)
        clip["context_expanded"] = True

    return clips


# --------------------------------------------------------------------------- #
# Transcript-similarity dedupe (3.5)
# --------------------------------------------------------------------------- #

def dedupe_semantic(clips: List[Dict], threshold: float = DEDUPE_SIMILARITY) -> List[Dict]:
    """Drop the lower-scoring of any two clips whose excerpts are near-identical."""
    ranked = sorted(clips, key=lambda c: c.get("score", 0), reverse=True)
    kept: List[Dict] = []
    kept_words: List[set] = []
    for c in ranked:
        words = sig.content_words(c.get("transcript_excerpt", ""))
        if any(sig.jaccard(words, kw) > threshold for kw in kept_words):
            continue
        kept.append(c)
        kept_words.append(words)
    return kept
