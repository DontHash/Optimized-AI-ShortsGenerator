"""Cut clips at original aspect ratio with ffmpeg. No vertical reframing."""
import os
import re
import subprocess
from typing import Dict, List


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "clip").lower()).strip("-")
    return (slug or "clip")[:60]


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
        # -ss before -i: fast keyframe seek (can be ~1–2s off)
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
        except Exception as e:
            print(f"[render] {rank} failed: {e}", flush=True)
            results.append({**clip, "clip_path": None, "error": str(e)})
    return results
