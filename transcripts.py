"""CLI — download YouTube's own captions (SRT + plain text) for a list of videos.

No video download, no Whisper — only the (auto)captions YouTube already serves.

Usage:
    python transcripts.py urls.txt
    python transcripts.py "https://www.youtube.com/watch?v=..." --langs en,hi
"""
import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from shorts_generator.queue import load_urls
from shorts_generator.transcripts import download_transcripts


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download YouTube's own captions (and optional m4a audio) — no Whisper fallback"
    )
    parser.add_argument(
        "urls",
        nargs="+",
        help="YouTube URL(s), or a .txt file with one URL per line",
    )
    parser.add_argument("--language", default=None, help="Preferred caption language, e.g. 'en'")
    parser.add_argument(
        "--langs",
        default=None,
        help="Comma-separated caption languages to try, e.g. 'ne' for Nepali (Devanagari) or 'ne,ne-orig' (default: en)",
    )
    parser.add_argument(
        "--out",
        default=None,
        metavar="DIR",
        help="Output folder (default: output/transcripts)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Videos fetched in parallel (default: 4)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if a transcript is already cached",
    )
    parser.add_argument(
        "--audio",
        action="store_true",
        help="Also download the best audio-only stream (m4a preferred) per video",
    )
    parser.add_argument(
        "--audio-only",
        action="store_true",
        help="Download audio only, skip captions (implies --audio)",
    )
    args = parser.parse_args()

    urls = load_urls(args.urls)
    if not urls:
        print("No URLs to process.", file=sys.stderr)
        return 1

    langs = [c.strip() for c in (args.langs or "").split(",") if c.strip()] or None
    report = download_transcripts(
        urls,
        out_dir=args.out,
        language=args.language,
        langs=langs,
        force=args.force,
        workers=args.workers,
        audio=args.audio or args.audio_only,
        audio_only=args.audio_only,
    )

    for item in report["ok"]:
        tag = " (cached)" if item.get("cached") else ""
        if item.get("srt"):
            print(f"\nOK  {item['video_id']}{tag}  → {item['srt']}")
        else:
            print(f"\nOK  {item['video_id']}{tag}")
        if item.get("txt"):
            print(f"    text → {item['txt']}")
        if item.get("audio"):
            print(f"    audio → {item['audio']}")
    for item in report["failed"]:
        print(f"\nFAIL  {item['url']}\n      {item['error']}", file=sys.stderr)
        for key in ("srt", "audio"):
            if item.get(key):
                print(f"      partial {key} → {item[key]}", file=sys.stderr)

    return 1 if report["failed"] and not report["ok"] else 0


if __name__ == "__main__":
    sys.exit(main())
