"""ffmpeg clip cutting + vertical 9:16 shorts rendering.

Shorts use face-aware intelligent cropping (see smartcrop.py): the crop window
follows the speaker so the subject stays in frame, with optional caption burn,
fades, and loudness normalization.
"""
import json
import os
import re
import subprocess
import tempfile
import threading
from dataclasses import replace
from typing import Callable, Dict, List, Optional, Tuple

from .captions import build_ass, burn_subtitles, has_audio
from .config import (
    SHORTS_CAPTIONS,
    SHORTS_CRF,
    SHORTS_ENCODER,
    SHORTS_FACE_CROP,
    SHORTS_FADE_SECONDS,
    SHORTS_FPS,
    SHORTS_HEIGHT,
    SHORTS_MAX_UPSCALE,
    SHORTS_WIDTH,
)
from .render import (
    RenderCancelled,
    RenderError,
    RenderPlan,
    RenderSegment,
    render_plan,
)

# HDR input needs tonemapping before yuv420p 8-bit encoding, otherwise the
# naive conversion turns the picture gray/muddy. These transfer tags mark PEQ/HLG.
_HDR_TRANSFERS = frozenset({"smpte2084", "arib-std-b67", "bt2020-10", "bt2020-12", "linear"})

# Standard 9:16 output widths; pick the largest that stays within the upscale cap.
_STANDARD_WIDTHS = (1080, 720, 540, 480, 360)


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "clip").lower()).strip("-")
    return (slug or "clip")[:60]


def _run(cmd: List[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def probe_video(source_path: str) -> Optional[Dict]:
    """Return {width, height, fps, duration, color_transfer} via ffprobe. None on any failure."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,avg_frame_rate,color_transfer:format=duration",
        "-of", "json",
        source_path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
        stream = (data.get("streams") or [{}])[0]
        dur_raw = (data.get("format") or {}).get("duration")
        fps_raw = str(stream.get("avg_frame_rate", "0/0"))
        num, _, den = fps_raw.partition("/")
        fps = float(num) / float(den) if den and float(den) else None
        return {
            "width": int(stream.get("width") or 0),
            "height": int(stream.get("height") or 0),
            "fps": fps,
            "duration": float(dur_raw) if dur_raw else 0.0,
            "color_transfer": str(stream.get("color_transfer") or "").strip(),
        }
    except (ValueError, TypeError):
        return None


def cut_subclip(
    source_path: str,
    start: float,
    end: float,
    out_path: str,
    accurate: bool = False,
) -> str:
    """Cut [start, end]. Default -c copy (fast); accurate=True re-encodes."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    duration = max(0.1, end - start)
    if accurate:
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", f"{start:.3f}",
            "-i", source_path,
            "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k",
            out_path,
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", f"{start:.3f}",
            "-i", source_path,
            "-t", f"{duration:.3f}",
            "-c", "copy",
            out_path,
        ]
    subprocess.run(cmd, check=True)
    return out_path


def render_clips(
    source_path: str,
    clips: List[Dict],
    out_dir: str,
    accurate: bool = False,
) -> List[Dict]:
    """Write original-ratio mp4s named `<rank>_<name>.mp4`. Mutates clip dicts with clip_path."""
    os.makedirs(out_dir, exist_ok=True)
    results: List[Dict] = []
    for clip in clips:
        rank = int(clip.get("rank", 0))
        name = clip.get("name") or _slugify(str(clip.get("title", "clip")))
        out_path = os.path.join(out_dir, f"{rank}_{name}.mp4")
        print(f"[render] {rank}: {clip.get('title', '(untitled)')}", flush=True)
        try:
            cut_subclip(
                source_path,
                float(clip["start_time"]),
                float(clip["end_time"]),
                out_path,
                accurate=accurate,
            )
            results.append({**clip, "clip_path": out_path})
        except Exception as e:  # noqa: BLE001
            print(f"[render] {rank} failed: {e}", flush=True)
            results.append({**clip, "clip_path": None, "error": str(e)})
    return results


# --------------------------------------------------------------------------- #
# Shorts rendering (9:16, face-aware)
# --------------------------------------------------------------------------- #

def _short_output_size(crop_w: int, crop_h: int) -> Tuple[int, int]:
    """Pick output size so we never upscale beyond SHORTS_MAX_UPSCALE× detail.

    A 360p source cropped to 9:16 leaves ~200px of real detail; blowing it to
    1080px is a 5× upscale (mushy). Cap at 3× and snap to a standard width.
    """
    target = min(SHORTS_WIDTH, int(round(crop_w * SHORTS_MAX_UPSCALE)))
    for w in _STANDARD_WIDTHS:
        if w <= target:
            h = int(round(w * SHORTS_HEIGHT / SHORTS_WIDTH / 2)) * 2
            return w, h
    return 360, 640


def _normalize_crop_segments(
    segments: List[Tuple[float, float, float]], duration: float
) -> List[Tuple[float, float, float]]:
    """Guarantee segments tile [0, duration] end-to-end (no intro cut, no tail drop).

    Face-tracking plans only describe ranges where a face was sampled. The
    renderer must still cover the intro before the first sample and any gaps
    between segments; otherwise the short silently loses seconds (and its
    captions/audio drift). Gaps are filled with the previous crop window and
    the tail is clamped to the clip duration.
    """
    duration = max(0.0, float(duration))
    if duration <= 0.0:
        return []

    cleaned: List[Tuple[float, float, float]] = []
    for s_start, s_end, s_x in sorted(segments, key=lambda s: float(s[0])):
        a = max(0.0, min(float(s_start), duration))
        b = max(a, min(float(s_end), duration))
        if b - a > 1e-6:
            cleaned.append((a, b, float(s_x)))
    if not cleaned:
        return [(0.0, duration, 0.5)]

    out: List[Tuple[float, float, float]] = []
    cursor = 0.0
    for a, b, x in cleaned:
        if b <= cursor + 1e-6:
            continue
        if a > cursor + 1e-6:
            # Fill the gap (including the intro before the first face sample)
            # with the previous/next crop window so no content is dropped.
            fill_x = out[-1][2] if out else x
            out.append((cursor, a, fill_x))
            cursor = a
        a = max(a, cursor)
        if b > a + 1e-6:
            out.append((a, b, x))
            cursor = b
        if cursor >= duration:
            break

    if not out:
        return [(0.0, duration, 0.5)]
    if cursor < duration - 1e-6:
        out.append((cursor, duration, out[-1][2]))

    # Merge contiguous segments that use the same crop window.
    merged: List[Tuple[float, float, float]] = []
    for seg in out:
        if merged and abs(merged[-1][1] - seg[0]) < 1e-6 and abs(merged[-1][2] - seg[2]) < 1e-9:
            merged[-1] = (merged[-1][0], seg[1], merged[-1][2])
        else:
            merged.append(seg)
    return merged


def _srt_timestamp(seconds: float) -> str:
    ms = max(0, int(round(seconds * 1000)))
    return f"{ms // 3600000:02d}:{(ms // 60000) % 60:02d}:{(ms // 1000) % 60:02d},{ms % 1000:03d}"


def chunk_words_to_cues(
    words: List[Dict],
    max_words: int = 5,
    max_span: float = 2.8,
    lead: float = 0.15,
    tail: float = 0.4,
) -> List[Dict]:
    """Group word timestamps into short caption cues that appear on time.

    Whisper's sentence-level segments can span 30s (or worse: whole verses),
    which makes burned captions feel late. Chunking by word count / span keeps
    each caption short and synced to the speech. Returns [{start, end, text}].

    Accepts both word-level ``{"word"}`` and sentence ``{"text"}`` entries so
    older caches and callers keep working.
    """
    clean = []
    for w in sorted(words, key=lambda item: float(item.get("start", 0.0))):
        text = str(w.get("word") or w.get("text") or "").strip()
        if not text or text in {",", ".", "?", "!", ";", ":", "..", "..."}:
            continue
        try:
            start = float(w["start"])
            end = float(w["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end <= start:
            end = start + 0.05
        clean.append({"start": start, "end": end, "text": text})
    if not clean:
        return []

    cues: List[Dict] = []
    cur: List[Dict] = []
    for w in clean:
        if not cur:
            cur = [w]
            continue
        span = w["end"] - cur[0]["start"]
        if len(cur) >= max_words or span > max_span:
            cues.append(_cue_from(cur, lead, tail))
            cur = [w]
        else:
            cur.append(w)
    if cur:
        cues.append(_cue_from(cur, lead, tail))

    # Lead/tail padding can make adjacent cues overlap (libass then stacks
    # both). Clamp each cue to the next cue's start.
    for i in range(len(cues) - 1):
        cues[i]["end"] = min(cues[i]["end"], max(cues[i]["start"] + 0.05, cues[i + 1]["start"]))
    return cues


def _cue_from(words: List[Dict], lead: float, tail: float) -> Dict:
    text = " ".join(w["text"] for w in words)
    start = max(0.0, words[0]["start"] - lead)
    end = words[-1]["end"] + tail
    return {"start": start, "end": end, "text": text}


def build_clip_srt(segments: List[Dict], clip_start: float, clip_end: float, out_path: str) -> str:
    """SRT for the clip window from transcript segments (rebase to clip-relative time)."""
    clip_dur = max(0.1, clip_end - clip_start)
    lines: List[str] = []
    idx = 1
    for s in segments:
        start = max(0.0, float(s["start"]) - clip_start)
        end = min(float(s["end"]) - clip_start, clip_dur)
        if end <= 0 or start >= clip_dur:
            continue
        text = str(s.get("text", "")).strip()
        if not text:
            continue
        lines.append(str(idx))
        lines.append(f"{_srt_timestamp(start)} --> {_srt_timestamp(end)}")
        lines.append(text)
        lines.append("")
        idx += 1
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out_path


def burn_srt_captions(video_path: str, srt_path: str, out_path: str) -> str:
    """Deprecated SRT entry point: convert to a safe 9:16 ASS and burn it."""
    from .transcriber import load_srt_file

    subs = load_srt_file(srt_path)
    if not subs.get("segments"):
        raise RuntimeError(f"no cues in {srt_path}")
    ass_path = os.path.splitext(out_path)[0] + ".ass"
    build_ass(subs["segments"], ass_path, clip_start=0.0)
    return burn_subtitles(video_path, ass_path, out_path)


def render_shorts(
    source_path: str,
    clip: Dict,
    out_dir: str,
    transcript_segments: Optional[List[Dict]] = None,
    progress_cb: Optional[Callable[[float], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Dict:
    """Render one clip as a 9:16 short with face-aware crop + optional captions.

    The whole short is produced by one ffmpeg filter graph and one encode
    (see ``shorts_generator.render``). Returns the clip dict plus
    short_path / thumb_path / error.
    """
    rank = int(clip.get("rank", 0))
    name = clip.get("name") or _slugify(str(clip.get("title", "clip")))
    os.makedirs(out_dir, exist_ok=True)

    result = dict(clip)
    base = os.path.join(out_dir, f"{rank}_{name}_short")
    try:
        info = probe_video(source_path) or {}
        src_w = int(info.get("width") or 1280)
        src_h = int(info.get("height") or 720)
        src_duration = float(info.get("duration") or 0.0)

        # Clamp to the real media length. Upstream boundary snapping can push
        # an end past EOF; rendering that silently truncates video/audio.
        start = max(0.0, float(clip["start_time"]))
        end = float(clip["end_time"])
        if src_duration > 0:
            start = min(start, max(0.0, src_duration - 0.5))
            end = min(end, src_duration)
        duration = end - start
        if duration < 0.5:
            raise RuntimeError(
                f"clip is shorter than 0.5s after clamping to the source "
                f"({start:.2f}s–{end:.2f}s of {src_duration:.2f}s)"
            )

        target_ratio = SHORTS_WIDTH / SHORTS_HEIGHT
        src_ratio = src_w / src_h

        # Plan crop segments. sample_faces returns absolute source times;
        # origin=start rebases them to clip-relative time exactly once.
        crop_segments: List[Tuple[float, float, float]] = []
        if SHORTS_FACE_CROP and src_ratio >= target_ratio:
            try:
                from . import smartcrop as sc

                samples = sc.sample_faces(source_path, start=start, end=end)
                if samples:
                    crop_segments = sc.plan_crop_segments(samples, duration, origin=start)
            except Exception:  # noqa: BLE001 — face crop must never kill a render
                crop_segments = []
        crop_segments = _normalize_crop_segments(crop_segments, duration)

        from .smartcrop import compute_crop_window

        render_segments: List[RenderSegment] = []
        for seg_start, seg_end, seg_x in crop_segments:
            crop = compute_crop_window(src_w, src_h, SHORTS_WIDTH, SHORTS_HEIGHT, seg_x)
            render_segments.append(RenderSegment(
                start=start + seg_start,
                end=start + seg_end,
                crop=crop,
            ))

        first_crop = render_segments[0].crop
        out_w, out_h = _short_output_size(first_crop["w"], first_crop["h"])
        hdr = (info.get("color_transfer") or "") in _HDR_TRANSFERS
        if hdr:
            print("[shorts] HDR source detected — tonemapping to SDR", flush=True)

        ass_path = ""
        output = f"{base}.mp4"
        if SHORTS_CAPTIONS and transcript_segments:
            ass_path = os.path.join(out_dir, f"{rank}_{name}_short.ass")
            build_ass(
                transcript_segments,
                ass_path,
                clip_start=start,
                clip_end=duration,
            )
            output = f"{base}_captioned.mp4"

        plan = RenderPlan(
            source=source_path,
            output=output,
            segments=render_segments,
            width=out_w,
            height=out_h,
            fps=SHORTS_FPS,
            crf=SHORTS_CRF,
            encoder=SHORTS_ENCODER,
            ass_path=ass_path,
            fade=SHORTS_FADE_SECONDS,
            hdr=hdr,
            audio=has_audio(source_path),
        )
        try:
            render_plan(plan, progress_cb=progress_cb, cancel_event=cancel_event)
        except RenderError as e:
            # A caption/libass failure should still yield a usable raw short.
            if ass_path and any(
                token in str(e).lower()
                for token in ("ass", "subtitle", "font", "libass", "filter")
            ):
                print(f"[shorts] caption burn failed ({e}); rendering without captions", flush=True)
                plan = replace(plan, ass_path="", output=f"{base}.mp4")
                render_plan(plan, progress_cb=progress_cb, cancel_event=cancel_event)
            else:
                raise

        short_path = plan.output
        result["short_path"] = short_path
        if ass_path and os.path.isfile(ass_path):
            result["ass_path"] = ass_path

        # Thumbnail from the *rendered* short (cropped, captioned, vertical).
        thumb = f"{base}.jpg"
        try:
            thumb_at = min(max(0.5, duration * 0.1), max(0.5, duration - 0.2))
            _run(["ffmpeg", "-y", "-loglevel", "error",
                  "-ss", f"{thumb_at:.3f}", "-i", short_path,
                  "-frames:v", "1", "-q:v", "3", thumb])
            result["thumb_path"] = thumb
        except Exception:  # noqa: BLE001
            result["thumb_path"] = None
        print(f"[shorts] rendered {rank} → {short_path}", flush=True)
    except RenderCancelled:
        result["short_path"] = None
        result["error"] = "cancelled"
        print(f"[shorts] {rank} cancelled", flush=True)
    except Exception as e:  # noqa: BLE001
        result["short_path"] = None
        result["error"] = str(e)
        print(f"[shorts] {rank} failed: {e}", flush=True)
    return result


def render_all_shorts(
    source_path: str,
    clips: List[Dict],
    out_dir: str,
    transcript_segments: Optional[List[Dict]] = None,
    progress_cb: Optional[Callable[[float], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> List[Dict]:
    """Render every clip as a 9:16 short (batch), with overall progress."""
    results: List[Dict] = []
    total = max(1, len(clips))
    for i, clip in enumerate(clips):
        if cancel_event is not None and cancel_event.is_set():
            results.append({**clip, "short_path": None, "error": "cancelled"})
            continue

        def _clip_progress(fraction: float, _i: int = i) -> None:
            if progress_cb:
                progress_cb(max(0.0, min(1.0, (_i + fraction) / total)))

        results.append(render_shorts(
            source_path, clip, out_dir, transcript_segments,
            progress_cb=_clip_progress,
            cancel_event=cancel_event,
        ))
    return results


def extract_audio(source_path: str, out_path: str) -> str:
    """Extract audio as MP3."""
    _run(["ffmpeg", "-y", "-loglevel", "error",
          "-i", source_path, "-vn", "-c:a", "libmp3lame", "-q:a", "2", out_path])
    return out_path


def compile_shorts(
    clip_paths: List[str],
    out_path: str,
    music_path: Optional[str] = None,
    music_volume: float = 0.25,
) -> str:
    """Stitch clip MP4s into one video, optionally mixing a background track."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for p in clip_paths:
            # absolute paths: concat resolves entries relative to the LIST file
            escaped = os.path.abspath(p).replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")
        list_path = f.name
    try:
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
               "-i", list_path]
        if music_path and os.path.isfile(music_path):
            cmd += ["-stream_loop", "-1", "-i", music_path,
                    "-filter_complex",
                    f"[0:a]volume=1.0[voice];[1:a]volume={music_volume}[music];"
                    f"[voice][music]amix=inputs=2:duration=first:dropout_transition=2:normalize=0,"
                    f"alimiter=limit=0.95[aout]",
                    "-map", "0:v", "-map", "[aout]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-shortest", "-movflags", "+faststart"]
        else:
            cmd += ["-c", "copy"]
        cmd.append(out_path)
        _run(cmd)
    finally:
        os.unlink(list_path)
    return out_path
