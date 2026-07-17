"""CLI — generate shorts-style captions for local video file(s).

Usage:
    python captions.py "D:\\clips\\my-short.mp4"
    python captions.py clip1.mp4 clip2.mp4 --burn
"""
import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from shorts_generator.captions import generate_captions


def main() -> int:
    parser = argparse.ArgumentParser(description="Shorts-style captions for local videos")
    parser.add_argument(
        "videos",
        nargs="*",
        help="Local video path(s). If omitted, prompts interactively.",
    )
    parser.add_argument("--language", default=None, help="Force Whisper language, e.g. 'en'")
    parser.add_argument(
        "--burn",
        action="store_true",
        help="Hard-burn .ass captions onto a new mp4",
    )
    args = parser.parse_args()

    videos = list(args.videos)
    if not videos:
        raw = input("Video file path(s), space-separated: ").strip()
        videos = raw.split() if raw else []
    if not videos:
        print("No videos given.", file=sys.stderr)
        return 1

    failed = 0
    for path in videos:
        try:
            result = generate_captions(path, language=args.language, burn=args.burn)
            print(f"\n{path}")
            for k, v in result.items():
                print(f"  {k}: {v}")
        except Exception as e:
            print(f"\nFAILED {path}: {e}", file=sys.stderr)
            failed += 1

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
