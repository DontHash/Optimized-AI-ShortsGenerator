"""Clip-finding pipeline: download → transcribe → rank → clips.json (optional render)."""
import json
import os
import re
from typing import Dict, List, Optional

from .clipper import render_clips
from .config import DOWNLOAD_FORMAT, OUTPUT_DIR
from .downloader import download_youtube, extract_youtube_video_id
from .highlights import get_highlights
from .llm import call_llm
from .transcriber import transcribe


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "clip").lower()).strip("-")
    return (slug or "clip")[:60]


def format_hms(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:04.1f}"


def _build_clips_payload(
    video_id: str,
    video_title: str,
    source_url: str,
    duration: float,
    highlights: List[Dict],
    num_clips: int,
) -> Dict:
    top = sorted(highlights, key=lambda h: int(h.get("score", 0)), reverse=True)[:num_clips]
    clips = []
    for rank, h in enumerate(top, 1):
        start = float(h["start_time"])
        end = float(h["end_time"])
        title = str(h.get("title") or "Untitled")
        clips.append({
            "rank": rank,
            "name": _slugify(title),
            "title": title,
            "start_time": start,
            "end_time": end,
            "start_hms": format_hms(start),
            "end_hms": format_hms(end),
            "score": int(h.get("score", 0)),
            "hook_sentence": h.get("hook_sentence", ""),
            "virality_reason": h.get("virality_reason", ""),
            "transcript_excerpt": h.get("transcript_excerpt", ""),
        })
    return {
        "video_id": video_id,
        "video_title": video_title,
        "source_url": source_url,
        "duration": duration,
        "clips": clips,
    }


def find_clips(
    youtube_url: str,
    num_clips: int = 3,
    download_format: Optional[str] = None,
    language: Optional[str] = None,
    min_score: int = 0,
    render: bool = False,
    accurate_cut: bool = False,
    force: bool = False,
    out_root: Optional[str] = None,
) -> Dict:
    """Find viral moments. Writes output/<video_id>/clips.json. Render is opt-in."""
    video_id = extract_youtube_video_id(youtube_url)
    if not video_id:
        raise RuntimeError(f"YouTube URL required (got {youtube_url!r})")

    out_root = out_root or OUTPUT_DIR
    video_dir = os.path.join(out_root, video_id)
    clips_json_path = os.path.join(video_dir, "clips.json")
    os.makedirs(video_dir, exist_ok=True)

    if os.path.exists(clips_json_path) and not force:
        print(f"[pipeline] skipping (exists): {clips_json_path}  (use --force to redo)", flush=True)
        with open(clips_json_path, encoding="utf-8") as f:
            payload = json.load(f)
        if render and not any(c.get("clip_path") for c in payload.get("clips", [])):
            # Need source on disk to render
            source_path, _info = download_youtube(
                youtube_url, fmt=download_format or DOWNLOAD_FORMAT, out_dir=video_dir
            )
            payload["clips"] = render_clips(
                source_path, payload["clips"], out_dir=video_dir, accurate=accurate_cut
            )
            with open(clips_json_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        return payload

    source_path, info = download_youtube(
        youtube_url, fmt=download_format or DOWNLOAD_FORMAT, out_dir=video_dir
    )
    video_title = str(info.get("title") or video_id)

    # Put transcript cache next to the source so re-runs stay cheap
    transcript = transcribe(source_path, language=language, cache_dir=video_dir)
    if not transcript["segments"]:
        raise RuntimeError("Whisper produced no segments. The video may have no detectable speech.")

    highlights_result = get_highlights(
        transcript, num_clips=num_clips, llm_fn=call_llm, min_score=min_score
    )
    all_highlights: List[Dict] = highlights_result.get("highlights", [])
    if not all_highlights:
        raise RuntimeError("Highlight generator returned zero clips.")

    duration = float(transcript.get("duration") or info.get("duration") or 0)
    payload = _build_clips_payload(
        video_id=video_id,
        video_title=video_title,
        source_url=youtube_url,
        duration=duration,
        highlights=all_highlights,
        num_clips=num_clips,
    )

    if render:
        print(f"[pipeline] rendering {len(payload['clips'])} clips", flush=True)
        payload["clips"] = render_clips(
            source_path, payload["clips"], out_dir=video_dir, accurate=accurate_cut
        )

    with open(clips_json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"[pipeline] wrote {clips_json_path}", flush=True)

    payload["_all_highlights"] = all_highlights  # for CLI summary; not in clips.json
    payload["_clips_json"] = clips_json_path
    return payload


# Back-compat alias
def generate_shorts(*args, **kwargs) -> Dict:
    kwargs.pop("aspect_ratio", None)
    kwargs.pop("mode", None)
    return find_clips(*args, **kwargs)
