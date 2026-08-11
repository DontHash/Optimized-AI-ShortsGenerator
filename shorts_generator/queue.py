"""Process a queue of YouTube URLs with fault isolation + resumability.

Supports parallel processing (`workers > 1`): downloads are network-bound, so
several videos can download concurrently while transcription/ranking of each
completes in its own worker thread. Per-video callbacks (`on_video_done`) and
cancellation (`is_cancelled`) make the queue usable from a GUI without blocking.
"""
import concurrent.futures
import json
import os
from typing import Callable, Dict, List, Optional

from .config import OUTPUT_DIR
from .pipeline import find_clips


def load_urls(args: List[str]) -> List[str]:
    """Resolve CLI args into a URL list. A single .txt arg = one URL per line."""
    if len(args) == 1 and args[0].lower().endswith(".txt") and os.path.isfile(args[0]):
        urls = []
        with open(args[0], encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    urls.append(line)
        return urls
    return list(args)


def _run_one(
    url: str,
    num_clips: int,
    download_format: Optional[str],
    language: Optional[str],
    min_score: int,
    render: bool,
    accurate_cut: bool,
    force: bool,
    out_root: str,
    shorts: bool = False,
) -> Dict:
    """Run the pipeline for one URL. Returns an ok/failed report entry (never raises)."""
    try:
        result = find_clips(
            youtube_url=url,
            num_clips=num_clips,
            download_format=download_format,
            language=language,
            min_score=min_score,
            render=render,
            accurate_cut=accurate_cut,
            force=force,
            out_root=out_root,
            shorts=shorts,
        )
        return {
            "ok": True,
            "url": url,
            "video_id": result.get("video_id"),
            "clips": len(result.get("clips", [])),
            "clips_json": os.path.join(out_root, str(result.get("video_id", "")), "clips.json"),
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "url": url, "error": str(e)}


def process_queue(
    urls: List[str],
    num_clips: int = 3,
    download_format: Optional[str] = None,
    language: Optional[str] = None,
    min_score: int = 0,
    render: bool = False,
    accurate_cut: bool = False,
    force: bool = False,
    out_root: Optional[str] = None,
    workers: int = 1,
    on_video_done: Optional[Callable[[Dict], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
    shorts: bool = False,
) -> Dict:
    """Process URLs. `workers` > 1 runs videos in parallel (downloads are I/O-bound).

    `on_video_done(entry)` is called as each video finishes (entry has ok/url/
    video_id/clips/clips_json or ok=False + error). `is_cancelled()` checked
    between videos; if it returns True, remaining futures are cancelled.
    """
    out_root = out_root or OUTPUT_DIR
    os.makedirs(out_root, exist_ok=True)

    report = {"ok": [], "failed": []}
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
                    _run_one, url, num_clips, download_format, language, min_score,
                    render, accurate_cut, force, out_root, shorts,
                ): url
                for url in urls
            }
            for future in concurrent.futures.as_completed(futures):
                if cancelled or (is_cancelled and is_cancelled()):
                    cancelled = True
                    break
                entry = future.result()
                _finish(entry)
                print(f"\n[queue] finished {entry['url']}", flush=True)
            if cancelled:
                for f in futures:
                    f.cancel()
    else:
        for i, url in enumerate(urls, 1):
            if cancelled or (is_cancelled and is_cancelled()):
                cancelled = True
                break
            print(f"\n[{i}/{total}] {url}", flush=True)
            entry = _run_one(
                url, num_clips, download_format, language, min_score,
                render, accurate_cut, force, out_root, shorts,
            )
            _finish(entry)

    report_path = os.path.join(out_root, "queue_report.json")
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
    except OSError:
        pass
    print(
        f"\n[queue] done — {len(report['ok'])} ok, {len(report['failed'])} failed"
        + (", cancelled" if cancelled else "")
        + f" → {report_path}",
        flush=True,
    )
    report["cancelled"] = cancelled
    return report
