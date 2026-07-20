# ClipClipper

## About

**ClipClipper** is an open-source YouTube **clip-finding engine**: paste a long video URL and get a ranked [`clips.json`](#clipsjson-excerpt) with start/end times, titles, hooks, and scores you can explain (LLM + Most Replayed + audio energy + chapters, fused per video).

The pipeline runs **locally** — `yt-dlp`, `faster-whisper`, and OpenAI or Gemini on your hardware. Optional ffmpeg cuts stay at **source aspect ratio** (no forced 9:16 crop, no clip SaaS API). A separate `captions.py` adds SRT/ASS or burn-in for editors.

This repository ([`DontHash/Optimized-AI-ShortsGenerator`](https://github.com/DontHash/Optimized-AI-ShortsGenerator)) ships the reference CLI (`main.py`). Runtime artifacts live in gitignored `output/`; see [`.gitignore`](.gitignore).

## Features

- **Ranked clip candidates** — start/end times, titles, hooks, virality notes, and per-signal scores
- **Multi-signal fusion** — LLM ranking + Most Replayed heatmap + loudness/spikes + chapter hints (weights renormalize when a signal is missing)
- **Local-first pipeline** — `yt-dlp` download, `faster-whisper` transcript, OpenAI or Gemini for highlights
- **Caching** — re-runs reuse download, SRT, audio curve, and heatmap; skip completed videos unless `--force`
- **Batch queue** — multiple URLs or a `.txt` file; summary in `output/queue_report.json`
- **Optional render** — ffmpeg cuts at source aspect ratio (no vertical crop, no third-party video API)
- **Captions helper** — SRT, karaoke ASS, optional burn-in via `captions.py`

## Requirements

| Dependency | Purpose |
|------------|---------|
| **Python 3.10+** | Runtime |
| **[ffmpeg](https://ffmpeg.org/)** | Download merge, audio analysis, optional cuts and caption burn |
| **API key** | `OPENAI_API_KEY` or `GEMINI_API_KEY` (see `.env.example`) |

Install Python packages:

```bash
pip install -r requirements.txt
```

Copy environment template and add your key:

```bash
cp .env.example .env
```

For GPU Whisper, install PyTorch separately (CPU works without it; see comment in `requirements.txt`).

## Quick start

```bash
# Timestamps + clips.json (default)
python main.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Several videos or a URL list
python main.py URL1 URL2 URL3 --num-clips 5
python main.py urls.txt

# Also export ranked MP4 segments
python main.py urls.txt --render

# Frame-accurate cuts (slower re-encode)
python main.py urls.txt --render --accurate-cut
```

## Output

Each video is written under `output/<video_id>/`:

```
output/<video_id>/
  source_<id>_max.mp4      # cached download (quality tag matches --format)
  source_<id>_max.srt      # cached transcript
  audio_energy.json        # loudness / spike / pause curve
  heatmap.json             # YouTube Most Replayed (when available)
  clips.json               # primary result
  1_slug.mp4               # only with --render
```

### `clips.json` (excerpt)

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
        "llm": 0.91,
        "replay": 0.80,
        "audio": 0.55,
        "chapter": 1.0,
        "final_score": 92.0,
        "signals_present": ["audio", "chapter", "llm", "replay"]
      }
    }
  ]
}
```

- **`score`** — fused 0–100 rank used for ordering  
- **`llm_score`** — raw model score before fusion  
- **`signals`** — which inputs contributed and how  

On low-view videos without heatmap or chapters, missing signals drop out and their weight is redistributed (typically LLM + audio only).

Queue runs append `output/queue_report.json` with `ok` / `failed` entries. Existing `clips.json` is left in place unless you pass `--force` (download and transcript caches are still reused).

## CLI reference

| Flag | Default | Description |
|------|---------|-------------|
| `--num-clips` | `3` | Maximum clips kept per video |
| `--min-score` | `0` | Drop clips below this fused score |
| `--format` | `max` | `max` (best available) or `360` / `480` / `720` / `1080` |
| `--language` | auto | Whisper language code, e.g. `en` |
| `--render` | off | Cut original-ratio MP4s |
| `--accurate-cut` | off | With `--render`, re-encode for frame-accurate boundaries |
| `--force` | off | Re-run analysis even if `clips.json` exists |
| `--no-browser-cookies` | off | Do not load YouTube cookies from the browser |
| `--cookies-from-browser` | — | Override browser (e.g. `edge`, `chrome`, `firefox`, `brave`) |
| `--cookies` | — | Path to Netscape `cookies.txt` instead of browser cookies |

Positional arguments: one or more YouTube URLs, or a `.txt` file with one URL per line.

## YouTube downloads and cookies

Age-restricted, region-locked, or bot-check failures are common without cookies. By default the downloader tries cookies from your browser (configurable in `.env` as `YTDLP_COOKIES_FROM_BROWSER`).

**Recommended for CI or headless use:** export cookies to `cookies.txt` or `cookies.json` in the project root (gitignored) or set `YTDLP_COOKIES_FILE`. File cookies take precedence over browser cookies.

```bash
python main.py "https://www.youtube.com/watch?v=..." --cookies path/to/cookies.txt
python main.py "..." --no-browser-cookies
```

See `.env.example` for `YTDLP_PLAYER_CLIENTS` and related yt-dlp tuning.

## Captions

Works on any local video file (including rendered clips):

```bash
python captions.py output/VIDEO_ID/1_the-hook.mp4
python captions.py clip1.mp4 clip2.mp4 --burn
```

Produces `.srt` (editors) and styled `.ass` (karaoke highlight). `--burn` hard-burns ASS via ffmpeg.

Environment: `CAPTION_FONT`, `CAPTION_FONT_SIZE`, `CAPTION_HIGHLIGHT_COLOR`, `CAPTION_MAX_WORDS`.

## Configuration

All knobs live in `.env`. Common settings:

| Variable | Default | Notes |
|----------|---------|--------|
| `LLM_PROVIDER` | `openai` | `openai` or `gemini` |
| `OPENAI_API_KEY` / `GEMINI_API_KEY` | — | Required for chosen provider |
| `LOCAL_WHISPER_MODEL` | `base` | `tiny` → `large-v3` |
| `LOCAL_WHISPER_DEVICE` | `auto` | `auto` / `cpu` / `cuda` |
| `LOCAL_OUTPUT_DIR` | `output` | Output root |
| `DOWNLOAD_FORMAT` | `max` | Same options as `--format` |
| `RERANK_WEIGHTS` | see `.env.example` | LLM / replay / audio / chapter fusion |
| `AUDIO_ENERGY` | `true` | ffmpeg + numpy loudness scoring |
| `PEAK_LEAD_SECONDS` / `PEAK_TAIL_SECONDS` | `5` / `5` | Context around replay peaks |
| `DEDUPE_SIMILARITY` | `0.6` | Transcript overlap threshold for near-duplicates |

Full list and defaults: [`.env.example`](.env.example).

## How it works

```mermaid
flowchart LR
  A[YouTube URL] --> B[yt-dlp download]
  B --> C[faster-whisper]
  C --> D[Signals]
  D --> E[LLM highlights]
  E --> F[Fusion + dedupe]
  F --> G[clips.json]
  G --> H[Optional ffmpeg cut]
```

1. Download (cached) — max quality by default, MP4-preferred merge  
2. Transcribe to SRT (cached)  
3. Collect replay heatmap, chapters, audio energy, semantic boundaries  
4. LLM ranks candidate moments (hinted by peaks and structure)  
5. Fuse signals into a calibrated per-video score; expand peaks for setup → payoff  
6. Dedupe by time and transcript similarity; snap to sentence boundaries  
7. Write `clips.json` (+ sidecar JSON); optionally `--render` cuts  

Design notes and validation: [`UPLIFT_PLAN.md`](UPLIFT_PLAN.md). Replay holdout eval:

```bash
python -m eval.replay_holdout urls.txt
```

## Project layout

Generated and tooling artifacts stay out of git: `output/` (runs), `graphify-out/` and `.graphify_*` (optional local graphify analysis), plus `.env` and cookie files — see [`.gitignore`](.gitignore).

```
main.py                   Clip-finding CLI
captions.py               Standalone captions CLI
requirements.txt
.env.example
UPLIFT_PLAN.md            Signal fusion design + validation notes
eval/replay_holdout.py    Ranking eval without manual labels
shorts_generator/
  pipeline.py             find_clips() orchestration
  queue.py                Multi-URL processing + queue report
  signals.py              Heatmap, chapters, audio, boundaries
  rerank.py               Fusion, peak expansion, dedupe
  highlights.py           LLM ranking + boundary snap
  downloader.py           yt-dlp (YouTube + metadata for signals)
  transcriber.py          faster-whisper
  llm.py                  OpenAI / Gemini
  clipper.py              ffmpeg cut (no crop)
  captions.py             SRT / ASS / burn
  config.py
```

## License

MIT — use and modify freely; attribution appreciated.
