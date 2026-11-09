"""YouTube-native transcripts: fetch YouTube's own captions for a URL list.

No Whisper — this is strictly the (auto)captions YouTube already serves.
Videos without captions are reported as failures instead of falling back to a
speech model. Optionally also downloads the best audio-only stream (m4a), which
keeps audio + transcript pairs together for ASR datasets.
"""
import concurrent.futures
import json
import os
from typing import Callable, Dict, List, Optional

from .caption_tracks import fetch_source_subs as fetch_auto_subs
from .config import OUTPUT_DIR
from .downloader import download_audio, extract_youtube_video_id, normalize_url
from .transcriber import load_srt_file

DEFAULT_OUT_DIR = os.path.join(OUTPUT_DIR, "transcripts")


def _srt_to_text(srt_path: str) -> str:
    """Plain text with timestamps stripped, one caption segment per line."""
    parsed = load_srt_file(srt_path)
    return "\n".join(
        str(seg.get("text", "")).strip()
        for seg in parsed.get("segments", [])
        if str(seg.get("text", "")).strip()
    )


def _find_cached(out_dir: str, video_id: str, requested: List[str]) -> Optional[str]:
    """Existing final SRT for this video in one of the requested languages."""
    if not os.path.isdir(out_dir):
        return None
    for lang in requested:
        path = os.path.join(out_dir, f"{video_id}.{lang}.srt")
        if os.path.isfile(path):
            return path
    return None


def _requested_langs(language: Optional[str], langs: Optional[List[str]]) -> List[str]:
    return [c.strip() for c in (langs or [language or "en"]) if c.strip()] or ["en"]


def _promote_fetched(out_dir: str, video_id: str) -> List[Dict]:
    """Rename yt-dlp's ``source_<id>_auto.<lang>.*`` files to ``<id>.<lang>.*``.

    Also writes a timestamp-free ``.txt`` next to each ``.srt``. Returns one
    entry per caption file: ``{lang, srt, txt}`` (``txt`` is empty for VTT).
    """
    prefix = f"source_{video_id}_auto."
    names = sorted(
        (n for n in os.listdir(out_dir) if n.startswith(prefix) and n.endswith((".srt", ".vtt"))),
        key=lambda n: (not n.endswith(".srt"), n),
    )
    produced: List[Dict] = []
    for name in names:
        lang = name[len(prefix):].rsplit(".", 1)[0] or "und"
        ext = os.path.splitext(name)[1]
        final = os.path.join(out_dir, f"{video_id}.{lang}{ext}")
        os.replace(os.path.join(out_dir, name), final)
        item: Dict = {"lang": lang, "srt": final, "txt": ""}
        if ext == ".srt":
            txt = os.path.join(out_dir, f"{video_id}.{lang}.txt")
            with open(txt, "w", encoding="utf-8") as f:
                f.write(_srt_to_text(final))
            item["txt"] = txt
        produced.append(item)
    return produced


def _run_one(
    url: str,
    out_dir: str,
    language: Optional[str],
    langs: Optional[List[str]],
    force: bool,
    audio: bool,
    audio_only: bool,
) -> Dict:
    """Fetch one video's YouTube captions (and optional m4a audio). Never raises."""
    try:
        video_id = extract_youtube_video_id(url)
        if not video_id:
            return {"ok": False, "url": url, "error": "not a YouTube URL"}
        url = normalize_url(url)

        srt = txt = ""
        cached = False
        problems: List[str] = []
        files: List[str] = []

        if not audio_only:
            cached_path = _find_cached(out_dir, video_id, _requested_langs(language, langs))
            if cached_path and not force:
                txt = os.path.splitext(cached_path)[0] + ".txt"
                if not os.path.isfile(txt):
                    with open(txt, "w", encoding="utf-8") as f:
                        f.write(_srt_to_text(cached_path))
                srt, cached = cached_path, True
            else:
                fetched = fetch_auto_subs(url, out_dir, video_id, language=language, langs=langs)
                if fetched:
                    promoted = _promote_fetched(out_dir, video_id)
                    if promoted:
                        primary = promoted[0]
                        srt, txt = primary["srt"], primary["txt"]
                        files = [p["srt"] for p in promoted] + [p["txt"] for p in promoted if p["txt"]]
                    else:
                        srt = fetched
                else:
                    problems.append("no YouTube captions available (Whisper fallback disabled)")

        audio_path = ""
        if audio or audio_only:
            audio_path = download_audio(url, out_dir, video_id) or ""
            if not audio_path:
                problems.append("audio download failed")

        entry: Dict = {
            "ok": not problems,
            "url": url,
            "video_id": video_id,
            "srt": srt,
            "txt": txt,
            "audio": audio_path,
            "cached": cached,
        }
        if files:
            entry["files"] = files
        if problems:
            entry["error"] = "; ".join(problems)
        return entry
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "url": url, "error": str(e)}


def download_transcripts(
    urls: List[str],
    out_dir: Optional[str] = None,
    language: Optional[str] = None,
    langs: Optional[List[str]] = None,
    force: bool = False,
    workers: int = 1,
    audio: bool = False,
    audio_only: bool = False,
    on_video_done: Optional[Callable[[Dict], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> Dict:
    """Download YouTube's own captions for each URL (SRT + plain .txt).

    ``audio=True`` additionally downloads the best audio-only stream (m4a
    preferred) next to the transcript; ``audio_only=True`` skips captions.
    ``workers`` > 1 fetches videos in parallel (I/O-bound). `on_video_done(entry)`
    is called as each video finishes; `is_cancelled()` is checked between videos,
    like ``queue.process_queue``. There is no Whisper fallback: videos without
    captions land in ``report["failed"]`` (unless ``audio_only``).
    """
    out_dir = out_dir or DEFAULT_OUT_DIR
    os.makedirs(out_dir, exist_ok=True)

    report: Dict = {"ok": [], "failed": []}
    total = len(urls)
    cancelled = False

    def _finish(entry: Dict) -> None:
        (report["ok"] if entry.get("ok") else report["failed"]).append(entry)
        if on_video_done:
            try:
                on_video_done(entry)
            except Exception:  # noqa: BLE001
                pass

    if workers > 1 and total > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    _run_one, url, out_dir, language, langs, force, audio, audio_only
                ): url
                for url in urls
            }
            for future in concurrent.futures.as_completed(futures):
                if cancelled or (is_cancelled and is_cancelled()):
                    cancelled = True
                    break
                entry = future.result()
                _finish(entry)
                print(f"\n[transcripts] finished {entry['url']}", flush=True)
            if cancelled:
                for fut in futures:
                    fut.cancel()
    else:
        for i, url in enumerate(urls, 1):
            if cancelled or (is_cancelled and is_cancelled()):
                cancelled = True
                break
            print(f"\n[{i}/{total}] {url}", flush=True)
            _finish(_run_one(url, out_dir, language, langs, force, audio, audio_only))

    report_path = os.path.join(out_dir, "transcripts_report.json")
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
    except OSError:
        pass
    print(
        f"\n[transcripts] done — {len(report['ok'])} ok, {len(report['failed'])} failed"
        + (", cancelled" if cancelled else "")
        + f" → {report_path}",
        flush=True,
    )
    report["cancelled"] = cancelled
    return report
