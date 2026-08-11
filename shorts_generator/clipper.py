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
from typing import Dict, List, Optional, Tuple

from .config import (
    SHORTS_CAPTIONS,
    SHORTS_CRF,
    SHORTS_FACE_CROP,
    SHORTS_FADE_SECONDS,
    SHORTS_FPS,
    SHORTS_HEIGHT,
    SHORTS_WIDTH,
)


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "clip").lower()).strip("-")
    return (slug or "clip")[:60]


def _run(cmd: List[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def probe_video(source_path: str) -> Optional[Dict]:
    """Return {width, height, fps, duration} via ffprobe. None on any failure."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,avg_frame_rate:format=duration",
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

def _encode_segment(
    source: str, start: float, duration: float, crop: Dict[str, int],
    out_path: str, fade: float, is_last: bool,
) -> None:
    vf = (
        f"crop={crop['w']}:{crop['h']}:{crop['x']}:{crop['y']},"
        f"scale={SHORTS_WIDTH}:{SHORTS_HEIGHT}:flags=lanczos,"
        f"fps={SHORTS_FPS},format=yuv420p"
    )
    if fade > 0:
        vf += f",fade=t=in:st=0:d={fade}"
        if is_last:
            vf += f",fade=t=out:st={max(0.1, duration - fade)}:d={fade}"
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
        "-i", source,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", str(SHORTS_CRF),
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
        out_path,
    ]
    _run(cmd)


def _concat(parts: List[str], out_path: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for p in parts:
            # absolute paths: the concat demuxer resolves entries relative to the LIST file
            escaped = os.path.abspath(p).replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")
        list_path = f.name
    try:
        _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
              "-i", list_path, "-c", "copy", out_path])
    finally:
        os.unlink(list_path)


def _srt_timestamp(seconds: float) -> str:
    ms = max(0, int(round(seconds * 1000)))
    return f"{ms // 3600000:02d}:{(ms // 60000) % 60:02d}:{(ms // 1000) % 60:02d},{ms % 1000:03d}"


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
    """Burn an SRT onto a video with shorts-style styling (libass)."""
    srt_esc = srt_path.replace("\\", "/").replace(":", "\\:")
    style = (
        "FontName=Arial,Fontsize=80,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,BackColour=&H80000000,Bold=1,"
        "BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=240"
    )
    _run(["ffmpeg", "-y", "-loglevel", "error",
          "-i", video_path,
          "-vf", f"subtitles='{srt_esc}':force_style='{style}'",
          "-c:a", "copy",
          out_path])
    return out_path


def render_shorts(
    source_path: str,
    clip: Dict,
    out_dir: str,
    transcript_segments: Optional[List[Dict]] = None,
) -> Dict:
    """Render one clip as a 9:16 short with face-aware crop + optional captions.

    Returns the clip dict plus short_path / thumb_path / error. The source must
    exist locally (cache reuse keeps this fast).
    """
    rank = int(clip.get("rank", 0))
    name = clip.get("name") or _slugify(str(clip.get("title", "clip")))
    start = float(clip["start_time"])
    end = float(clip["end_time"])
    os.makedirs(out_dir, exist_ok=True)

    result = dict(clip)
    base = os.path.join(out_dir, f"{rank}_{name}_short")
    try:
        info = probe_video(source_path) or {}
        src_w = int(info.get("width") or 1280)
        src_h = int(info.get("height") or 720)
        duration = max(0.1, end - start)
        target_ratio = SHORTS_WIDTH / SHORTS_HEIGHT
        src_ratio = src_w / src_h

        # plan crop segments (faces -> tracking; else single center segment)
        segments: List[Tuple[float, float, float]] = []
        if SHORTS_FACE_CROP and src_ratio >= target_ratio:
            try:
                from . import smartcrop as sc

                samples = [s for s in sc.sample_faces(source_path) if start <= s[0] <= end]
                if samples:
                    segments = sc.plan_crop_segments(samples, duration)
            except Exception:  # noqa: BLE001 — face crop must never kill a render
                segments = []
        if not segments:
            segments = [(0.0, duration, 0.5)]

        parts: List[str] = []
        tmp_dir = tempfile.mkdtemp(prefix="short_")
        try:
            for i, (seg_start, seg_end, seg_x) in enumerate(segments):
                from .smartcrop import compute_crop_window

                crop = compute_crop_window(src_w, src_h, SHORTS_WIDTH, SHORTS_HEIGHT, seg_x)
                part = os.path.join(tmp_dir, f"p{i:02d}.mp4")
                _encode_segment(
                    source_path, start + seg_start, seg_end - seg_start,
                    crop, part, SHORTS_FADE_SECONDS, i == len(segments) - 1,
                )
                parts.append(part)
            raw_short = f"{base}.mp4"
            _concat(parts, raw_short)

            short_path = raw_short
            if SHORTS_CAPTIONS and transcript_segments:
                srt_path = os.path.join(out_dir, f"{rank}_{name}_short.srt")
                build_clip_srt(transcript_segments, start, end, srt_path)
                captioned = f"{base}_captioned.mp4"
                burn_srt_captions(raw_short, srt_path, captioned)
                short_path = captioned
            result["short_path"] = short_path
        finally:
            import shutil

            shutil.rmtree(tmp_dir, ignore_errors=True)

        # thumbnail at the hook
        thumb = f"{base}.jpg"
        try:
            _run(["ffmpeg", "-y", "-loglevel", "error",
                  "-ss", f"{start + 0.5:.3f}", "-i", source_path,
                  "-frames:v", "1", "-q:v", "3", thumb])
            result["thumb_path"] = thumb
        except Exception:  # noqa: BLE001
            result["thumb_path"] = None
        print(f"[shorts] rendered {rank} → {short_path}", flush=True)
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
) -> List[Dict]:
    """Render every clip as a 9:16 short (batch)."""
    results = []
    for clip in clips:
        results.append(render_shorts(source_path, clip, out_dir, transcript_segments))
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
            cmd += ["-i", music_path,
                    "-filter_complex",
                    f"[0:a]volume=1.0[voice];[1:a]volume={music_volume}[music];"
                    f"[voice][music]amix=inputs=2:duration=first:dropout_transition=2[aout]",
                    "-map", "0:v", "-map", "[aout]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "128k"]
        else:
            cmd += ["-c", "copy"]
        cmd.append(out_path)
        _run(cmd)
    finally:
        os.unlink(list_path)
    return out_path
