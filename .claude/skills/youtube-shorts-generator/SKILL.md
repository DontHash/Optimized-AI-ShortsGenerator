---
name: youtube-shorts-generator
description: Find viral clip timestamps from YouTube videos. Triggers on "find viral clips", "extract best moments", "make shorts from this YouTube link", "rank highlights in this podcast". Downloads via yt-dlp, transcribes with faster-whisper, ranks via OpenAI/Gemini virality framework, writes clips.json (optional --render for original-ratio mp4s). Captions are a separate captions.py step.
---

# YouTube Clip-Finding Engine

Timestamps-first clip finder. Default output is `output/<video_id>/clips.json` — not vertical shorts. Rendering and captions are opt-in.

## When to use

- "Find viral clips from this YouTube video"
- "Give me timestamps of the best moments"
- "Queue these URLs and extract highlights"

Wrong skill for: transcription-only, summarization, thumbnails, vertical auto-crop.

## Inputs

1. **Source** — YouTube URL(s) or a `.txt` of URLs (YouTube only)
2. **`num_clips`** — default 3
3. **`min_score`** — optional floor
4. **`language`** — Whisper ISO-639-1, default auto
5. **`render`** — cut original-ratio mp4s (default off)

## Prerequisites

- Python 3.10+, `ffmpeg` on PATH
- `LLM_PROVIDER=openai|gemini` + matching API key in `.env`
- `pip install -r requirements.txt`

## Run

```bash
python main.py "https://www.youtube.com/watch?v=VIDEO_ID"
python main.py urls.txt --num-clips 5 --render
python captions.py output/VIDEO_ID/1_slug.mp4 --burn
```

## Output

`output/<video_id>/clips.json` with rank, name, title, start/end (seconds + HMS), score, hook, virality_reason, transcript_excerpt.

Queue summary: `output/queue_report.json`.

## Do not

- Call MuAPI or set `--mode`
- Vertically crop / change aspect ratio
- Accept local files as clip-finder input (captions.py takes local files)
