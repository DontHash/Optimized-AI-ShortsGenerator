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
  source_<id>.mp4      # cached download
  source_<id>.srt      # cached transcript
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
      "hook_sentence": "...",
      "virality_reason": "...",
      "transcript_excerpt": "..."
    }
  ]
}
```

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

## How it works

1. Download (yt-dlp, cached) at max available quality by default (mp4-preferring merge)
2. Transcribe (faster-whisper, SRT-cached)
3. Rank highlights via LLM (virality framework: hooks, peaks, opinion bombs, …)
4. Snap timestamps to sentence boundaries; attach transcript excerpts
5. Write `clips.json` — optionally `--render` original-ratio cuts

## Project layout

```
main.py                 clip-finding CLI
captions.py             captions CLI
requirements.txt
.env.example
shorts_generator/
  pipeline.py           find_clips()
  queue.py              multi-URL + queue_report.json
  highlights.py         LLM ranking + boundary snap
  downloader.py         yt-dlp (YouTube only)
  transcriber.py        faster-whisper
  llm.py                OpenAI / Gemini
  clipper.py            ffmpeg cut (no crop)
  captions.py           srt / ass / burn
  config.py
```

## License

MIT
