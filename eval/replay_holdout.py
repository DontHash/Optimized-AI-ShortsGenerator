"""Replay-holdout validation (see UPLIFT_PLAN.md §5).

Ground-truth check with no labels: on videos that HAVE a YouTube replay heatmap,
score how well the chosen clip windows land on real replay peaks — using a heatmap
the ranker was NOT allowed to see (replay weight forced to 0). If the remaining
signals (audio/chapter/semantic + LLM) still land on replay peaks better than
random windows, they are genuinely finding what audiences rewatch.

Usage:
    python -m eval.replay_holdout URL1 URL2 ...
    python -m eval.replay_holdout urls.txt --num-clips 5
"""
import argparse
import os
import random
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Force replay out of the ranker BEFORE importing the pipeline/config
os.environ["RERANK_WEIGHTS"] = os.environ.get(
    "RERANK_HOLDOUT_WEIGHTS", "llm:0.55,replay:0.0,audio:0.30,chapter:0.15"
)

from shorts_generator import signals as sig  # noqa: E402
from shorts_generator.downloader import extract_youtube_video_id  # noqa: E402
from shorts_generator.pipeline import find_clips  # noqa: E402
from shorts_generator.queue import load_urls  # noqa: E402


def _random_baseline(heatmap, clip_lengths, trials=200):
    duration = heatmap[-1]["end"]
    scores = []
    for _ in range(trials):
        total = 0.0
        for length in clip_lengths:
            start = random.uniform(0, max(0.1, duration - length))
            total += sig.heatmap_mean(heatmap, start, start + length)
        scores.append(total / max(1, len(clip_lengths)))
    return sum(scores) / len(scores)


def evaluate(url, num_clips):
    video_id = extract_youtube_video_id(url)
    payload = find_clips(url, num_clips=num_clips, force=True)
    clips = payload.get("clips", [])
    if not clips:
        return None

    # Reload heatmap from the sidecar the pipeline wrote (ranker never used it)
    heatmap_path = os.path.join("output", video_id, "heatmap.json")
    if not os.path.isfile(heatmap_path):
        print(f"  {video_id}: no heatmap — skipped (needs a higher-view video)")
        return None
    import json
    with open(heatmap_path, encoding="utf-8") as f:
        heatmap = sig.normalize_heatmap(json.load(f))

    lengths = [c["end_time"] - c["start_time"] for c in clips]
    picked = sum(sig.heatmap_mean(heatmap, c["start_time"], c["end_time"]) for c in clips) / len(clips)
    baseline = _random_baseline(heatmap, lengths)
    lift = (picked / baseline - 1.0) * 100 if baseline else 0.0
    print(f"  {video_id}: picked={picked:.3f}  random={baseline:.3f}  lift={lift:+.0f}%")
    return picked, baseline, lift


def main():
    parser = argparse.ArgumentParser(description="Replay-holdout validation")
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--num-clips", type=int, default=5)
    args = parser.parse_args()

    print(f"Reranker weights (replay held out): {os.environ['RERANK_WEIGHTS']}\n")
    results = []
    for url in load_urls(args.urls):
        try:
            r = evaluate(url, args.num_clips)
            if r:
                results.append(r)
        except Exception as e:
            print(f"  FAILED {url}: {e}")

    if results:
        avg_lift = sum(r[2] for r in results) / len(results)
        wins = sum(1 for r in results if r[2] > 0)
        print(f"\n{len(results)} videos · {wins} beat random · mean lift {avg_lift:+.0f}%")
        print("PASS" if avg_lift > 0 else "FAIL (signals not beating random on held-out replay)")
    else:
        print("\nNo videos with heatmaps evaluated.")


if __name__ == "__main__":
    main()
