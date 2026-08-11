"""TikTok downloader — watermark-free video + title + thumbnail.

No ranking/analysis (unlike the YouTube clip engine): this module downloads the
video and captures its metadata. Watermark-free by selecting yt-dlp formats that
exclude the watermarked ``download`` format (TikTok serves clean ``bytevc1/h264``
CDN copies for in-app playback).

Reliability: yt-dlp needs impersonation support for TikTok's JS challenge
(``pip install curl-cffi``), cookies help when logged in, and TikTok rate-limits
aggressively — so the downloader retries once with a backoff and degrades to
clear error messages in the queue.
"""
import os
import re
import time
from typing import Dict, List, Optional

from .config import OUTPUT_DIR
from .downloader import fetch_thumbnail

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_TIKTOK_ID_RE = re.compile(r"tiktok\.com/(?:@[\w.]+/)?video/(\d+)", re.IGNORECASE)
_MEDIA_EXTS = (".mp4", ".mkv", ".webm")


def extract_tiktok_id(url: str) -> Optional[str]:
    """Best-effort TikTok video id from a URL. None for non-TikTok/other URLs."""
    if not url or "tiktok.com" not in url.lower():
        return None
    match = _TIKTOK_ID_RE.search(url)
    return match.group(1) if match else None


def watermark_free_format() -> str:
    """yt-dlp format selector: best video+audio, skipping the watermarked 'download' format."""
    return 'bv*+ba/b[format_id!="download"]/b'


def _import_ytdlp():
    try:
        import yt_dlp  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "yt-dlp is required. Install it with:\n    pip install -r requirements.txt"
        ) from e
    return yt_dlp


def _base_opts(out_dir: str, video_id: str, fmt: str) -> Dict:
    return {
        "format": fmt,
        "outtmpl": os.path.join(out_dir, f"source_{video_id}.%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "http_headers": {"User-Agent": _USER_AGENT},
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 30,
    }


def _resolve_path(info: Dict, out_dir: str, video_id: str) -> str:
    path = info.get("_filename") or ""
    if path and os.path.isfile(path):
        return path
    stem = os.path.join(out_dir, f"source_{video_id}")
    for ext in _MEDIA_EXTS:
        if os.path.isfile(stem + ext):
            return stem + ext
    return ""


def download_tiktok(
    url: str,
    out_root: Optional[str] = None,
    use_cookies: bool = False,
) -> Dict:
    """Download one TikTok video without watermark. Returns a report entry (never raises).

    Entry fields: ok, url, video_id, title, author, duration, stats, thumbnail_path,
    source_path, clips_json (for queue report parity), or ok=False + error.
    """
    video_id = extract_tiktok_id(url)
    if not video_id:
        return {
            "ok": False, "url": url,
            "error": "Not a TikTok video URL (expected https://www.tiktok.com/@user/video/ID)",
        }

    out_root = out_root or OUTPUT_DIR
    video_dir = os.path.join(out_root, "tiktok", video_id)
    os.makedirs(video_dir, exist_ok=True)

    yt_dlp = _import_ytdlp()
    fmt = watermark_free_format()
    last_err: Optional[Exception] = None

    for attempt in range(2):  # one retry with backoff — TikTok rate-limits hard
        opts = _base_opts(video_dir, video_id, fmt)
        if use_cookies:
            opts["cookiesfrombrowser"] = ("chrome",)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
            source_path = _resolve_path(info, video_dir, video_id)
            if not source_path:
                raise RuntimeError("download finished but no media file found")
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt == 0:
                time.sleep(3)
                # second attempt falls back to any format (watermark-free may be unavailable)
                fmt = "bv*+ba/b"
    else:
        return {"ok": False, "url": url, "video_id": video_id, "error": str(last_err)}

    thumbnail_path = fetch_thumbnail(info.get("thumbnail"), video_dir)
    title = str(info.get("description") or info.get("title") or "").strip()
    if not title:
        title = f"@{info.get('channel', video_id)} TikTok video"

    stats = {
        "views": int(info.get("view_count") or 0),
        "likes": int(info.get("like_count") or 0),
        "comments": int(info.get("comment_count") or 0),
        "saves": int(info.get("save_count") or 0),
    }
    return {
        "ok": True,
        "url": url,
        "video_id": video_id,
        "title": title,
        "author": str(info.get("channel") or ""),
        "duration": float(info.get("duration") or 0),
        "stats": stats,
        "thumbnail_path": thumbnail_path,
        "source_path": source_path,
        "clips_json": os.path.join(video_dir, "download.json"),
    }


def process_tiktok_queue(
    urls: List[str],
    out_root: Optional[str] = None,
    workers: int = 1,
    on_video_done=None,
    is_cancelled=None,
) -> Dict:
    """Queue of TikTok URLs with fault isolation + parallel workers (mirrors queue.py)."""
    import concurrent.futures
    import json

    out_root = out_root or OUTPUT_DIR
    os.makedirs(out_root, exist_ok=True)
    report = {"ok": [], "failed": []}
    cancelled = False

    def _finish(entry: Dict) -> None:
        (report["ok"] if entry.get("ok") else report["failed"]).append(entry)
        if on_video_done:
            try:
                on_video_done(entry)
            except Exception:  # noqa: BLE001
                pass

    if workers > 1 and len(urls) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(download_tiktok, url, out_root) for url in urls]
            for future in concurrent.futures.as_completed(futures):
                if cancelled or (is_cancelled and is_cancelled()):
                    cancelled = True
                    break
                _finish(future.result())
            if cancelled:
                for f in futures:
                    f.cancel()
    else:
        for url in urls:
            if cancelled or (is_cancelled and is_cancelled()):
                cancelled = True
                break
            print(f"[tiktok] {url}", flush=True)
            _finish(download_tiktok(url, out_root))

    report_path = os.path.join(out_root, "queue_report_tiktok.json")
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
    except OSError:
        pass
    print(
        f"[tiktok] done — {len(report['ok'])} ok, {len(report['failed'])} failed"
        + (", cancelled" if cancelled else "")
        + f" → {report_path}",
        flush=True,
    )
    report["cancelled"] = cancelled
    return report
