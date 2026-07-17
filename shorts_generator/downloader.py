"""YouTube download via yt-dlp.

Quality policy mirrors Tyrrrz/YoutubeDownloader.Core (Highest + Mp4 preference):
uncapped best video+audio by default, prefer mp4/m4a when available, ffmpeg merge.
"""
import json
import os
import re
from typing import Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .config import DOWNLOAD_FORMAT, OUTPUT_DIR

# Aliases matching YoutubeDownloader.Core VideoQualityPreference
_MAX_ALIASES = frozenset({"max", "highest", "best", "maxres"})
_LOW_ALIASES = frozenset({"lowest", "min", "worst"})
_MEDIA_EXTS = (".mp4", ".mkv", ".webm")


def _import_ytdlp():
    try:
        import yt_dlp  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "yt-dlp is required. Install it with:\n    pip install -r requirements.txt"
        ) from e
    return yt_dlp


def _normalize_fmt(fmt: str) -> str:
    return (fmt or "max").strip().lower()


def _format_for(fmt: str) -> str:
    """Build a yt-dlp format selector from a quality preference.

    Mirrors YoutubeDownloader's TryGetBestOption:
      Highest  → best video+audio (prefer mp4/m4a, else any codec)
      UpToNp   → same with height<=N
      Lowest   → worst paired streams
    """
    key = _normalize_fmt(fmt)

    if key in _MAX_ALIASES:
        # Prefer same-container mp4+m4a (YoutubeDownloader default Container.Mp4),
        # then any bestvideo+bestaudio — no height cap (Highest).
        return (
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
            "bestvideo+bestaudio/best"
        )

    if key in _LOW_ALIASES:
        return "worstvideo+worstaudio/worst"

    try:
        height = int(key)
    except ValueError:
        height = 1080

    # UpTo{height}p — still prefer mp4/m4a first
    return (
        f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
        f"bestvideo[height<={height}]+bestaudio/"
        f"best[height<={height}]/best"
    )


def extract_youtube_video_id(source: str) -> Optional[str]:
    parsed = urlparse(source)
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]

    if host in ("youtu.be",):
        video_id = parsed.path.lstrip("/").split("/", 1)[0]
        return video_id or None

    if "youtube.com" in host:
        if parsed.path.startswith("/watch"):
            qs = parse_qs(parsed.query)
            video_id = qs.get("v", [""])[0]
            return video_id or None
        match = re.search(r"/(?:shorts|embed|live)/([^/?#&]+)", parsed.path)
        if match:
            return match.group(1)

    return None


def require_youtube_url(source: str) -> str:
    video_id = extract_youtube_video_id(source)
    if not video_id:
        raise RuntimeError(
            f"YouTube URL required (got {source!r}). "
            "Local files and non-YouTube URLs are not supported."
        )
    return video_id


def _fmt_tag(fmt: str) -> str:
    key = _normalize_fmt(fmt)
    if key in _MAX_ALIASES:
        return "max"
    if key in _LOW_ALIASES:
        return "low"
    try:
        return str(int(key))
    except ValueError:
        return "max"


def _meta_path(source_path: str) -> str:
    stem, _ = os.path.splitext(source_path)
    return stem + ".meta.json"


def _save_meta(source_path: str, info: Dict) -> None:
    meta = {
        "id": info.get("id"),
        "title": info.get("title"),
        "duration": info.get("duration"),
    }
    with open(_meta_path(source_path), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def _load_meta(source_path: str, video_id: str) -> Dict:
    path = _meta_path(source_path)
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            meta = json.load(f)
        if meta.get("id") or meta.get("title"):
            return meta
    return {"id": video_id, "title": video_id, "duration": 0}


def find_local_source(
    out_dir: str,
    video_id: str,
    fmt: Optional[str] = None,
) -> Optional[str]:
    """Return a local source file if already downloaded (retry-safe, no network)."""
    if not os.path.isdir(out_dir):
        return None

    if fmt is not None:
        hit = _existing_download(out_dir, video_id, fmt)
        if hit:
            return hit

    # Retry fallback: accept any cached source for this video id in the folder
    prefix = f"source_{video_id}"
    candidates = []
    for name in os.listdir(out_dir):
        lower = name.lower()
        if name.startswith(prefix) and any(lower.endswith(ext) for ext in _MEDIA_EXTS):
            candidates.append(os.path.join(out_dir, name))
    if not candidates:
        return None

    # Prefer exact format tag, then legacy untagged, then largest file
    if fmt is not None:
        tag = _fmt_tag(fmt)
        for path in candidates:
            if f"_{tag}." in os.path.basename(path):
                return path
    for path in candidates:
        base = os.path.basename(path)
        if base in {f"source_{video_id}{ext}" for ext in _MEDIA_EXTS}:
            return path
    return max(candidates, key=lambda p: os.path.getsize(p))


def is_downloaded(
    video_url: str,
    out_dir: Optional[str] = None,
    fmt: Optional[str] = None,
) -> bool:
    video_id = extract_youtube_video_id(video_url)
    if not video_id:
        return False
    out_dir = out_dir or OUTPUT_DIR
    return find_local_source(out_dir, video_id, fmt=fmt or DOWNLOAD_FORMAT) is not None


def _existing_download(out_dir: str, video_id: str, fmt: str) -> Optional[str]:
    """Return cached path for this video_id + quality tag (avoids reusing a lower res)."""
    tag = _fmt_tag(fmt)
    for ext in _MEDIA_EXTS:
        candidate = os.path.join(out_dir, f"source_{video_id}_{tag}{ext}")
        if os.path.exists(candidate):
            return candidate
    if tag == "max":
        for ext in _MEDIA_EXTS:
            legacy = os.path.join(out_dir, f"source_{video_id}{ext}")
            if os.path.exists(legacy):
                return legacy
    return None


def download_youtube(
    video_url: str,
    fmt: Optional[str] = None,
    out_dir: Optional[str] = None,
) -> Tuple[str, Dict]:
    """Download a YouTube URL at the requested quality. Returns (local_path, info_dict)."""
    yt_dlp = _import_ytdlp()
    video_id = require_youtube_url(video_url)
    fmt = _normalize_fmt(fmt or DOWNLOAD_FORMAT)
    out_dir = out_dir or OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    tag = _fmt_tag(fmt)

    cached = find_local_source(out_dir, video_id, fmt=fmt)
    if cached:
        print(f"[download] already on disk, skipping download: {cached}", flush=True)
        info = _load_meta(cached, video_id)
        return cached, info

    label = "max" if tag == "max" else f"{tag}p"
    print(f"[download] {video_url} @ {label} → {out_dir}/", flush=True)
    ydl_opts = {
        "format": _format_for(fmt),
        "outtmpl": os.path.join(out_dir, f"source_%(id)s_{tag}.%(ext)s"),
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=True)
        path = ydl.prepare_filename(info)
        if not os.path.exists(path):
            stem, _ = os.path.splitext(path)
            for ext in _MEDIA_EXTS:
                if os.path.exists(stem + ext):
                    path = stem + ext
                    break

    _save_meta(path, info)
    print(f"[download] ready: {path}", flush=True)
    return path, info
