"""CLI — find viral clips from one or more YouTube URLs.
# python main.py "https://www.youtube.com/watch?v=xmIKHROpeOY" --num-clips 5  --format max --language en --render --accurate-cut --force
Usage:
    python main.py "https://www.youtube.com/watch?v=..."
    python main.py URL1 URL2 URL3 --num-clips 5
    python main.py urls.txt --render
"""
import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from shorts_generator.config import DOWNLOAD_FORMAT
from shorts_generator.queue import load_urls, process_queue


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clip-finding engine: timestamps + optional original-ratio cuts"
    )
    parser.add_argument(
        "urls",
        nargs="+",
        help="YouTube URL(s), or a .txt file with one URL per line",
    )
    parser.add_argument("--num-clips", type=int, default=3, help="Max clips per video (default: 3)")
    parser.add_argument(
        "--min-score",
        type=int,
        default=0,
        help="Drop clips below this virality score (default: 0 = keep all)",
    )
    parser.add_argument(
        "--format",
        default=DOWNLOAD_FORMAT,
        help=f"Download quality: max (uncapped) | 360 / 480 / 720 / 1080 (default: {DOWNLOAD_FORMAT})",
    )
    parser.add_argument("--language", default=None, help="Force Whisper language, e.g. 'en'")
    parser.add_argument(
        "--render",
        action="store_true",
        help="Also cut original-ratio mp4s (default: timestamps JSON only)",
    )
    parser.add_argument(
        "--accurate-cut",
        action="store_true",
        help="With --render, re-encode for frame-accurate cuts (slower)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Redo clip analysis even if clips.json exists; still reuses cached download/transcript",
    )
    parser.add_argument(
        "--no-browser-cookies",
        action="store_true",
        help="Do not read YouTube cookies from your browser (cookies are on by default)",
    )
    parser.add_argument(
        "--cookies-from-browser",
        default=None,
        metavar="BROWSER",
        help="Override default browser for cookies (edge/chrome/firefox/brave; optionally BROWSER:PROFILE)",
    )
    parser.add_argument(
        "--cookies",
        default=None,
        metavar="FILE",
        help="Path to a cookies.txt file (alternative to browser cookies)",
    )
    args = parser.parse_args()

    import os
    if args.no_browser_cookies:
        os.environ["YTDLP_COOKIES_FROM_BROWSER"] = "none"
    elif args.cookies_from_browser:
        os.environ["YTDLP_COOKIES_FROM_BROWSER"] = args.cookies_from_browser
    if args.cookies:
        os.environ["YTDLP_COOKIES_FILE"] = args.cookies

    urls = load_urls(args.urls)
    if not urls:
        print("No URLs to process.", file=sys.stderr)
        return 1

    report = process_queue(
        urls,
        num_clips=args.num_clips,
        download_format=args.format,
        language=args.language,
        min_score=args.min_score,
        render=args.render,
        accurate_cut=args.accurate_cut,
        force=args.force,
    )

    for item in report["ok"]:
        print(f"\nOK  {item['video_id']}  {item['clips']} clips → {item['clips_json']}")
    for item in report["failed"]:
        print(f"\nFAIL  {item['url']}\n      {item['error']}", file=sys.stderr)

    return 1 if report["failed"] and not report["ok"] else 0


if __name__ == "__main__":
    sys.exit(main())
