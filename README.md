# ClipClipper — YouTube Clip-Finding Engine

Find the viral moments in long YouTube videos. Output is **timestamps + ranked clips as JSON**; cutting mp4s and captions are optional follow-on steps.

No MuAPI. No vertical crop. Local pipeline only: `yt-dlp` → `faster-whisper` → OpenAI/Gemini ranking → `clips.json`.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env   # set OPENAI_API_KEY or GEMINI_API_KEY
```

Requires `ffmpeg` on PATH.

```bash
# Timestamps only (default)
python main.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Multiple URLs or a file
python main.py URL1 URL2 URL3
python main.py urls.txt --num-clips 5

# Also cut original-ratio mp4s
python main.py urls.txt --render

# Captions for any local video (separate tool)
python captions.py output/VIDEO_ID/1_the-hook.mp4 --burn
```

## Output

Each video lands in `output/<video_id>/`:

```
output/<video_id>/
  source_<id>_max.mp4  # cached download (quality-tagged)
  source_<id>_max.srt  # cached transcript
  audio_energy.json    # cached loudness/spike/pause curve
  heatmap.json         # YouTube "Most Replayed" graph (when available)
  clips.json           # the product
  1_slug.mp4           # only with --render
```

`clips.json` shape:

```json
{
  "video_id": "6G0bG6qWqTs",
  "video_title": "...",
  "source_url": "https://...",
  "duration": 1873.4,
  "clips": [
    {
      "rank": 1,
      "name": "the-one-mistake-that-cost-me-50k",
      "title": "The one mistake that cost me $50K",
      "start_time": 124.3,
      "end_time": 187.6,
      "start_hms": "00:02:04.3",
      "end_hms": "00:03:07.6",
      "score": 92,
      "llm_score": 88,
      "hook_sentence": "...",
      "virality_reason": "...",
      "transcript_excerpt": "...",
      "context_expanded": true,
      "signals": {
        "llm": 0.91, "replay": 0.80, "audio": 0.55, "chapter": 1.0,
        "final_score": 92.0, "signals_present": ["audio","chapter","llm","replay"]
      }
    }
  ]
}
```

`score` is the **fused** 0–100 rank (LLM + replay + audio + chapter); `llm_score`
keeps the raw model score, and `signals` shows exactly why each clip ranked where
it did. On low-view videos with no heatmap/chapters, absent signals drop out and
their weight redistributes — `score` then rests on LLM + audio only.

Queue runs write `output/queue_report.json` (`ok` / `failed`). Existing `clips.json` is skipped unless `--force`.

## CLI flags

| Flag | Default | Notes |
|------|---------|-------|
| `--num-clips` | `3` | Max clips kept per video |
| `--min-score` | `0` | Drop clips below this score |
| `--format` | `max` | Uncapped best (YoutubeDownloader-style Highest+Mp4), or `360`/`480`/`720`/`1080` |
| `--language` | auto | Whisper language code |
| `--render` | off | Cut original-ratio mp4s |
| `--accurate-cut` | off | With `--render`, re-encode for frame-accurate cuts |
| `--force` | off | Redo even if `clips.json` exists |

## Captions

```bash
python captions.py path/to/clip.mp4
python captions.py a.mp4 b.mp4 --burn
```

Writes `.srt` (CapCut/Premiere) and karaoke-style `.ass`. `--burn` hard-burns the ASS via ffmpeg.

Env knobs: `CAPTION_FONT`, `CAPTION_FONT_SIZE`, `CAPTION_HIGHLIGHT_COLOR`, `CAPTION_MAX_WORDS`.

## Config (`.env`)

| Var | Default | Notes |
|-----|---------|-------|
| `LLM_PROVIDER` | `openai` | `openai` or `gemini` |
| `OPENAI_API_KEY` / `GEMINI_API_KEY` | — | Required for the chosen provider |
| `LOCAL_WHISPER_MODEL` | `base` | tiny → large-v3 |
| `LOCAL_WHISPER_DEVICE` | `auto` | auto / cpu / cuda |
| `LOCAL_OUTPUT_DIR` | `output` | Root output folder |
| `DOWNLOAD_FORMAT` | `max` | `max` (uncapped) or 360 / 480 / 720 / 1080 |
| `RERANK_WEIGHTS` | `llm:0.45,replay:0.25,audio:0.20,chapter:0.10` | Signal fusion weights |
| `AUDIO_ENERGY` | `true` | Loudness/spike/pause scoring (ffmpeg+numpy) |
| `PEAK_LEAD_SECONDS` / `PEAK_TAIL_SECONDS` | `5` / `5` | Context padding around replay peaks |
| `DEDUPE_SIMILARITY` | `0.6` | Transcript-overlap threshold for near-duplicate clips |

## How it works

1. Download (yt-dlp, cached) at max available quality by default (mp4-preferring merge)
2. Transcribe (faster-whisper, SRT-cached)
3. Gather signals: YouTube replay heatmap, chapters, audio energy, semantic boundaries
4. Rank highlights via LLM (virality framework) — hinted with peaks/chapters/boundaries
5. **Fuse** LLM + replay + audio + chapter into a calibrated score (rank-normalized per video)
6. Expand peak clips to capture the setup (context) → peak → payoff
7. Dedupe by time and transcript similarity; snap to sentence boundaries
8. Write `clips.json` (+ `heatmap.json`) — optionally `--render` original-ratio cuts

See `UPLIFT_PLAN.md` for the full design and the replay-holdout validation
(`python -m eval.replay_holdout <urls>`).

## Project layout

```
main.py                 clip-finding CLI
captions.py             captions CLI
requirements.txt
.env.example
UPLIFT_PLAN.md          signal-fusion design + validation
eval/replay_holdout.py  no-label ranking validation
shorts_generator/
  pipeline.py           find_clips() — orchestrates signals + fusion
  queue.py              multi-URL + queue_report.json
  signals.py            replay heatmap, chapters, audio energy, boundaries
  rerank.py             weighted fusion, peak expansion, semantic dedupe
  highlights.py         LLM ranking + boundary snap
  downloader.py         yt-dlp (YouTube only, signals in meta.json)
  transcriber.py        faster-whisper
  llm.py                OpenAI / Gemini
  clipper.py            ffmpeg cut (no crop)
  captions.py           srt / ass / burn
  config.py
```

## License

MIT
