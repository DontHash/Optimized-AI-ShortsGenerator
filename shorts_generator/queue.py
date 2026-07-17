"""Process a queue of YouTube URLs with fault isolation + resumability."""
import json
import os
from typing import Dict, List, Optional

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
) -> Dict:
    out_root = out_root or OUTPUT_DIR
    os.makedirs(out_root, exist_ok=True)

    report = {"ok": [], "failed": []}
    total = len(urls)

    for i, url in enumerate(urls, 1):
        print(f"\n[{i}/{total}] {url}", flush=True)
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
            )
            report["ok"].append({
                "url": url,
                "video_id": result.get("video_id"),
                "clips": len(result.get("clips", [])),
                "clips_json": os.path.join(out_root, result.get("video_id", ""), "clips.json"),
            })
        except Exception as e:
            print(f"[{i}/{total}] FAILED: {e}", flush=True)
            report["failed"].append({"url": url, "error": str(e)})

    report_path = os.path.join(out_root, "queue_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(
        f"\n[queue] done — {len(report['ok'])} ok, {len(report['failed'])} failed → {report_path}",
        flush=True,
    )
    return report
