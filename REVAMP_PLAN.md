# Clipper Revamp Plan

Turn `AI-Youtube-Shorts-Generator` from a "vertical shorts renderer" into a **clip-finding engine**: it finds the viral moments and hands you timestamps + original-ratio clips; you (or a later UI) do the creative cropping.

---

## Goals (what you asked for)

1. **Remove the MuAPI implementation** — local pipeline only.
2. **Remove vertical cropping** — no OpenCV reframing. Keep the original aspect ratio.
3. **Timestamps-first output** — every highlight gets a name + start/end time, saved as JSON. Rendering actual clip files is optional.
4. **Queue multiple YouTube videos** — process a list of URLs in one run.
5. **1080p downloads** — bump quality from the current 720p default.
6. **YouTube-only input** — drop local-file input support (`file://` and raw paths). *(Assumption from your message — flip this if I misread.)*
7. **Keep the OpenAI ⇄ Gemini switch** (`LLM_PROVIDER`) exactly as it is. No Ollama.
8. **Captions module (separate feature)** — give it a video, get shorts-style captions back.
9. **UI comes last** — functionality first.

---

## Phase 0 — Removals (do this first)

### 0.1 Remove MuAPI / API mode

| Action | File |
|---|---|
| Delete | `shorts_generator/muapi.py` |
| Delete | `shorts_generator/downloader.py` (MuAPI download) |
| Delete | `shorts_generator/transcriber.py` (MuAPI whisper) |
| Delete | `shorts_generator/clipper.py` (MuAPI autocrop) |
| Edit | `shorts_generator/pipeline.py` — delete `_run_api()`, delete the `mode` parameter, `_run_local()` becomes the only path |
| Edit | `shorts_generator/highlights.py` — remove `call_muapi_llm` |
| Edit | `shorts_generator/config.py` — remove `MUAPI_*`, `POLL_*`, `require_api_key()` |
| Edit | `main.py` — remove `--mode` flag |
| Edit | `.env.example` — remove `MUAPI_API_KEY` |
| Edit | `requirements.txt` / `requirements-local.txt` — local deps become the *only* requirements file; `requests` may become removable |

Side effect: the `shorts_generator/local/` subpackage can be flattened into `shorts_generator/` since "local" is no longer a distinction. This also kills the import cycles the graph flagged (`__init__.py → pipeline.py → clipper.py → __init__.py` etc.).

### 0.2 Remove vertical cropping

| Action | File |
|---|---|
| Edit | `shorts_generator/local/clipper.py` — delete `_reframe_vertical()`, `_ratio()`, and the OpenCV dependency entirely. Keep `_cut_subclip()` (ffmpeg time-cut) |
| Edit | `main.py` — remove `--aspect-ratio` flag |
| Edit | `requirements-local.txt` — drop `opencv-python` |

Cutting at the original ratio with ffmpeg stays: `-c copy` (instant, lossless) as default, with re-encode as a fallback flag for frame-accurate cuts (`-c copy` snaps to keyframes and can be off by up to a couple of seconds).

---

## Phase 1 — Core functionality

### 1.1 Timestamps-first output (the new product shape)

New default behavior: **no rendering at all.** The pipeline outputs one JSON per video:

```json
{
  "video_id": "6G0bG6qWqTs",
  "video_title": "How I Built a $1M Business",
  "source_url": "https://www.youtube.com/watch?v=6G0bG6qWqTs",
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

- Written to `output/<video_id>/clips.json` automatically (no `--output-json` flag needed — it's the whole point now).
- Add `start_hms`/`end_hms` human-readable times so you can scrub to them in any player.
- `--render` flag opts in to actually cutting `output/<video_id>/<rank>_<name>.mp4` files at original ratio.

### 1.2 Queue multiple videos

```bash
python main.py urls.txt              # file with one URL per line
python main.py URL1 URL2 URL3        # or several URLs directly
```

- New `shorts_generator/queue.py`: iterates URLs, one folder per video (`output/<video_id>/`).
- **Fault isolation**: one failed video logs the error and moves on; a `queue_report.json` at the end summarizes ok/failed.
- **Resumability**: if `output/<video_id>/clips.json` already exists, skip (or `--force` to redo). Download + `.srt` transcript caching already exists — keep it, it makes re-runs nearly free.
- Sequential processing is correct here (Whisper saturates the CPU/GPU anyway); don't parallelize transcription.

### 1.3 1080p downloads

- `config.py`: new `DOWNLOAD_FORMAT` env default = `"1080"`; `main.py` `--format` default flips to `1080`.
- `_format_for()` in the downloader already supports arbitrary heights — the selector `bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]` just works, ffmpeg merges the streams.
- Caveat to handle: 1080p on YouTube is usually VP9/webm, not mp4. Loosen the selector to `bestvideo[height<=1080]+bestaudio/best[height<=1080]` with `merge_output_format: "mp4"` so you don't silently fall back to 720p mp4. Requires ffmpeg on PATH (already required).

### 1.4 YouTube-only input

- Remove `_resolve_local_path()` from the downloader; error clearly on non-YouTube input.
- Keep `_extract_youtube_video_id()` — it becomes mandatory (used for output folders and caching).

### 1.5 LLM provider (unchanged)

`LLM_PROVIDER=openai|gemini` with `OPENAI_API_KEY` / `GEMINI_API_KEY` stays exactly as-is (`shorts_generator/local/llm.py`, `config.py`).

---

## Phase 2 — Captions module (separate feature)

**Completely independent of the clipping pipeline.** It is never run as part of clip generation — it's a separate command you invoke later, giving it the local file path(s) of whatever videos you want captioned (pipeline-rendered clips, your own edits, anything on disk):

```bash
python captions.py "D:\clips\my-edited-short.mp4"
python captions.py output/<video_id>/1_the-one-mistake.mp4 output/<video_id>/2_second-clip.mp4
```

If run with no arguments, it prompts for file location(s) interactively.

- New `shorts_generator/captions.py` + `captions.py` entry point.
- Re-uses `transcribe_local()` but with **`word_timestamps=True`** in faster-whisper — shorts-style captions need word-level timing, not sentence segments.
- Output formats:
  - `.srt` — universal, imports into CapCut/Premiere/YouTube Studio.
  - `.ass` — styled karaoke-style captions (word-by-word pop-in, the "shorts look"): 2–4 words per line, centered, bold.
  - `--burn` flag: ffmpeg `subtitles=` filter to hard-burn the `.ass` onto the video for a ready-to-post file.
- Style knobs in `.env`: font, size, highlight color, max words per caption line.

---

## Phase 3 — UI (later, don't build yet)

When the engine is stable: a thin local web UI (FastAPI + one HTML page, or Streamlit) that:
- takes pasted URLs → shows queue progress,
- lists clips with score/hook/timestamps, embedded YouTube player seeking to `start_time` (no need to render anything to preview!),
- buttons: "render this clip", "generate captions".

The timestamps-first JSON is exactly the API a UI needs — that's why Phase 1.1 comes first.

---

## Extra improvements worth doing (my recommendations)

Ordered by value-for-effort:

1. **Boundary snapping to sentence edges** *(high value)* — LLM timestamps often cut mid-word. Snap `start_time` back to the nearest segment start and `end_time` forward to the nearest segment end (± small padding, e.g. 0.3s of silence). Cheap to implement — the transcript segments are already in memory — and it fixes the single most amateur-feeling artifact of auto-clippers.
2. **Transcript excerpt per clip** *(high value, trivial)* — include the actual transcript text inside each clip's JSON entry. Lets you judge a clip without watching it, and feeds the captions module later.
3. **Retry / fallback between providers** *(medium)* — if Gemini rate-limits (free tier), one retry with backoff, then optional automatic fallback to the other configured provider.
4. **`--min-score` filter** *(trivial)* — don't return clips below a score threshold instead of always returning N; some videos just don't have 5 good moments. Honest output beats padded output.
5. **Chapter/heatmap awareness** *(medium)* — yt-dlp exposes YouTube chapters and (via extractors) the "most replayed" heatmap. Feed chapter titles into the LLM prompt as hints, or boost candidate scores that overlap replay peaks. This is data the original repo ignores and paid tools use.
6. **SponsorBlock skip** *(low effort)* — yt-dlp integrates SponsorBlock; mark sponsor segments so highlights never land inside an ad read.
7. **Structured logging + `--quiet`** *(low)* — queue runs need clean per-video log lines, not interleaved prints.
8. **Cookie support for age-restricted videos** *(low)* — `--cookies-from-browser` passthrough to yt-dlp; queue runs die on age-gated videos otherwise.

Skipped deliberately: Ollama (you rejected it), speaker diarization and scene detection (heavy deps, marginal gain at this stage), parallel transcription (CPU-bound anyway).

---

## Suggested build order

```
Phase 0.1  Remove MuAPI            ← unblocks everything, deletes ~5 files
Phase 0.2  Remove cropping         ← deletes OpenCV, simplifies clipper
Phase 1.1  Timestamps-first JSON   ← the new core product
Phase 1.3  1080p default           ← one-line-ish
Phase 1.4  YouTube-only            ← small deletion
Phase 1.2  Queue                   ← builds on stable single-video flow
Extras 1+2 Boundary snap + excerpts
Phase 2    Captions module
Extras 3-8 As desired
Phase 3    UI
```

Phases 0–1 are roughly a day of focused work; captions another half-day; extras incremental.
