"""Clip-finding pipeline: download → transcribe → signals → rank → clips.json."""
import json
import os
import re
from typing import Dict, List, Optional

from . import rerank
from . import signals as sig
from .caption_tracks import fetch_source_subs
from .clipper import render_clips, render_shorts
from .config import (
    AUDIO_ENERGY_ENABLED,
    AUTO_SUBS_ENABLED,
    AUTO_SUBS_LANGS,
    DOWNLOAD_FORMAT,
    MAX_CLIP_SECONDS,
    OUTPUT_DIR,
    SPONSORBLOCK_ENABLED,
    YTDLP_COOKIES_FILE,
    YTDLP_COOKIES_FROM_BROWSER,
)
from .downloader import (
    download_youtube,
    extract_youtube_video_id,
    fetch_sponsor_segments,
    fetch_thumbnail,
    find_local_source,
)
from .highlights import get_highlights, snap_to_sentence_boundaries, transcript_excerpt
from .llm import call_llm
from .transcriber import load_srt_file, load_word_srt, transcribe


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "clip").lower()).strip("-")
    return (slug or "clip")[:60]


def format_hms(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:04.1f}"


def _cached_segments(video_dir: str) -> List[Dict]:
    """Cached transcript for a re-run: prefer word-level, then source SRT."""
    try:
        names = sorted(os.listdir(video_dir))
    except OSError:
        return []
    word_srt = next((n for n in names if n.endswith(".words.srt")), None)
    if word_srt:
        words = load_word_srt(os.path.join(video_dir, word_srt))
        if words:
            return words
    srt_names = [
        n for n in names
        if n.endswith(".srt") and not n.endswith(".words.srt") and not n.endswith("_short.srt")
    ]
    srt_names.sort(key=lambda n: (not n.startswith("source_"), n))
    for name in srt_names:
        try:
            loaded = load_srt_file(os.path.join(video_dir, name))
        except (OSError, ValueError):
            continue
        if loaded.get("segments"):
            return loaded["segments"]
    return []


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
        clip = {
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
        }
        if "llm_score" in h:
            clip["llm_score"] = h["llm_score"]
        if "signals" in h:
            clip["signals"] = h["signals"]
        if h.get("context_expanded"):
            clip["context_expanded"] = True
        clips.append(clip)
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
    shorts: bool = False,
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
        clips = payload.get("clips", [])
        changed = False
        source_path = ""
        if shorts:
            missing = [
                c for c in clips
                if not (c.get("short_path") and os.path.isfile(str(c.get("short_path"))))
            ]
            if missing:
                source_path = find_local_source(
                    video_dir, video_id, fmt=download_format or DOWNLOAD_FORMAT
                )
                if not source_path:
                    source_path, _info = download_youtube(
                        youtube_url, fmt=download_format or DOWNLOAD_FORMAT, out_dir=video_dir
                    )
                segments = _cached_segments(video_dir)
                rendered = {
                    int(c.get("rank", 0)): render_shorts(source_path, c, video_dir, segments)
                    for c in missing
                }
                payload["clips"] = [
                    rendered.get(int(c.get("rank", 0)), c) for c in clips
                ]
                changed = True
        elif render:
            missing = [
                c for c in clips
                if not (c.get("clip_path") and os.path.isfile(str(c.get("clip_path"))))
            ]
            if missing:
                source_path = find_local_source(
                    video_dir, video_id, fmt=download_format or DOWNLOAD_FORMAT
                )
                if not source_path:
                    source_path, _info = download_youtube(
                        youtube_url, fmt=download_format or DOWNLOAD_FORMAT, out_dir=video_dir
                    )
                rendered = {
                    int(c.get("rank", 0)): c
                    for c in render_clips(
                        source_path, missing, out_dir=video_dir, accurate=accurate_cut
                    )
                }
                payload["clips"] = [
                    rendered.get(int(c.get("rank", 0)), c) for c in clips
                ]
                changed = True
        if changed:
            with open(clips_json_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        return payload

    fmt = download_format or DOWNLOAD_FORMAT
    if force and find_local_source(video_dir, video_id, fmt=fmt):
        print("[pipeline] --force retry: reusing cached download/transcript when available", flush=True)
    source_path, info = download_youtube(youtube_url, fmt=fmt, out_dir=video_dir)
    video_title = str(info.get("title") or video_id)
    thumbnail_path = fetch_thumbnail(info.get("thumbnail"), video_dir)

    # Put transcript cache next to the source so re-runs stay cheap.
    # Free path: fetch YouTube auto-captions; fall back to faster-whisper if absent.
    auto_subs_path = None
    if AUTO_SUBS_ENABLED:
        sub_langs = [language] if language else AUTO_SUBS_LANGS
        auto_subs_path = fetch_source_subs(
            youtube_url,
            video_dir,
            video_id,
            language=language,
            langs=sub_langs,
            cookies_from_browser=YTDLP_COOKIES_FROM_BROWSER or None,
            cookies_file=YTDLP_COOKIES_FILE or None,
            info=info,
        )
        if not auto_subs_path:
            print("[transcribe] no YouTube captions found; falling back to faster-whisper", flush=True)
    transcript = transcribe(
        source_path,
        language=language,
        cache_dir=video_dir,
        auto_subs_path=auto_subs_path,
    )
    if not transcript["segments"]:
        raise RuntimeError("Whisper produced no segments. The video may have no detectable speech.")
    segments = transcript["segments"]

    # --- Signals (all degrade gracefully to None/empty) ---
    heatmap = sig.normalize_heatmap(info.get("heatmap"))
    chapters = sig.normalize_chapters(info.get("chapters"))
    energy = None
    if AUDIO_ENERGY_ENABLED:
        energy = sig.compute_audio_energy(
            source_path, cache_path=os.path.join(video_dir, "audio_energy.json")
        )

    if heatmap:
        sig.write_heatmap_json(video_dir, heatmap)
        peaks = sig.peak_windows(heatmap, top_n=3)
        peak_str = ", ".join(sig.hms(p["start"]) for p in peaks)
        print(f"[signals] replay {sig.sparkline(heatmap)}  peaks: {peak_str}", flush=True)
    else:
        print("[signals] no replay heatmap (low-view or unavailable)", flush=True)
    print(
        f"[signals] chapters={len(chapters)} "
        f"audio_energy={'yes' if energy else 'no'}",
        flush=True,
    )

    boundaries = sig.candidate_boundaries(segments, heatmap, energy)

    # LLM candidate generation (min_score deferred until after fusion).
    # Pass raw signals so get_highlights can build chunk-relative hints for long videos.
    highlights_result = get_highlights(
        transcript,
        num_clips=num_clips,
        llm_fn=call_llm,
        min_score=0,
        signals={
            "heatmap": heatmap,
            "chapters": chapters,
            "boundaries": boundaries,
            "energy": energy,
        },
    )
    all_highlights: List[Dict] = highlights_result.get("highlights", [])
    if not all_highlights:
        raise RuntimeError("Highlight generator returned zero clips.")

    # --- Signal fusion → context expansion → dedupe → filter ---
    ranked = rerank.fuse(all_highlights, heatmap, chapters, energy)
    ranked = rerank.expand_for_context(ranked, segments, heatmap, energy)
    ranked = snap_to_sentence_boundaries(ranked, segments)
    # Boundary snap can extend past the expansion guard; enforce the cap after
    # snapping so a short never silently exceeds MAX_CLIP_SECONDS.
    for h in ranked:
        start = float(h["start_time"])
        end = float(h["end_time"])
        if end - start > MAX_CLIP_SECONDS:
            h["end_time"] = start + MAX_CLIP_SECONDS
    ranked = rerank.dedupe_semantic(ranked)
    if SPONSORBLOCK_ENABLED:
        sponsor_segments = fetch_sponsor_segments(video_id)
        if sponsor_segments:
            before = len(ranked)
            ranked = rerank.filter_sponsor_overlaps(ranked, sponsor_segments)
            dropped = before - len(ranked)
            if dropped:
                print(
                    f"[signals] SponsorBlock: dropped {dropped} clip(s) overlapping "
                    f"{len(sponsor_segments)} sponsor/intro segment(s)",
                    flush=True,
                )
    for h in ranked:
        h["transcript_excerpt"] = transcript_excerpt(
            segments, float(h["start_time"]), float(h["end_time"])
        )
    if min_score > 0:
        ranked = [h for h in ranked if int(h.get("score", 0)) >= min_score]

    duration = float(transcript.get("duration") or info.get("duration") or 0)
    payload = _build_clips_payload(
        video_id=video_id,
        video_title=video_title,
        source_url=youtube_url,
        duration=duration,
        highlights=ranked,
        num_clips=num_clips,
    )
    payload["thumbnail_path"] = thumbnail_path

    if render and not shorts:
        print(f"[pipeline] rendering {len(payload['clips'])} clips", flush=True)
        payload["clips"] = render_clips(
            source_path, payload["clips"], out_dir=video_dir, accurate=accurate_cut
        )

    if shorts:
        print(f"[pipeline] rendering {len(payload['clips'])} shorts (9:16)", flush=True)
        from .clipper import render_all_shorts

        # Prefer word-level cues when a word cache exists; sentence segments
        # still produce readable ASS captions.
        render_segments = _cached_segments(video_dir) or segments
        payload["clips"] = render_all_shorts(
            source_path, payload["clips"], out_dir=video_dir, transcript_segments=render_segments
        )

    with open(clips_json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"[pipeline] wrote {clips_json_path}", flush=True)

    payload["_all_highlights"] = all_highlights  # for CLI summary; not in clips.json
    payload["_clips_json"] = clips_json_path
    return payload
