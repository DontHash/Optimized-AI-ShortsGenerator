"""YouTube download via yt-dlp. Returns a local media path + metadata."""
import os
import re
from typing import Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .config import DOWNLOAD_FORMAT, OUTPUT_DIR


def _import_ytdlp():
    try:
        import yt_dlp  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "yt-dlp is required. Install it with:\n    pip install -r requirements.txt"
        ) from e
    return yt_dlp


def _format_for(fmt: str) -> str:
    """Map '720' / '1080' to a yt-dlp selector that tolerates VP9/webm sources."""
    try:
        height = int(fmt)
    except ValueError:
        height = 1080
    # Prefer height cap, any codec; merge to mp4. Avoid silent 720p mp4 fallback.
    return (
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


def _existing_download(out_dir: str, video_id: str) -> Optional[str]:
    for ext in (".mp4", ".mkv", ".webm"):
        candidate = os.path.join(out_dir, f"source_{video_id}{ext}")
        if os.path.exists(candidate):
            return candidate
    return None


def download_youtube(
    video_url: str,
    fmt: Optional[str] = None,
    out_dir: Optional[str] = None,
) -> Tuple[str, Dict]:
    """Download a YouTube URL. Returns (local_path, info_dict)."""
    yt_dlp = _import_ytdlp()
    video_id = require_youtube_url(video_url)
    fmt = fmt or DOWNLOAD_FORMAT
    out_dir = out_dir or OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)

    cached = _existing_download(out_dir, video_id)
    if cached:
        print(f"[download] reusing cached: {cached}", flush=True)
        # Lightweight probe for title/duration without re-download
        ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(video_url, download=False)
            except Exception:
                info = {"id": video_id, "title": video_id, "duration": 0}
        return cached, info

    print(f"[download] {video_url} @ {fmt}p → {out_dir}/", flush=True)
    ydl_opts = {
        "format": _format_for(fmt),
        "outtmpl": os.path.join(out_dir, "source_%(id)s.%(ext)s"),
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
            for ext in (".mp4", ".mkv", ".webm"):
                if os.path.exists(stem + ext):
                    path = stem + ext
                    break

    print(f"[download] ready: {path}", flush=True)
    return path, info
